#!/usr/bin/env node

"use strict";

// reumanlab connector — persistent runtime for AgenticPlug Phase 3.
//
// Implements the connector contract defined in:
//   https://github.com/alrobles/agenticplug/blob/main/docs/kuhpc-connector-contract.md
//
// Security invariants (§6):
//   - No arbitrary shell
//   - Allowlist-only path access
//   - Bounded output per capability
//   - Sanitized errors (§4.2)
//   - Fail-closed config (§6.5)
//   - Write capabilities return 501 (§2.2)
//
// Start:
//   HPC_USER=... HPC_HOST=... CONNECTOR_TOKEN=... node main.js
//
// See docs/reumanlab-connector-deploy.md for systemd setup.

const http = require("http");
const crypto = require("crypto");
const { validate } = require("./config");
const { dispatch } = require("./capabilities");
const { sanitize } = require("./sanitize");
const audit = require("./audit");

// ── Fail-closed config check ───────────────────────────────────────────

const result = validate(process.env);
if (!result.ok) {
  const msg = {
    error: "fail-closed: required configuration missing",
    missing: result.missing,
    timestamp: new Date().toISOString(),
  };
  process.stderr.write(JSON.stringify(msg) + "\n");
  process.exit(1);
}
const CONFIG = result.config;

// ── Token verification ─────────────────────────────────────────────────

const TOKEN_HASH = crypto
  .createHash("sha256")
  .update(CONFIG.connectorToken)
  .digest("hex");

function verifyBearer(authHeader) {
  if (!authHeader || !authHeader.startsWith("Bearer ")) return false;
  const provided = authHeader.slice(7);
  const providedHash = crypto.createHash("sha256").update(provided).digest("hex");
  // Constant-time comparison via SHA-256 of both hashes
  const a = Buffer.from(TOKEN_HASH, "hex");
  const b = Buffer.from(providedHash, "hex");
  try {
    return crypto.timingSafeEqual(a, b);
  } catch {
    return false;
  }
}

// ── HTTP helpers ───────────────────────────────────────────────────────

const MAX_BODY_BYTES = 1048576; // 1 MiB

function sendJSON(res, statusCode, data) {
  const body = JSON.stringify(data);
  res.writeHead(statusCode, {
    "Content-Type": "application/json",
    "Content-Length": Buffer.byteLength(body),
  });
  res.end(body);
}

function readBody(req) {
  return new Promise((resolve, reject) => {
    const chunks = [];
    let total = 0;
    req.on("data", (chunk) => {
      total += chunk.length;
      if (total > MAX_BODY_BYTES) {
        req.destroy();
        reject(new Error("body too large"));
        return;
      }
      chunks.push(chunk);
    });
    req.on("end", () => resolve(Buffer.concat(chunks)));
    req.on("error", reject);
  });
}

function parseJSON(buf) {
  try {
    return JSON.parse(buf.toString("utf8"));
  } catch {
    return null;
  }
}

// ── Request handler ────────────────────────────────────────────────────

async function handleRequest(req, res) {
  // Health probe — unauthenticated, for systemd/load-balancer checks
  if (req.url === "/healthz" && req.method === "GET") {
    return sendJSON(res, 200, { status: "ok", connector_id: CONFIG.connectorId });
  }

  // All other routes require POST /v1/capabilities
  if (req.method !== "POST" || req.url !== "/v1/capabilities") {
    return sendJSON(res, 404, { error: "not found" });
  }

  // Auth check — fail with 401 before any capability work
  if (!verifyBearer(req.headers["authorization"])) {
    return sendJSON(res, 401, { error: "unauthorized" });
  }

  const startMs = Date.now();
  let capability = "";
  let userId = "unknown";
  let taskId = "unknown";

  try {
    const buf = await readBody(req);
    const body = parseJSON(buf);

    if (!body || typeof body.capability !== "string") {
      return sendJSON(res, 400, {
        error: "payload must include a 'capability' string field",
        code: "invalid_payload",
        capability: "",
      });
    }

    capability = body.capability;
    userId = body.user_id || "unknown";
    taskId = body.task_id || "unknown";
    const payload = body.payload || {};

    const outcome = await dispatch(capability, payload, CONFIG);

    const durationMs = Date.now() - startMs;

    if (outcome.error) {
      // Dispatch returned an error (path_not_allowed, capability_disabled, etc.)
      // Check if the result itself has an error flag (e.g. path validation)
      audit.emit({
        connectorId: CONFIG.connectorId,
        capability,
        userId,
        taskId,
        resultStatus: "error",
        errorCode: outcome.error.code,
        errorMessage: sanitize(outcome.error.error),
        durationMs,
      });
      return sendJSON(res, outcome.status, outcome.error);
    }

    // Check for inline error from path-validating capabilities
    if (outcome.result && outcome.result.error === true) {
      audit.emit({
        connectorId: CONFIG.connectorId,
        capability,
        userId,
        taskId,
        resultStatus: "error",
        errorCode: outcome.result.code,
        errorMessage: sanitize(outcome.result.message),
        durationMs,
      });
      const httpStatus = outcome.result.code === "path_traversal" ? 400 : 403;
      return sendJSON(res, httpStatus, {
        error: outcome.result.message,
        code: outcome.result.code,
        capability,
      });
    }

    audit.emit({
      connectorId: CONFIG.connectorId,
      capability,
      userId,
      taskId,
      resultStatus: "ok",
      durationMs,
    });
    return sendJSON(res, outcome.status, outcome.result);
  } catch (err) {
    const durationMs = Date.now() - startMs;
    const sanitized = sanitize(err.message);
    const code = err.killed ? "scheduler_unreachable" : "connector_error";
    audit.emit({
      connectorId: CONFIG.connectorId,
      capability,
      userId,
      taskId,
      resultStatus: "error",
      errorCode: code,
      errorMessage: sanitized,
      durationMs,
    });
    return sendJSON(res, code === "scheduler_unreachable" ? 503 : 500, {
      error: sanitized,
      code,
      capability,
    });
  }
}

// ── Server ─────────────────────────────────────────────────────────────

const server = http.createServer(handleRequest);

server.listen(CONFIG.port, CONFIG.host, () => {
  const info = {
    event: "connector_started",
    connector_id: CONFIG.connectorId,
    host: CONFIG.host,
    port: CONFIG.port,
    timestamp: new Date().toISOString(),
    capabilities_read: [
      "remote.health",
      "remote.info",
      "remote.list_home",
      "hpc.status",
      "hpc.queue",
      "hpc.logs.read",
    ],
    capabilities_write_disabled: [
      "hpc.submit",
      "hpc.cancel",
      "hpc.write",
      "hpc.delete",
    ],
  };
  process.stdout.write(JSON.stringify(info) + "\n");
});

// Export for testing
module.exports = { server, CONFIG, verifyBearer, handleRequest };

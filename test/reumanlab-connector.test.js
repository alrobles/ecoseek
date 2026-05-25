#!/usr/bin/env node

"use strict";

// Tests for the reumanlab connector runtime.
// Covers: allowed command, denied command, timeout, config missing, sanitized error.
// No external dependencies — uses Node's built-in assert + http.

const assert = require("assert");
const http = require("http");

// ── Helpers ────────────────────────────────────────────────────────────

let passed = 0;
let failed = 0;
const failures = [];

function test(name, fn) {
  return fn()
    .then(() => {
      passed++;
      console.log(`  PASS  ${name}`);
    })
    .catch((err) => {
      failed++;
      failures.push({ name, error: err });
      console.log(`  FAIL  ${name}`);
      console.log(`        ${err.message}`);
    });
}

// ── Unit tests: config.validate ────────────────────────────────────────

const { validate, REQUIRED_VARS } = require("../connector/reumanlab/config");

async function configTests() {
  console.log("\n== config ==");

  await test("validate returns ok:false when HPC_USER is missing", async () => {
    const result = validate({ HPC_HOST: "h", CONNECTOR_TOKEN: "t" });
    assert.strictEqual(result.ok, false);
    assert.ok(result.missing.includes("HPC_USER"));
  });

  await test("validate returns ok:false when HPC_HOST is missing", async () => {
    const result = validate({ HPC_USER: "u", CONNECTOR_TOKEN: "t" });
    assert.strictEqual(result.ok, false);
    assert.ok(result.missing.includes("HPC_HOST"));
  });

  await test("validate returns ok:false when CONNECTOR_TOKEN is missing", async () => {
    const result = validate({ HPC_USER: "u", HPC_HOST: "h" });
    assert.strictEqual(result.ok, false);
    assert.ok(result.missing.includes("CONNECTOR_TOKEN"));
  });

  await test("validate returns ok:true with all required vars", async () => {
    const result = validate({
      HPC_USER: "testuser",
      HPC_HOST: "hpc.example.edu",
      CONNECTOR_TOKEN: "secret",
    });
    assert.strictEqual(result.ok, true);
    assert.strictEqual(result.config.hpcUser, "testuser");
    assert.strictEqual(result.config.hpcHost, "hpc.example.edu");
  });

  await test("validate parses HPC_ALLOWED_LOG_PATHS", async () => {
    const result = validate({
      HPC_USER: "u",
      HPC_HOST: "h",
      CONNECTOR_TOKEN: "t",
      HPC_ALLOWED_LOG_PATHS: "/scratch/user,/home/user/work",
    });
    assert.deepStrictEqual(result.config.allowedPaths, ["/scratch/user", "/home/user/work"]);
  });

  await test("validate uses defaults for optional vars", async () => {
    const result = validate({
      HPC_USER: "u",
      HPC_HOST: "h",
      CONNECTOR_TOKEN: "t",
    });
    assert.strictEqual(result.config.connectorId, "reumanlab");
    assert.strictEqual(result.config.port, 8000);
    assert.strictEqual(result.config.host, "127.0.0.1");
    assert.strictEqual(result.config.commandTimeoutMs, 30000);
  });
}

// ── Unit tests: sanitize ───────────────────────────────────────────────

const { sanitize, MAX_ERROR_LENGTH } = require("../connector/reumanlab/sanitize");

async function sanitizeTests() {
  console.log("\n== sanitize ==");

  await test("strips user@host from SSH errors", async () => {
    const result = sanitize("ssh: connect to host hpc.crc.ku.edu port 22: Connection refused");
    assert.ok(!result.includes("hpc.crc.ku.edu"), `got: ${result}`);
    assert.ok(result.includes("[REDACTED]"));
  });

  await test("strips IPv4 addresses", async () => {
    const result = sanitize("connection to 192.168.1.100 failed");
    assert.ok(!result.includes("192.168.1.100"), `got: ${result}`);
    assert.ok(result.includes("[REDACTED]"));
  });

  await test("strips absolute paths", async () => {
    const result = sanitize("Error reading /home/user/secret/data.txt");
    assert.ok(!result.includes("/home/user/secret"), `got: ${result}`);
    assert.ok(result.includes("[REDACTED]"));
  });

  await test("strips long tokens (>= 20 hex chars)", async () => {
    const token = "abcdef0123456789abcdef01234567890";
    const result = sanitize(`token ${token} leaked`);
    assert.ok(!result.includes(token), `got: ${result}`);
    assert.ok(result.includes("[REDACTED]"));
  });

  await test("truncates to 512 characters", async () => {
    const long = "a".repeat(1000);
    const result = sanitize(long);
    assert.ok(result.length <= MAX_ERROR_LENGTH, `length: ${result.length}`);
  });

  await test("returns 'internal error' for empty input", async () => {
    assert.strictEqual(sanitize(""), "internal error");
    assert.strictEqual(sanitize(null), "internal error");
    assert.strictEqual(sanitize(undefined), "internal error");
  });
}

// ── Unit tests: capabilities ───────────────────────────────────────────

const {
  dispatch,
  validatePath,
  clamp,
  remoteHealth,
  remoteInfo,
  validateGbifArgs,
  gbifQuery,
  READ_CAPABILITIES,
  WRITE_CAPABILITIES,
  GBIF_MAX_LIMIT,
} = require("../connector/reumanlab/capabilities");

const mockConfig = {
  hpcUser: "testuser",
  hpcHost: "hpc.test.edu",
  connectorToken: "test-token",
  connectorId: "reumanlab",
  port: 8000,
  host: "127.0.0.1",
  allowedPaths: ["/scratch/testuser", "/home/testuser/work"],
  commandTimeoutMs: 5000,
  maxOutputBytes: 1048576,
  gbifdbDir: "/home/a474r867/work/gbifdata/gbif_effort/gbifdata",
  apptainerImage: "/home/a474r867/work/gbifdata/gbif_effort/container/gbif-kde.sif",
  gbifQueryR: "/home/a474r867/work/scripts/gbif_query.R",
  gbifRunner: "/home/a474r867/work/scripts/run_gbif_query.sh",
  gbifTimeoutMs: 60000,
  gbifMaxOutputBytes: 16777216,
};

// Mock exec function that returns canned output
function mockExec(cmd, args, opts) {
  const argStr = args.join(" ");
  if (argStr.includes("sinfo")) {
    return Promise.resolve("batch*  up  infinite  10/5/2/17  node[01-17]\n");
  }
  if (argStr.includes("squeue")) {
    return Promise.resolve(
      "JOBID   NAME      STATE   TIME     NODELIST\n" +
      "12345   train     RUNNING 1:23:45  node03\n"
    );
  }
  if (argStr.includes("ls -1a")) {
    return Promise.resolve("results\nrun.log\ndata\n");
  }
  if (argStr.includes("tail")) {
    return Promise.resolve("Epoch 1/10: loss=0.842\nEpoch 2/10: loss=0.671\n");
  }
  return Promise.resolve("");
}

// Mock exec that simulates timeout (killed process)
function mockExecTimeout() {
  const err = new Error("Command timed out");
  err.killed = true;
  return Promise.reject(err);
}

async function capabilityTests() {
  console.log("\n== capabilities ==");

  // clamp
  await test("clamp enforces min/max", async () => {
    assert.strictEqual(clamp(0, 1, 200), 1);
    assert.strictEqual(clamp(300, 1, 200), 200);
    assert.strictEqual(clamp(50, 1, 200), 50);
    assert.strictEqual(clamp("abc", 1, 200), 1);
  });

  // validatePath
  await test("validatePath allows paths under allowlist", async () => {
    const result = validatePath("/scratch/testuser/job-123/out.log", mockConfig.allowedPaths);
    assert.strictEqual(result, "/scratch/testuser/job-123/out.log");
  });

  await test("validatePath rejects paths outside allowlist", async () => {
    const result = validatePath("/etc/passwd", mockConfig.allowedPaths);
    assert.strictEqual(result, null);
  });

  await test("validatePath rejects path traversal (..)", async () => {
    const result = validatePath("/scratch/testuser/../../../etc/passwd", mockConfig.allowedPaths);
    assert.strictEqual(result, null);
  });

  await test("validatePath rejects shell metacharacters", async () => {
    assert.strictEqual(validatePath("/scratch/testuser/$(whoami)", mockConfig.allowedPaths), null);
    assert.strictEqual(validatePath("/scratch/testuser/;rm -rf /", mockConfig.allowedPaths), null);
    assert.strictEqual(validatePath("/scratch/testuser/|cat /etc/shadow", mockConfig.allowedPaths), null);
  });

  await test("validatePath rejects null bytes", async () => {
    assert.strictEqual(validatePath("/scratch/testuser/\0evil", mockConfig.allowedPaths), null);
  });

  await test("validatePath rejects empty / non-string input", async () => {
    assert.strictEqual(validatePath("", mockConfig.allowedPaths), null);
    assert.strictEqual(validatePath(null, mockConfig.allowedPaths), null);
    assert.strictEqual(validatePath(42, mockConfig.allowedPaths), null);
  });

  // remote.health — allowed command
  await test("remote.health returns structured result", async () => {
    const result = remoteHealth(mockConfig);
    assert.strictEqual(result.status, "ok");
    assert.strictEqual(result.connector_id, "reumanlab");
    assert.strictEqual(result.version, "0.3.0");
    assert.strictEqual(typeof result.uptime_seconds, "number");
  });

  // remote.info — redacted fields
  await test("remote.info redacts sensitive fields", async () => {
    const result = remoteInfo(mockConfig);
    assert.strictEqual(result.node_name, "[REDACTED]");
    assert.strictEqual(result.hpc_user, "[REDACTED]");
    assert.strictEqual(result.hpc_host, "[REDACTED]");
    assert.ok(result.node_version.startsWith("v"));
  });

  // dispatch — allowed read capabilities
  await test("dispatch remote.health returns 200", async () => {
    const out = await dispatch("remote.health", {}, mockConfig);
    assert.strictEqual(out.status, 200);
    assert.strictEqual(out.result.status, "ok");
  });

  await test("dispatch remote.info returns 200", async () => {
    const out = await dispatch("remote.info", {}, mockConfig);
    assert.strictEqual(out.status, 200);
    assert.strictEqual(out.result.hpc_user, "[REDACTED]");
  });

  await test("dispatch remote.list_home returns entries (mock)", async () => {
    const out = await dispatch(
      "remote.list_home",
      { path: "/scratch/testuser" },
      mockConfig,
      mockExec
    );
    assert.strictEqual(out.status, 200);
    assert.ok(Array.isArray(out.result.entries));
    assert.ok(out.result.entries.length > 0);
  });

  await test("dispatch hpc.status returns scheduler info (mock)", async () => {
    const out = await dispatch("hpc.status", {}, mockConfig, mockExec);
    assert.strictEqual(out.status, 200);
    assert.strictEqual(out.result.scheduler, "slurm");
    assert.strictEqual(out.result.scheduler_reachable, true);
  });

  await test("dispatch hpc.queue returns squeue lines (mock)", async () => {
    const out = await dispatch("hpc.queue", { max_lines: 50 }, mockConfig, mockExec);
    assert.strictEqual(out.status, 200);
    assert.strictEqual(out.result.command, "squeue");
    assert.ok(out.result.lines.length > 0);
  });

  await test("dispatch hpc.logs.read returns log lines (mock)", async () => {
    const out = await dispatch(
      "hpc.logs.read",
      { path: "/scratch/testuser/out.log", lines: 100 },
      mockConfig,
      mockExec
    );
    assert.strictEqual(out.status, 200);
    assert.ok(Array.isArray(out.result.lines));
    assert.ok(out.result.lines.some((l) => l.includes("Epoch")));
  });

  // dispatch — denied commands (write capabilities)
  await test("dispatch hpc.submit returns 501 capability_disabled", async () => {
    const out = await dispatch("hpc.submit", {}, mockConfig);
    assert.strictEqual(out.status, 501);
    assert.strictEqual(out.error.code, "capability_disabled");
  });

  await test("dispatch hpc.cancel returns 501 capability_disabled", async () => {
    const out = await dispatch("hpc.cancel", {}, mockConfig);
    assert.strictEqual(out.status, 501);
    assert.strictEqual(out.error.code, "capability_disabled");
  });

  await test("dispatch hpc.write returns 501 capability_disabled", async () => {
    const out = await dispatch("hpc.write", {}, mockConfig);
    assert.strictEqual(out.status, 501);
    assert.strictEqual(out.error.code, "capability_disabled");
  });

  await test("dispatch hpc.delete returns 501 capability_disabled", async () => {
    const out = await dispatch("hpc.delete", {}, mockConfig);
    assert.strictEqual(out.status, 501);
    assert.strictEqual(out.error.code, "capability_disabled");
  });

  // dispatch — unknown capability
  await test("dispatch unknown capability returns invalid_payload", async () => {
    const out = await dispatch("not.a.real.cap", {}, mockConfig);
    assert.strictEqual(out.status, 400);
    assert.strictEqual(out.error.code, "invalid_payload");
  });

  // dispatch — path not allowed
  await test("dispatch remote.list_home with disallowed path returns error", async () => {
    const out = await dispatch(
      "remote.list_home",
      { path: "/etc/shadow" },
      mockConfig,
      mockExec
    );
    assert.strictEqual(out.status, 200); // dispatch returns 200, inline error
    assert.strictEqual(out.result.error, true);
    assert.strictEqual(out.result.code, "path_not_allowed");
  });

  await test("dispatch hpc.logs.read with traversal returns path_traversal", async () => {
    const out = await dispatch(
      "hpc.logs.read",
      { path: "/scratch/testuser/../../etc/passwd" },
      mockConfig,
      mockExec
    );
    assert.strictEqual(out.result.error, true);
    assert.strictEqual(out.result.code, "path_traversal");
  });

  // dispatch — missing required payload fields
  await test("dispatch remote.list_home without path returns invalid_payload", async () => {
    const out = await dispatch("remote.list_home", {}, mockConfig, mockExec);
    assert.strictEqual(out.status, 400);
    assert.strictEqual(out.error.code, "invalid_payload");
  });

  await test("dispatch hpc.logs.read without path returns invalid_payload", async () => {
    const out = await dispatch("hpc.logs.read", {}, mockConfig, mockExec);
    assert.strictEqual(out.status, 400);
    assert.strictEqual(out.error.code, "invalid_payload");
  });
}

// ── Timeout test ───────────────────────────────────────────────────────

async function timeoutTests() {
  console.log("\n== timeout ==");

  await test("hpc.status timeout produces scheduler_unreachable-style error", async () => {
    try {
      await dispatch("hpc.status", {}, mockConfig, mockExecTimeout);
      assert.fail("should have thrown");
    } catch (err) {
      assert.ok(err.killed === true || err.message.includes("timed out"));
    }
  });

  await test("hpc.queue timeout throws killed error", async () => {
    try {
      await dispatch("hpc.queue", {}, mockConfig, mockExecTimeout);
      assert.fail("should have thrown");
    } catch (err) {
      assert.ok(err.killed === true);
    }
  });

  // ── gbif.query: arg validation ───────────────────────────────────────
  await test("validateGbifArgs rejects shell meta in species_name", async () => {
    const v = validateGbifArgs({ species_name: "foo; rm -rf /" });
    assert.strictEqual(v.ok, false);
    assert.strictEqual(v.code, "invalid_spec");
  });

  await test("validateGbifArgs rejects species_name > 128 chars", async () => {
    const v = validateGbifArgs({ species_name: "A".repeat(200) });
    assert.strictEqual(v.ok, false);
  });

  await test("validateGbifArgs rejects negative taxon_key", async () => {
    const v = validateGbifArgs({ taxon_key: -1 });
    assert.strictEqual(v.ok, false);
  });

  await test("validateGbifArgs rejects unordered year_range", async () => {
    const v = validateGbifArgs({ year_range: [2020, 2010] });
    assert.strictEqual(v.ok, false);
  });

  await test("validateGbifArgs rejects out-of-bounds year_range", async () => {
    const v = validateGbifArgs({ year_range: [1600, 2000] });
    assert.strictEqual(v.ok, false);
  });

  await test("validateGbifArgs rejects unordered bbox", async () => {
    const v = validateGbifArgs({ bbox: [10, 20, 5, 30] });
    assert.strictEqual(v.ok, false);
  });

  await test("validateGbifArgs rejects limit > GBIF_MAX_LIMIT", async () => {
    const v = validateGbifArgs({ limit: GBIF_MAX_LIMIT + 1 });
    assert.strictEqual(v.ok, false);
    assert.strictEqual(v.code, "row_cap_exceeded");
  });

  await test("validateGbifArgs accepts default empty args (uses default limit)", async () => {
    const v = validateGbifArgs({});
    assert.strictEqual(v.ok, true);
    assert.strictEqual(v.spec.limit, 50000);
  });

  await test("validateGbifArgs forwards all optional filters", async () => {
    const v = validateGbifArgs({
      species_name: "Caligus elongatus",
      taxon_key: 2294018,
      year_range: [2010, 2020],
      bbox: [-10, 30, 20, 60],
      limit: 500,
    });
    assert.strictEqual(v.ok, true);
    assert.strictEqual(v.spec.species_name, "Caligus elongatus");
    assert.strictEqual(v.spec.taxon_key, 2294018);
    assert.deepStrictEqual(v.spec.year_range, [2010, 2020]);
    assert.deepStrictEqual(v.spec.bbox, [-10, 30, 20, 60]);
    assert.strictEqual(v.spec.limit, 500);
  });

  // ── gbif.query: SSH integration via mock execFn ──────────────────────
  function mockGbifExecOk() {
    const envelope = JSON.stringify({
      data: [
        [50.1, 10.5, "Caligus elongatus", 2294018, 2018, 6, "HUMAN_OBSERVATION"],
        [51.0, 11.0, "Caligus elongatus", 2294018, 2019, 7, "PRESERVED_SPECIMEN"],
      ],
      error: null,
    });
    return Promise.resolve(envelope + "\n");
  }

  function mockGbifExecMalformed() {
    return Promise.resolve("this is not JSON\n");
  }

  function mockGbifExecTimeoutKilled() {
    const err = new Error("Command timed out");
    err.killed = true;
    return Promise.reject(err);
  }

  function mockGbifExecConnRefused() {
    return Promise.reject(new Error("ssh: Connection refused"));
  }

  await test("gbifQuery returns parsed envelope on happy path", async () => {
    const result = await gbifQuery(
      { args: { species_name: "Caligus elongatus", limit: 100 } },
      mockConfig,
      mockGbifExecOk
    );
    assert.strictEqual(result.error, null);
    assert.strictEqual(result.data.length, 2);
    assert.strictEqual(result.data[0][2], "Caligus elongatus");
  });

  await test("gbifQuery surfaces invalid_spec error from validation", async () => {
    const result = await gbifQuery(
      { args: { species_name: "bad; rm" } },
      mockConfig,
      mockGbifExecOk
    );
    assert.deepStrictEqual(result.data, []);
    assert.strictEqual(result.error.code, "invalid_spec");
  });

  await test("gbifQuery surfaces runtime_error on malformed R output", async () => {
    const result = await gbifQuery(
      { args: { species_name: "Caligus elongatus" } },
      mockConfig,
      mockGbifExecMalformed
    );
    assert.deepStrictEqual(result.data, []);
    assert.strictEqual(result.error.code, "runtime_error");
  });

  await test("gbifQuery returns runtime_error on SSH timeout", async () => {
    const result = await gbifQuery(
      { args: { limit: 10 } },
      mockConfig,
      mockGbifExecTimeoutKilled
    );
    assert.strictEqual(result.error.code, "runtime_error");
    assert.ok(result.error.message.toLowerCase().includes("timed out"));
  });

  await test("gbifQuery returns cluster_unreachable on SSH failure", async () => {
    const result = await gbifQuery(
      { args: { limit: 10 } },
      mockConfig,
      mockGbifExecConnRefused
    );
    assert.strictEqual(result.error.code, "cluster_unreachable");
  });

  // ── gbif.query: dispatch wiring ──────────────────────────────────────
  await test("dispatch gbif.query returns 200 with parsed data", async () => {
    const out = await dispatch(
      "gbif.query",
      { args: { species_name: "Caligus elongatus", limit: 10 } },
      mockConfig,
      mockGbifExecOk
    );
    assert.strictEqual(out.status, 200);
    assert.strictEqual(out.result.error, null);
    assert.strictEqual(out.result.data.length, 2);
  });

  await test("gbif.query is in READ_CAPABILITIES set", async () => {
    assert.ok(READ_CAPABILITIES.has("gbif.query"));
  });
}

// ── Integration test: HTTP server ──────────────────────────────────────

async function httpTests() {
  console.log("\n== http integration ==");

  // Spin up a test server using the request handler directly
  // We simulate the server logic without requiring real env vars.
  const crypto = require("crypto");
  const { sanitize: san } = require("../connector/reumanlab/sanitize");
  const aud = require("../connector/reumanlab/audit");
  const { dispatch: disp } = require("../connector/reumanlab/capabilities");

  const TEST_TOKEN = "test-secret-token-12345";
  const tokenHash = crypto.createHash("sha256").update(TEST_TOKEN).digest("hex");
  const testConfig = { ...mockConfig };

  function verifyBearer(authHeader) {
    if (!authHeader || !authHeader.startsWith("Bearer ")) return false;
    const provided = authHeader.slice(7);
    const providedHash = crypto.createHash("sha256").update(provided).digest("hex");
    const a = Buffer.from(tokenHash, "hex");
    const b = Buffer.from(providedHash, "hex");
    try { return crypto.timingSafeEqual(a, b); } catch { return false; }
  }

  const testServer = http.createServer(async (req, res) => {
    if (req.url === "/healthz" && req.method === "GET") {
      const body = JSON.stringify({ status: "ok", connector_id: "reumanlab" });
      res.writeHead(200, { "Content-Type": "application/json" });
      return res.end(body);
    }

    if (req.method !== "POST" || req.url !== "/v1/capabilities") {
      const body = JSON.stringify({ error: "not found" });
      res.writeHead(404, { "Content-Type": "application/json" });
      return res.end(body);
    }

    if (!verifyBearer(req.headers["authorization"])) {
      const body = JSON.stringify({ error: "unauthorized" });
      res.writeHead(401, { "Content-Type": "application/json" });
      return res.end(body);
    }

    const chunks = [];
    for await (const chunk of req) chunks.push(chunk);
    const parsed = JSON.parse(Buffer.concat(chunks).toString());
    const startMs = Date.now();

    try {
      const outcome = await disp(parsed.capability, parsed.payload || {}, testConfig, mockExec);
      if (outcome.error) {
        const body = JSON.stringify(outcome.error);
        res.writeHead(outcome.status, { "Content-Type": "application/json" });
        return res.end(body);
      }
      if (outcome.result && outcome.result.error === true) {
        const httpStatus = outcome.result.code === "path_traversal" ? 400 : 403;
        const body = JSON.stringify({ error: outcome.result.message, code: outcome.result.code, capability: parsed.capability });
        res.writeHead(httpStatus, { "Content-Type": "application/json" });
        return res.end(body);
      }
      const body = JSON.stringify(outcome.result);
      res.writeHead(outcome.status, { "Content-Type": "application/json" });
      return res.end(body);
    } catch (err) {
      const body = JSON.stringify({ error: san(err.message), code: "connector_error", capability: parsed.capability });
      res.writeHead(500, { "Content-Type": "application/json" });
      return res.end(body);
    }
  });

  // Start on random port
  await new Promise((resolve) => testServer.listen(0, "127.0.0.1", resolve));
  const { port } = testServer.address();

  function request(method, path, body, headers) {
    return new Promise((resolve, reject) => {
      const opts = { hostname: "127.0.0.1", port, method, path, headers: headers || {} };
      if (body) opts.headers["Content-Type"] = "application/json";
      const req = http.request(opts, (res) => {
        const chunks = [];
        res.on("data", (c) => chunks.push(c));
        res.on("end", () => {
          const text = Buffer.concat(chunks).toString();
          let json;
          try { json = JSON.parse(text); } catch { json = null; }
          resolve({ status: res.statusCode, body: json, text });
        });
      });
      req.on("error", reject);
      if (body) req.write(JSON.stringify(body));
      req.end();
    });
  }

  const authHeaders = { Authorization: `Bearer ${TEST_TOKEN}` };

  try {
    await test("GET /healthz returns 200 without auth", async () => {
      const res = await request("GET", "/healthz");
      assert.strictEqual(res.status, 200);
      assert.strictEqual(res.body.status, "ok");
    });

    await test("POST /v1/capabilities without auth returns 401", async () => {
      const res = await request("POST", "/v1/capabilities", { capability: "remote.health" });
      assert.strictEqual(res.status, 401);
    });

    await test("POST /v1/capabilities with wrong token returns 401", async () => {
      const res = await request("POST", "/v1/capabilities", { capability: "remote.health" }, {
        Authorization: "Bearer wrong-token",
      });
      assert.strictEqual(res.status, 401);
    });

    await test("POST /v1/capabilities remote.health returns 200", async () => {
      const res = await request("POST", "/v1/capabilities", { capability: "remote.health" }, authHeaders);
      assert.strictEqual(res.status, 200);
      assert.strictEqual(res.body.status, "ok");
      assert.strictEqual(res.body.connector_id, "reumanlab");
    });

    await test("POST /v1/capabilities hpc.submit returns 501", async () => {
      const res = await request("POST", "/v1/capabilities", { capability: "hpc.submit" }, authHeaders);
      assert.strictEqual(res.status, 501);
      assert.strictEqual(res.body.code, "capability_disabled");
    });

    await test("POST /v1/capabilities remote.list_home with bad path returns 403", async () => {
      const res = await request("POST", "/v1/capabilities", {
        capability: "remote.list_home",
        payload: { path: "/etc/passwd" },
      }, authHeaders);
      assert.strictEqual(res.status, 403);
      assert.strictEqual(res.body.code, "path_not_allowed");
    });

    await test("GET /nonexistent returns 404", async () => {
      const res = await request("GET", "/nonexistent");
      assert.strictEqual(res.status, 404);
    });
  } finally {
    testServer.close();
  }
}

// ── Audit tests ────────────────────────────────────────────────────────

async function auditTests() {
  console.log("\n== audit ==");

  await test("audit.emit produces required fields", async () => {
    // Capture stdout
    const origWrite = process.stdout.write;
    let captured = "";
    process.stdout.write = (s) => { captured += s; };

    const aud = require("../connector/reumanlab/audit");
    const event = aud.emit({
      connectorId: "reumanlab",
      capability: "hpc.queue",
      userId: "octocat",
      taskId: "task_abc",
      resultStatus: "ok",
      durationMs: 42,
    });

    process.stdout.write = origWrite;

    assert.strictEqual(event.event, "capability_invoked");
    assert.strictEqual(event.connector_id, "reumanlab");
    assert.strictEqual(event.capability, "hpc.queue");
    assert.strictEqual(event.user_id, "octocat");
    assert.strictEqual(event.task_id, "task_abc");
    assert.strictEqual(event.result_status, "ok");
    assert.strictEqual(event.duration_ms, 42);
    assert.ok(event.timestamp);

    const parsed = JSON.parse(captured.trim());
    assert.strictEqual(parsed.event, "capability_invoked");
  });

  await test("audit.emit includes error fields on error", async () => {
    const origWrite = process.stdout.write;
    let captured = "";
    process.stdout.write = (s) => { captured += s; };

    const aud = require("../connector/reumanlab/audit");
    const event = aud.emit({
      connectorId: "reumanlab",
      capability: "hpc.logs.read",
      userId: "octocat",
      taskId: "task_xyz",
      resultStatus: "error",
      errorCode: "path_not_allowed",
      errorMessage: "path not in allowlist",
      durationMs: 2,
    });

    process.stdout.write = origWrite;

    assert.strictEqual(event.result_status, "error");
    assert.strictEqual(event.error_code, "path_not_allowed");
    assert.strictEqual(event.error_message, "path not in allowlist");
  });
}

// ── Run all ────────────────────────────────────────────────────────────

async function main() {
  console.log("reumanlab-connector test suite\n");

  await configTests();
  await sanitizeTests();
  await capabilityTests();
  await timeoutTests();
  await auditTests();
  await httpTests();

  console.log(`\n== summary ==`);
  console.log(`  ${passed} passed, ${failed} failed`);

  if (failures.length > 0) {
    console.log("\nFailures:");
    for (const f of failures) {
      console.log(`  ${f.name}: ${f.error.message}`);
    }
    process.exit(1);
  }
}

main().catch((err) => {
  console.error("Test runner error:", err);
  process.exit(1);
});

"use strict";

// Capability dispatch handlers for the reumanlab connector.
// Implements read-only alpha capabilities per §2.1 of the connector contract.
// Write capabilities return 501 capability_disabled per §2.2 / §7.5.

const { execFile } = require("child_process");
const path = require("path");

const SHELL_META_RE = /[;|&$`><\n\0]/;
const POSIX_PATH_RE = /^\/[A-Za-z0-9/._-]+$/;

// Clamp a value between min and max.
function clamp(val, min, max) {
  const n = typeof val === "number" ? val : parseInt(val, 10);
  if (Number.isNaN(n)) return min;
  return Math.max(min, Math.min(max, n));
}

// Run a command with bounded output and timeout.
function execBounded(cmd, args, opts) {
  return new Promise((resolve, reject) => {
    const child = execFile(cmd, args, {
      timeout: opts.timeoutMs || 30000,
      maxBuffer: opts.maxOutputBytes || 1048576,
      env: opts.env || { PATH: "/usr/local/bin:/usr/bin:/bin" },
      encoding: "utf8",
    }, (err, stdout, stderr) => {
      if (err) {
        reject(err);
      } else {
        resolve(stdout);
      }
    });
  });
}

// Build SSH args for remote commands.
function sshArgs(config) {
  const args = [
    "-o", "BatchMode=yes",
    "-o", "ConnectTimeout=10",
    "-o", "StrictHostKeyChecking=yes",
  ];
  if (config.sshIdentityFile) {
    args.push("-i", config.sshIdentityFile);
  }
  args.push(`${config.hpcUser}@${config.hpcHost}`);
  return args;
}

function sshEnv() {
  const env = {
    PATH: process.env.PATH || "/usr/local/bin:/usr/bin:/bin",
    HOME: process.env.HOME || "/tmp",
    LANG: "C.UTF-8",
  };
  if (process.env.SSH_AUTH_SOCK) env.SSH_AUTH_SOCK = process.env.SSH_AUTH_SOCK;
  if (process.env.HPC_SSH_KEY) env.IDENTITY_FILE = process.env.HPC_SSH_KEY;
  return env;
}

// Validate a path against the allowlist. Returns null if rejected.
function validatePath(requestedPath, allowedPaths) {
  if (typeof requestedPath !== "string" || requestedPath.length === 0) return null;
  if (requestedPath.length > 4096) return null;
  if (requestedPath.includes("\0")) return null;
  if (SHELL_META_RE.test(requestedPath)) return null;
  if (!POSIX_PATH_RE.test(requestedPath)) return null;

  const segments = requestedPath.split("/");
  if (segments.some((seg) => seg === "..")) return null;

  const resolved = path.resolve(requestedPath);
  for (const base of allowedPaths) {
    const resolvedBase = path.resolve(base);
    if (resolved === resolvedBase || resolved.startsWith(resolvedBase + "/")) {
      return resolved;
    }
  }
  return null;
}

// ── Capability: remote.health ──────────────────────────────────────────
const startTime = Date.now();

function remoteHealth(config) {
  return {
    status: "ok",
    connector_id: config.connectorId,
    version: "0.3.0",
    uptime_seconds: Math.floor((Date.now() - startTime) / 1000),
  };
}

// ── Capability: remote.info ────────────────────────────────────────────
function remoteInfo(config) {
  return {
    os_type: process.platform,
    node_name: "[REDACTED]",
    hpc_user: "[REDACTED]",
    hpc_host: "[REDACTED]",
    node_version: process.version,
    connector_start_time: new Date(startTime).toISOString(),
  };
}

// ── Capability: remote.list_home ───────────────────────────────────────
async function remoteListHome(payload, config, execFn) {
  const requestedPath = payload.path;
  const maxEntries = clamp(payload.max_entries || 50, 1, 200);

  const safePath = validatePath(requestedPath, config.allowedPaths);
  if (!safePath) {
    return {
      error: true,
      code: requestedPath && requestedPath.split("/").some((s) => s === "..")
        ? "path_traversal"
        : "path_not_allowed",
      message: `path is not in the configured allowlist`,
    };
  }

  const run = execFn || execBounded;
  // ls -1a with bounded output; we parse entries ourselves
  const stdout = await run(
    "ssh",
    [...sshArgs(config), `ls -1a ${safePath} | head -n ${maxEntries + 1}`],
    { timeoutMs: config.commandTimeoutMs, maxOutputBytes: config.maxOutputBytes, env: sshEnv() }
  );

  const allEntries = stdout
    .split("\n")
    .map((l) => l.trim())
    .filter((l) => l && l !== "." && l !== "..");

  const truncated = allEntries.length > maxEntries;
  const entries = allEntries.slice(0, maxEntries).map((name) => ({
    name,
    type: name.endsWith("/") ? "directory" : "file",
  }));

  return {
    path: safePath,
    entries,
    truncated,
  };
}

// ── Capability: hpc.status ─────────────────────────────────────────────
async function hpcStatus(config, execFn) {
  const run = execFn || execBounded;
  const stdout = await run(
    "ssh",
    [...sshArgs(config), "sinfo --summarize --noheader 2>&1 || echo __UNREACHABLE__"],
    { timeoutMs: config.commandTimeoutMs, maxOutputBytes: config.maxOutputBytes, env: sshEnv() }
  );

  if (stdout.includes("__UNREACHABLE__") || stdout.includes("error")) {
    return {
      scheduler: "slurm",
      cluster_name: "kuhpc",
      scheduler_reachable: false,
      nodes_available: 0,
      queued_jobs: 0,
    };
  }

  // Parse sinfo summarize output for node counts
  const lines = stdout.trim().split("\n").filter(Boolean);
  let nodesAvailable = 0;
  for (const line of lines) {
    const parts = line.trim().split(/\s+/);
    // sinfo --summarize: PARTITION AVAIL TIMELIMIT NODES(A/I/O/T) NODELIST
    const nodeField = parts.find((p) => p.includes("/"));
    if (nodeField) {
      const [, idle] = nodeField.split("/");
      nodesAvailable += parseInt(idle, 10) || 0;
    }
  }

  return {
    scheduler: "slurm",
    cluster_name: "kuhpc",
    scheduler_reachable: true,
    nodes_available: nodesAvailable,
    queued_jobs: 0, // filled by separate squeue count
  };
}

// ── Capability: hpc.queue ──────────────────────────────────────────────
async function hpcQueue(payload, config, execFn) {
  const maxLines = clamp(payload.max_lines || 50, 1, 200);

  const run = execFn || execBounded;
  const stdout = await run(
    "ssh",
    [...sshArgs(config), `squeue -u ${config.hpcUser} | head -n ${maxLines + 1}`],
    { timeoutMs: config.commandTimeoutMs, maxOutputBytes: config.maxOutputBytes, env: sshEnv() }
  );

  const allLines = stdout.split("\n").filter((l) => l.trim());
  const truncated = allLines.length > maxLines;
  const lines = allLines.slice(0, maxLines);

  return {
    command: "squeue",
    lines,
    truncated,
  };
}

// ── Capability: gbif.query ─────────────────────────────────────────────
// Bridge to the local GBIF Parquet mirror on KU-HPC.
// Invokes ~/work/scripts/gbif_query.R inside the gbif-kde.sif Apptainer
// image over SSH and streams a one-line JSON envelope back.
//
// Contract (alrobles/ecoseek#71):
//   payload.args = {
//     species_name?: string,
//     taxon_key?:    integer,
//     bbox?:         [min_lon, min_lat, max_lon, max_lat],
//     year_range?:   [start_year, end_year],
//     limit?:        integer (1..100000)
//   }
//   returns: { data: [[lat,lon,species,taxonKey,year,month,basisOfRecord], ...],
//              error: null | { code, message } }

const GBIF_SPECIES_RE = /^[A-Za-z][A-Za-z .\-']{0,127}$/;
const GBIF_MAX_LIMIT = 100000;
const GBIF_DEFAULT_LIMIT = 50000;

function validateGbifArgs(args) {
  if (!args || typeof args !== "object") {
    return { ok: false, code: "invalid_spec", message: "args must be an object" };
  }
  if (args.species_name !== undefined && args.species_name !== null) {
    if (typeof args.species_name !== "string" ||
        args.species_name.length > 128 ||
        !GBIF_SPECIES_RE.test(args.species_name)) {
      return {
        ok: false,
        code: "invalid_spec",
        message: "species_name fails allowlist or length check",
      };
    }
  }
  if (args.taxon_key !== undefined && args.taxon_key !== null) {
    if (typeof args.taxon_key !== "number" ||
        !Number.isFinite(args.taxon_key) ||
        args.taxon_key < 0 || args.taxon_key > 1e12) {
      return {
        ok: false,
        code: "invalid_spec",
        message: "taxon_key out of range",
      };
    }
  }
  if (args.year_range !== undefined && args.year_range !== null) {
    const yr = args.year_range;
    if (!Array.isArray(yr) || yr.length !== 2 ||
        yr[0] > yr[1] || yr[0] < 1700 || yr[1] > 2100) {
      return {
        ok: false,
        code: "invalid_spec",
        message: "year_range must be [low, high] within [1700, 2100]",
      };
    }
  }
  if (args.bbox !== undefined && args.bbox !== null) {
    const bb = args.bbox;
    if (!Array.isArray(bb) || bb.length !== 4 ||
        bb[0] >= bb[2] || bb[1] >= bb[3]) {
      return {
        ok: false,
        code: "invalid_spec",
        message: "bbox must be [min_lon, min_lat, max_lon, max_lat]",
      };
    }
  }
  let limit = args.limit;
  if (limit === undefined || limit === null) {
    limit = GBIF_DEFAULT_LIMIT;
  }
  if (typeof limit !== "number" || !Number.isInteger(limit) ||
      limit < 1 || limit > GBIF_MAX_LIMIT) {
    return {
      ok: false,
      code: "row_cap_exceeded",
      message: `limit must be in [1, ${GBIF_MAX_LIMIT}]`,
    };
  }

  // Build the spec object that will be JSON-encoded for the R script.
  const spec = { limit };
  if (args.species_name) spec.species_name = args.species_name;
  if (args.taxon_key !== undefined && args.taxon_key !== null) {
    spec.taxon_key = args.taxon_key;
  }
  if (Array.isArray(args.year_range)) spec.year_range = args.year_range;
  if (Array.isArray(args.bbox)) spec.bbox = args.bbox;
  return { ok: true, spec };
}

async function gbifQuery(payload, config, execFn) {
  const args = (payload && payload.args) || {};
  const v = validateGbifArgs(args);
  if (!v.ok) {
    return { data: [], error: { code: v.code, message: v.message } };
  }

  const run = execFn || execBounded;

  // Build the remote command: pipe JSON spec via stdin into a wrapper that
  // launches Apptainer and Rscript on the cluster. Using `bash -lc` keeps the
  // login profile (PATH for apptainer, R) and avoids quoting issues — the
  // payload itself is base64-encoded so shell meta in JSON can't break out.
  const specJson = JSON.stringify(v.spec);
  const specB64 = Buffer.from(specJson, "utf8").toString("base64");

  const remoteCmd =
    "bash -lc " +
    JSON.stringify(
      `set -euo pipefail; \
GBIFDB_DIR='${config.gbifdbDir}' \
APPTAINER_IMAGE='${config.apptainerImage}' \
GBIF_QUERY_R='${config.gbifQueryR}' \
echo '${specB64}' | base64 -d | '${config.gbifRunner}'`
    );

  let stdout;
  try {
    stdout = await run(
      "ssh",
      [...sshArgs(config), remoteCmd],
      {
        timeoutMs: config.gbifTimeoutMs || 600000,
        maxOutputBytes: config.gbifMaxOutputBytes || 16 * 1024 * 1024,
        env: sshEnv(),
      }
    );
  } catch (err) {
    // Distinguish kill-by-timeout from connection failure where possible
    if (err && err.killed) {
      return {
        data: [],
        error: {
          code: "runtime_error",
          message: "cluster query timed out",
        },
      };
    }
    return {
      data: [],
      error: {
        code: "cluster_unreachable",
        message: "ssh to cluster failed",
      },
    };
  }

  // The R script emits the envelope as one JSON object (followed by \n).
  // Be defensive: take the last non-empty line.
  const lines = stdout.split("\n").map((l) => l.trim()).filter(Boolean);
  const payloadLine = lines.length > 0 ? lines[lines.length - 1] : "";
  let parsed;
  try {
    parsed = JSON.parse(payloadLine);
  } catch (err) {
    return {
      data: [],
      error: {
        code: "runtime_error",
        message: "could not parse R script output",
      },
    };
  }
  if (!parsed || typeof parsed !== "object") {
    return {
      data: [],
      error: {
        code: "runtime_error",
        message: "R script returned non-object envelope",
      },
    };
  }
  if (!("data" in parsed)) {
    return {
      data: [],
      error: {
        code: "runtime_error",
        message: "envelope missing data field",
      },
    };
  }
  return { data: parsed.data || [], error: parsed.error || null };
}

// ── Capability: hpc.logs.read ──────────────────────────────────────────
async function hpcLogsRead(payload, config, execFn) {
  const requestedPath = payload.path;
  const lineCount = clamp(payload.lines || 100, 1, 500);

  const safePath = validatePath(requestedPath, config.allowedPaths);
  if (!safePath) {
    return {
      error: true,
      code: requestedPath && requestedPath.split("/").some((s) => s === "..")
        ? "path_traversal"
        : "path_not_allowed",
      message: `path is not in the configured allowlist`,
    };
  }

  const run = execFn || execBounded;
  const stdout = await run(
    "ssh",
    [...sshArgs(config), `tail -n ${lineCount + 1} ${safePath}`],
    { timeoutMs: config.commandTimeoutMs, maxOutputBytes: config.maxOutputBytes, env: sshEnv() }
  );

  const allLines = stdout.split("\n");
  // Remove trailing empty line from tail output
  if (allLines.length > 0 && allLines[allLines.length - 1] === "") {
    allLines.pop();
  }
  const truncated = allLines.length > lineCount;
  const lines = allLines.slice(0, lineCount);

  return {
    path: safePath,
    lines,
    truncated,
  };
}

// ── Allowlisted capability map ─────────────────────────────────────────
const READ_CAPABILITIES = new Set([
  "remote.health",
  "remote.info",
  "remote.list_home",
  "hpc.status",
  "hpc.queue",
  "hpc.logs.read",
  "gbif.query",
]);

const WRITE_CAPABILITIES = new Set([
  "hpc.submit",
  "hpc.cancel",
  "hpc.write",
  "hpc.delete",
]);

// Main dispatch. Returns { status, result } or { status, error }.
async function dispatch(capability, payload, config, execFn) {
  if (WRITE_CAPABILITIES.has(capability)) {
    return {
      status: 501,
      error: {
        error: `capability '${capability}' is not enabled in Phase 3`,
        code: "capability_disabled",
        capability,
      },
    };
  }

  if (!READ_CAPABILITIES.has(capability)) {
    return {
      status: 400,
      error: {
        error: `unknown capability '${capability}'`,
        code: "invalid_payload",
        capability: capability || "",
      },
    };
  }

  switch (capability) {
    case "remote.health":
      return { status: 200, result: remoteHealth(config) };

    case "remote.info":
      return { status: 200, result: remoteInfo(config) };

    case "remote.list_home":
      if (!payload || !payload.path) {
        return {
          status: 400,
          error: {
            error: "payload.path is required",
            code: "invalid_payload",
            capability,
          },
        };
      }
      return { status: 200, result: await remoteListHome(payload, config, execFn) };

    case "hpc.status":
      return { status: 200, result: await hpcStatus(config, execFn) };

    case "hpc.queue":
      return { status: 200, result: await hpcQueue(payload || {}, config, execFn) };

    case "hpc.logs.read":
      if (!payload || !payload.path) {
        return {
          status: 400,
          error: {
            error: "payload.path is required",
            code: "invalid_payload",
            capability,
          },
        };
      }
      return { status: 200, result: await hpcLogsRead(payload, config, execFn) };

    case "gbif.query":
      return { status: 200, result: await gbifQuery(payload || {}, config, execFn) };

    default:
      return {
        status: 400,
        error: {
          error: `unknown capability '${capability}'`,
          code: "invalid_payload",
          capability,
        },
      };
  }
}

module.exports = {
  dispatch,
  validatePath,
  clamp,
  remoteHealth,
  remoteInfo,
  remoteListHome,
  hpcStatus,
  hpcQueue,
  hpcLogsRead,
  gbifQuery,
  validateGbifArgs,
  READ_CAPABILITIES,
  WRITE_CAPABILITIES,
  SHELL_META_RE,
  GBIF_SPECIES_RE,
  GBIF_MAX_LIMIT,
  GBIF_DEFAULT_LIMIT,
};

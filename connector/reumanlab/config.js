"use strict";

// Fail-closed configuration loader.
// If any required env var is missing the process exits immediately.
// This satisfies §6.5 of the connector contract.

const REQUIRED_VARS = [
  "HPC_USER",
  "HPC_HOST",
  "CONNECTOR_TOKEN",
];

function load(env) {
  const missing = REQUIRED_VARS.filter((k) => !env[k]);
  if (missing.length > 0) {
    const msg = {
      error: "fail-closed: required configuration missing",
      missing,
      timestamp: new Date().toISOString(),
    };
    process.stderr.write(JSON.stringify(msg) + "\n");
    process.exit(1);
  }

  const allowedPaths = (env.HPC_ALLOWED_LOG_PATHS || "")
    .split(",")
    .map((p) => p.trim())
    .filter(Boolean);

  return {
    hpcUser: env.HPC_USER,
    hpcHost: env.HPC_HOST,
    connectorToken: env.CONNECTOR_TOKEN,
    connectorId: env.CONNECTOR_ID || "reumanlab",
    port: parseInt(env.CONNECTOR_PORT || "8000", 10),
    host: env.CONNECTOR_HOST || "127.0.0.1",
    allowedPaths,
    commandTimeoutMs: parseInt(env.COMMAND_TIMEOUT_MS || "30000", 10),
    maxOutputBytes: parseInt(env.MAX_OUTPUT_BYTES || "1048576", 10),
    // gbif.query capability — see capabilities.js
    gbifdbDir: env.GBIFDB_DIR ||
      "/home/a474r867/work/gbifdata/gbif_effort/gbifdata",
    apptainerImage: env.GBIF_APPTAINER_IMAGE ||
      "/home/a474r867/work/gbifdata/gbif_effort/container/gbif-kde.sif",
    gbifQueryR: env.GBIF_QUERY_R ||
      "/home/a474r867/work/scripts/gbif_query.R",
    gbifRunner: env.GBIF_RUNNER ||
      "/home/a474r867/work/scripts/run_gbif_query.sh",
    gbifTimeoutMs: parseInt(env.GBIF_TIMEOUT_MS || "600000", 10),
    gbifMaxOutputBytes: parseInt(env.GBIF_MAX_OUTPUT_BYTES || "16777216", 10),
  };
}

// Testable variant that validates but does not exit.
function validate(env) {
  const missing = REQUIRED_VARS.filter((k) => !env[k]);
  if (missing.length > 0) {
    return { ok: false, missing };
  }
  const allowedPaths = (env.HPC_ALLOWED_LOG_PATHS || "")
    .split(",")
    .map((p) => p.trim())
    .filter(Boolean);

  return {
    ok: true,
    config: {
      hpcUser: env.HPC_USER,
      hpcHost: env.HPC_HOST,
      connectorToken: env.CONNECTOR_TOKEN,
      connectorId: env.CONNECTOR_ID || "reumanlab",
      port: parseInt(env.CONNECTOR_PORT || "8000", 10),
      host: env.CONNECTOR_HOST || "127.0.0.1",
      allowedPaths,
      commandTimeoutMs: parseInt(env.COMMAND_TIMEOUT_MS || "30000", 10),
      maxOutputBytes: parseInt(env.MAX_OUTPUT_BYTES || "1048576", 10),
      gbifdbDir: env.GBIFDB_DIR ||
        "/home/a474r867/work/gbifdata/gbif_effort/gbifdata",
      apptainerImage: env.GBIF_APPTAINER_IMAGE ||
        "/home/a474r867/work/gbifdata/gbif_effort/container/gbif-kde.sif",
      gbifQueryR: env.GBIF_QUERY_R ||
        "/home/a474r867/work/scripts/gbif_query.R",
      gbifRunner: env.GBIF_RUNNER ||
        "/home/a474r867/work/scripts/run_gbif_query.sh",
      gbifTimeoutMs: parseInt(env.GBIF_TIMEOUT_MS || "600000", 10),
      gbifMaxOutputBytes: parseInt(env.GBIF_MAX_OUTPUT_BYTES || "16777216", 10),
    },
  };
}

module.exports = { load, validate, REQUIRED_VARS };

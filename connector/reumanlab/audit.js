"use strict";

// Structured audit logging per connector contract §5.

function emit(fields) {
  const event = {
    event: "capability_invoked",
    timestamp: new Date().toISOString(),
    connector_id: fields.connectorId || "reumanlab",
    capability: fields.capability,
    user_id: fields.userId || "unknown",
    task_id: fields.taskId || "unknown",
    result_status: fields.resultStatus, // "ok" | "error"
    duration_ms: fields.durationMs,
  };

  if (fields.resultStatus === "error") {
    if (fields.errorCode) event.error_code = fields.errorCode;
    if (fields.errorMessage) event.error_message = fields.errorMessage;
  }

  process.stdout.write(JSON.stringify(event) + "\n");
  return event;
}

module.exports = { emit };

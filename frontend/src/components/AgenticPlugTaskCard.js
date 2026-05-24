import React from "react";
import "./AgenticPlugTaskView.css";

const STATE_ICONS = {
  task_created: "○",
  task_running: "◌",
  approval_required: "⚠",
  approval_denied: "✕",
  approval_granted: "✓",
  job_submitted: "↑",
  job_queued: "⏳",
  job_running: "▶",
  job_completed: "✔",
  job_failed: "✗",
  artifact_available: "📦",
  github_handoff: "🐙",
};

export const AgenticPlugTaskCard = ({ task, isSelected, onSelect, stateLabel }) => {
  const icon = STATE_ICONS[task.state] || "?";
  const isActive = [
    "task_created",
    "task_running",
    "approval_required",
    "job_submitted",
    "job_queued",
    "job_running",
  ].includes(task.state);

  return (
    <div
      className={`ap-task-card ${isSelected ? "ap-selected" : ""} ${
        task.state === "approval_required" ? "ap-needs-approval" : ""
      } ${task.state === "job_failed" ? "ap-failed" : ""} ${
        task.state === "approval_denied" ? "ap-denied" : ""
      }`}
      onClick={onSelect}
    >
      <div className="ap-task-card-header">
        <span className={`ap-state-icon ${isActive ? "ap-active" : ""}`}>
          {icon}
        </span>
        <span className="ap-task-title">{task.title || task.task_id}</span>
      </div>
      <div className="ap-task-card-body">
        <span className={`ap-state-badge ap-badge-${task.state}`}>
          {stateLabel}
        </span>
        {task.exit_code != null && (
          <span
            className={`ap-exit-badge ${
              task.exit_code === 0 ? "ap-exit-ok" : "ap-exit-err"
            }`}
          >
            exit {task.exit_code}
          </span>
        )}
      </div>
      <div className="ap-task-card-footer">
        <span className="ap-task-id">ID: {task.task_id.slice(0, 8)}</span>
        {task.created_at && (
          <span className="ap-task-time">
            {new Date(task.created_at).toLocaleTimeString()}
          </span>
        )}
      </div>
    </div>
  );
};

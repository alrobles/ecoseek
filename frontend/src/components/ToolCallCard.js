import React from "react";

const TOOL_META = {
  hermes_status: {
    label: "Checking Hermes Beta",
    icon: "🔍",
    color: "#6366f1",
  },
  escalate_remote: {
    label: "Delegating to Hermes Beta",
    icon: "🚀",
    color: "#10b981",
  },
  dialectical_exchange: {
    label: "DiDAL Exchange",
    icon: "⚡",
    color: "#f59e0b",
  },
  eco_analyze: {
    label: "Ecological Analysis",
    icon: "🌿",
    color: "#22c55e",
  },
  ku_hpc: {
    label: "HPC Job",
    icon: "🖥️",
    color: "#8b5cf6",
  },
};

function parseToolArgs(argsStr) {
  try {
    return JSON.parse(argsStr);
  } catch {
    return null;
  }
}

export function ToolCallCard({ toolCall, status = "running" }) {
  const meta = TOOL_META[toolCall.name] || {
    label: toolCall.name,
    icon: "🔧",
    color: "#94a3b8",
  };

  const args = parseToolArgs(toolCall.arguments);

  return (
    <div className="tool-call-card" style={{ "--tool-color": meta.color }}>
      <div className="tool-call-header">
        <span className="tool-call-icon">{meta.icon}</span>
        <span className="tool-call-label">{meta.label}</span>
        <span className={`tool-call-status ${status}`}>
          {status === "running" && (
            <span className="tool-spinner" />
          )}
          {status === "running" ? "Running..." : status === "done" ? "Done" : "Error"}
        </span>
      </div>
      {args && (
        <div className="tool-call-args">
          {args.task && (
            <div className="tool-arg">
              <span className="tool-arg-key">Task:</span>
              <span className="tool-arg-value">{args.task.substring(0, 200)}{args.task.length > 200 ? "..." : ""}</span>
            </div>
          )}
          {args.plan && (
            <div className="tool-arg">
              <span className="tool-arg-key">Plan:</span>
              <span className="tool-arg-value">{args.plan.substring(0, 150)}{args.plan.length > 150 ? "..." : ""}</span>
            </div>
          )}
          {args.urgency && args.urgency !== "normal" && (
            <div className="tool-arg">
              <span className="tool-arg-key">Urgency:</span>
              <span className={`tool-arg-value urgency-${args.urgency}`}>{args.urgency}</span>
            </div>
          )}
          {args.species && (
            <div className="tool-arg">
              <span className="tool-arg-key">Species:</span>
              <span className="tool-arg-value">{args.species}</span>
            </div>
          )}
          {args.action && (
            <div className="tool-arg">
              <span className="tool-arg-key">Action:</span>
              <span className="tool-arg-value">{args.action}</span>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

export function ToolCallsContainer({ toolCalls, status = "running" }) {
  if (!toolCalls || toolCalls.length === 0) return null;

  return (
    <div className="tool-calls-container">
      {toolCalls.map((tc, i) => (
        <ToolCallCard key={tc.id || i} toolCall={tc} status={status} />
      ))}
    </div>
  );
}

import React, { useMemo } from "react";
import katex from "katex";
import "katex/dist/katex.min.css";

function extractBlocks(messages) {
  const blocks = [];
  for (const msg of messages) {
    if (msg.type !== "agent" || !msg.content) continue;
    const content = msg.content;

    const mathDisplay = /\$\$([\s\S]*?)\$\$/g;
    let m;
    while ((m = mathDisplay.exec(content)) !== null) {
      blocks.push({ type: "math", value: m[1].trim(), display: true });
    }

    const codeBlocks = /```(\w*)\n([\s\S]*?)```/g;
    while ((m = codeBlocks.exec(content)) !== null) {
      blocks.push({ type: "code", language: m[1] || "text", value: m[2].trim() });
    }
  }
  return blocks;
}

function MathPreview({ value }) {
  const html = useMemo(() => {
    try {
      return katex.renderToString(value, {
        displayMode: true,
        throwOnError: false,
        trust: true,
        strict: false,
      });
    } catch {
      return null;
    }
  }, [value]);

  if (!html) return <pre className="preview-fallback">{value}</pre>;
  return <div className="preview-math" dangerouslySetInnerHTML={{ __html: html }} />;
}

export function RenderPreview({ messages }) {
  const blocks = useMemo(() => extractBlocks(messages), [messages]);
  const latestBlocks = blocks.slice(-10).reverse();

  return (
    <div className="render-preview">
      <div className="preview-content">
        <div className="preview-blocks">
          {latestBlocks.length === 0 ? (
            <div className="preview-empty">
              <p>Equations, code, and results from Emily's responses will appear here for easy reference.</p>
            </div>
          ) : (
            latestBlocks.map((block, i) => (
              <div key={i} className={`preview-block preview-${block.type}`}>
                {block.type === "math" && <MathPreview value={block.value} />}
                {block.type === "code" && (
                  <div className="preview-code">
                    <div className="preview-code-header">{block.language}</div>
                    <pre><code>{block.value}</code></pre>
                  </div>
                )}
              </div>
            ))
          )}
        </div>
      </div>
    </div>
  );
}

const TOOL_LABELS = {
  hermes_status: "Status Check",
  escalate_remote: "Remote Delegation",
  dialectical_exchange: "DiDAL Exchange",
  eco_analyze: "Ecological Analysis",
  ku_hpc: "HPC Job",
};

export function DiDALPanel({ remoteStatus, isOnline, messages, didalExchanges = [], activeToolCalls = [] }) {
  const didalMessages = messages.filter(
    (m) => m.didalPhase || (m.toolCalls && m.toolCalls.length > 0) || (m.content && m.content.includes("Hermes Beta"))
  );

  const runningExchanges = didalExchanges.filter((ex) => ex.status === "running");
  const completedExchanges = didalExchanges.filter((ex) => ex.status !== "running");

  return (
    <div className="didal-panel">
      <div className="didal-status-grid">
        <div className="didal-status-card">
          <div className="didal-status-label">Alpha (Emily)</div>
          <div className={`didal-status-value ${isOnline ? "active" : "inactive"}`}>
            {isOnline ? "Online" : "Offline"}
          </div>
        </div>
        <div className="didal-connection">
          <svg width="40" height="24" viewBox="0 0 40 24">
            <line x1="0" y1="12" x2="40" y2="12"
              stroke={remoteStatus ? "#10b981" : "var(--muted-foreground)"}
              strokeWidth="2" strokeDasharray={remoteStatus ? "none" : "4 4"} />
            <polygon
              points="34,7 40,12 34,17"
              fill={remoteStatus ? "#10b981" : "var(--muted-foreground)"} />
          </svg>
        </div>
        <div className="didal-status-card">
          <div className="didal-status-label">Beta (Hermes)</div>
          <div className={`didal-status-value ${remoteStatus ? "active" : "inactive"}`}>
            {remoteStatus ? "Online" : "Offline"}
          </div>
        </div>
      </div>

      <div className="didal-info">
        <h4>DiDAL Phase 4 — Streaming</h4>
        <p>
          {remoteStatus
            ? "Real-time streaming with tool call visualization. Emily delegates heavy tasks to Hermes Beta on reumanlab."
            : "Hermes Beta is not connected. Emily will work locally without remote validation."}
        </p>
      </div>

      {/* Live activity */}
      {(runningExchanges.length > 0 || activeToolCalls.length > 0) && (
        <div className="didal-live">
          <h4>
            <span className="didal-live-dot" />
            Live Activity
          </h4>
          {activeToolCalls.map((tc, i) => (
            <div key={tc.id || i} className="didal-live-entry">
              <span className="didal-live-icon">
                {tc.name === "escalate_remote" ? "🚀" : tc.name === "dialectical_exchange" ? "⚡" : "🔧"}
              </span>
              <span className="didal-live-text">
                {TOOL_LABELS[tc.name] || tc.name}
              </span>
              <span className="didal-live-spinner" />
            </div>
          ))}
        </div>
      )}

      {/* Recent exchanges */}
      {(completedExchanges.length > 0 || didalMessages.length > 0) && (
        <div className="didal-log">
          <h4>Recent Exchanges</h4>
          {completedExchanges.slice(-5).reverse().map((ex, i) => (
            <div key={i} className={`didal-log-entry didal-log-${ex.status}`}>
              <span className="didal-log-icon">
                {ex.status === "done" ? "✓" : ex.status === "error" ? "✗" : "…"}
              </span>
              <span className="didal-log-tool">{TOOL_LABELS[ex.tool] || ex.tool}</span>
              {ex.completedAt && (
                <span className="didal-log-time">
                  {new Date(ex.completedAt).toLocaleTimeString()}
                </span>
              )}
            </div>
          ))}
          {completedExchanges.length === 0 && didalMessages.slice(-5).map((m, i) => (
            <div key={i} className="didal-log-entry">
              <span className="didal-log-text">
                {m.content.substring(0, 100)}
                {m.content.length > 100 ? "..." : ""}
              </span>
            </div>
          ))}
        </div>
      )}

      {remoteStatus && (
        <div className="didal-tools">
          <h4>Available Remote Tools</h4>
          <div className="didal-tool-grid">
            {["eco_analyze", "ku_hpc", "escalate_remote", "dialectical_exchange"].map((tool) => (
              <div key={tool} className="didal-tool-chip">{tool}</div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

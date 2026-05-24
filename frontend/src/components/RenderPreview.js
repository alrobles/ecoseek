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

export function DiDALPanel({ remoteStatus, isOnline, messages }) {
  const didalMessages = messages.filter(
    (m) => m.didalPhase || (m.content && m.content.includes("Hermes Beta"))
  );

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
        <h4>DiDAL Phase 3</h4>
        <p>
          {remoteStatus
            ? "Emily can delegate heavy tasks to Hermes Beta on reumanlab. Beta validates complex outputs using eco_analyze and ku_hpc tools."
            : "Hermes Beta is not connected. Emily will work locally without remote validation."}
        </p>
      </div>

      {didalMessages.length > 0 && (
        <div className="didal-log">
          <h4>Recent Delegations</h4>
          {didalMessages.slice(-5).map((m, i) => (
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

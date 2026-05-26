import React, { useMemo, useRef, useCallback } from "react";
import ReactMarkdown from "react-markdown";
import { MathJax } from "better-react-mathjax";

function downloadPdf(contentEl) {
  if (!contentEl) return;
  const printWin = window.open("", "_blank", "width=800,height=600");
  if (!printWin) return;
  // Include MathJax for PDF rendering
  const mathjaxScript = '<script id="MathJax-script" async src="https://cdn.jsdelivr.net/npm/mathjax@3/es5/tex-chtml.js"></script>';
  printWin.document.write(`<!DOCTYPE html><html><head>
    <meta charset="utf-8"/>
    <title>EcoSeek Report</title>
    ${mathjaxScript}
    <style>
      body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; padding: 2rem; max-width: 800px; margin: 0 auto; color: #1e293b; line-height: 1.7; }
      h1 { font-size: 1.6rem; border-bottom: 2px solid #10b981; padding-bottom: 0.4rem; }
      h2 { font-size: 1.3rem; color: #334155; margin-top: 1.5rem; }
      h3 { font-size: 1.1rem; }
      pre { background: #f1f5f9; padding: 1rem; border-radius: 6px; overflow-x: auto; font-size: 0.85rem; }
      code { font-family: "Fira Code", "Cascadia Code", monospace; }
      table { border-collapse: collapse; width: 100%; margin: 1rem 0; }
      th, td { border: 1px solid #cbd5e1; padding: 0.5rem 0.75rem; text-align: left; }
      th { background: #f1f5f9; font-weight: 600; }
      blockquote { border-left: 3px solid #10b981; padding-left: 1rem; color: #64748b; }
      .output-code-lang { font-size: 0.7rem; color: #64748b; padding: 0.25rem 0.5rem; background: #e2e8f0; display: inline-block; border-radius: 3px 3px 0 0; }
      @media print { body { padding: 0; } }
    </style>
  </head><body>${contentEl.innerHTML}
    <scr${""}ipt>window.onload=function(){window.print();window.close();}</scr${""}ipt>
  </body></html>`);
  printWin.document.close();
}

export function RenderPreview({ messages, streamingContent = "", isLoading = false, didalStages = [] }) {
  const contentRef = useRef(null);

  const latestAgentContent = useMemo(() => {
    let raw = "";
    if (isLoading && streamingContent) {
      raw = streamingContent;
    } else {
      for (let i = messages.length - 1; i >= 0; i--) {
        if (messages[i].type === "agent" && messages[i].content) {
          raw = messages[i].content;
          break;
        }
      }
    }
    return raw;
  }, [messages, streamingContent, isLoading]);

  const handleDownloadPdf = useCallback(() => {
    downloadPdf(contentRef.current);
  }, []);

  return (
    <div className="render-preview">
      {latestAgentContent && !isLoading && (
        <div className="output-toolbar">
          <button className="output-download-btn" onClick={handleDownloadPdf} title="Download as PDF">
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" />
              <polyline points="7 10 12 15 17 10" />
              <line x1="12" y1="15" x2="12" y2="3" />
            </svg>
            PDF
          </button>
        </div>
      )}
      <div className="output-content" ref={contentRef}>
        {!latestAgentContent && !isLoading ? (
          <div className="preview-empty">
            <p>Emily's formatted output will appear here — markdown, equations, code, and results rendered for easy reading.</p>
          </div>
        ) : !latestAgentContent && isLoading && didalStages.length > 0 ? (
          <div className="output-didal-progress">
            <h4>DiDAL Protocol Running...</h4>
            <div className="output-stage-list">
              {didalStages.map((s, i) => (
                <div key={i} className={`output-stage-item ${s.status}`}>
                  <span className="output-stage-icon">{s.status === "active" ? "◉" : "✓"}</span>
                  <span className="output-stage-name">{s.name}</span>
                  {s.detail && <span className="output-stage-detail">{s.detail}</span>}
                </div>
              ))}
            </div>
          </div>
        ) : (
          <div className="output-markdown">
            <MathJax>
            <ReactMarkdown
              components={{
                code({ node, inline, className, children, ...props }) {
                  if (inline) {
                    return <code className="inline-code" {...props}>{children}</code>;
                  }
                  const lang = (className || "").replace("language-", "");
                  return (
                    <div className="output-code-block">
                      {lang && <div className="output-code-lang">{lang}</div>}
                      <pre><code className={className} {...props}>{children}</code></pre>
                    </div>
                  );
                },
                table({ children }) {
                  return <div className="output-table-wrap"><table>{children}</table></div>;
                },
              }}
            >
              {latestAgentContent}
            </ReactMarkdown>
            </MathJax>
          </div>
        )}
      </div>
    </div>
  );
}

const TOOL_LABELS = {
  hermes_status: "Status Check",
  escalate_remote: "Remote Delegation",
  dialectical_exchange: "DiDAL Exchange",
  didal_protocol: "DiDAL Protocol",
  classify_prompt: "Classify Prompt",
  eco_analyze: "Ecological Analysis",
  ku_hpc: "HPC Job",
  literature_search: "Literature Search",
  web_search: "Web Search",
  upload_document: "Upload PDF",
  ecoagent_query: "EcoAgent Query",
  execute_r_code: "Execute R Code",
  list_r_packages: "R Packages",
  r_workspace_status: "R Workspace",
  run_niche_model: "Niche Model",
  upload_artifact: "Upload Artifact",
  classify_literature: "LACS Classify",
  train_lacs_model: "LACS Train",
};

const MODE_CONFIG = {
  direct: { label: "Direct", color: "#6366f1", icon: "⚡", desc: "Fast single-call answer" },
  didal: { label: "DiDAL", color: "#f59e0b", icon: "🔬", desc: "Dialectical loop with structured debate" },
  didal_literature: { label: "DiDAL + Literature", color: "#ef4444", icon: "📚", desc: "Evidence-backed synthesis with retrieval" },
};

function ClassificationBadge({ classification }) {
  if (!classification) return null;
  const cfg = MODE_CONFIG[classification.mode] || MODE_CONFIG.direct;
  const score = classification.complexity_score ?? 0;
  const pct = Math.round(score * 100);
  return (
    <div className="didal-classification" style={{ "--mode-color": cfg.color }}>
      <div className="didal-class-header">
        <span className="didal-class-icon">{cfg.icon}</span>
        <span className="didal-class-mode">{cfg.label}</span>
        <span className="didal-class-score">{pct}%</span>
      </div>
      <div className="didal-class-bar">
        <div className="didal-class-fill" style={{ width: `${pct}%` }} />
        <div className="didal-class-threshold didal-thresh-25" />
        <div className="didal-class-threshold didal-thresh-60" />
      </div>
      <div className="didal-class-labels">
        <span>Direct</span>
        <span>DiDAL</span>
        <span>Literature</span>
      </div>
      {classification.reasons && classification.reasons.length > 0 && (
        <div className="didal-class-reasons">
          {classification.reasons.slice(0, 3).map((r, i) => (
            <span key={i} className="didal-reason-chip">{r.split(":")[0]}</span>
          ))}
        </div>
      )}
    </div>
  );
}

function ProtocolStages({ stages }) {
  if (!stages || stages.length === 0) return null;
  const stageNames = {
    classify: "Classify",
    frame_task: "Frame Task",
    retrieve_evidence: "Retrieve Evidence",
    expert_draft: "Expert Draft",
    naive_critique: "Naive Critique",
    revision: "Revision",
    direct_answer: "Direct Answer",
  };
  return (
    <div className="didal-stages">
      <h4>Protocol Stages</h4>
      <div className="didal-stage-flow">
        {stages.map((s, i) => (
          <div key={i} className={`didal-stage-chip ${s.error ? "stage-error" : "stage-ok"}`}>
            <span className="stage-num">{i + 1}</span>
            <span className="stage-name">{stageNames[s.stage] || s.stage}</span>
          </div>
        ))}
      </div>
    </div>
  );
}

export function DiDALPanel({
  remoteStatus, isOnline, messages, didalExchanges = [],
  activeToolCalls = [], lastClassification = null, lastProtocolStages = null,
  lastTraceId = null, lastJudgeResult = null,
}) {
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
        <h4>DiDAL Protocol v2 — Complexity-Aware Routing</h4>
        <p>
          {remoteStatus
            ? "Automatic classification routes questions to the right mode: Direct (fast), DiDAL (debate), or Literature (evidence-backed)."
            : "Hermes Beta is not connected. Emily will work locally without dialectical validation."}
        </p>
      </div>

      {/* Last classification result */}
      <ClassificationBadge classification={lastClassification} />

      {/* Protocol stages */}
      <ProtocolStages stages={lastProtocolStages} />

      {/* Phoenix trace ID */}
      {lastTraceId && (
        <div className="didal-trace-id">
          <span className="didal-trace-label">🔭 Phoenix Trace</span>
          <code className="didal-trace-code">{lastTraceId}</code>
        </div>
      )}

      {/* Judge score */}
      {lastJudgeResult && lastJudgeResult.overall_score > 0 && (
        <div className="didal-judge">
          <h4>Judge Score</h4>
          <div className="didal-judge-overall">
            <span className="didal-judge-score">{(lastJudgeResult.overall_score * 100).toFixed(0)}%</span>
            <span className={`didal-judge-verdict verdict-${lastJudgeResult.verdict || "unknown"}`}>
              {lastJudgeResult.verdict || "—"}
            </span>
          </div>
          {lastJudgeResult.scores && (
            <div className="didal-judge-breakdown">
              {Object.entries(lastJudgeResult.scores).map(([key, val]) => (
                <div key={key} className="didal-judge-criterion">
                  <span className="didal-judge-criterion-label">{key.replace(/_/g, " ")}</span>
                  <div className="didal-judge-bar">
                    <div className="didal-judge-bar-fill" style={{ width: `${(val || 0) * 100}%` }} />
                  </div>
                  <span className="didal-judge-criterion-val">{((val || 0) * 100).toFixed(0)}%</span>
                </div>
              ))}
            </div>
          )}
        </div>
      )}

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
                {tc.name === "didal_protocol" ? "🔬"
                  : tc.name === "escalate_remote" ? "🚀"
                  : tc.name === "dialectical_exchange" ? "⚡"
                  : "🔧"}
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
              {ex.mode && <span className="didal-log-mode">{ex.mode}</span>}
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
          <h4>Available Tools</h4>
          <div className="didal-tool-sections">
            <div className="didal-tool-section">
              <span className="didal-tool-section-label">Core</span>
              <div className="didal-tool-grid">
                {["didal_protocol", "classify_prompt", "escalate_remote", "dialectical_exchange"].map((tool) => (
                  <div key={tool} className="didal-tool-chip">{TOOL_LABELS[tool] || tool}</div>
                ))}
              </div>
            </div>
            <div className="didal-tool-section">
              <span className="didal-tool-section-label">Literature & Search</span>
              <div className="didal-tool-grid">
                {["literature_search", "web_search", "classify_literature", "train_lacs_model"].map((tool) => (
                  <div key={tool} className="didal-tool-chip tool-lacs">{TOOL_LABELS[tool] || tool}</div>
                ))}
              </div>
            </div>
            <div className="didal-tool-section">
              <span className="didal-tool-section-label">Documents & Data</span>
              <div className="didal-tool-grid">
                {["upload_document", "upload_artifact", "eco_analyze", "ecoagent_query"].map((tool) => (
                  <div key={tool} className="didal-tool-chip">{TOOL_LABELS[tool] || tool}</div>
                ))}
              </div>
            </div>
            <div className="didal-tool-section">
              <span className="didal-tool-section-label">Compute</span>
              <div className="didal-tool-grid">
                {["execute_r_code", "run_niche_model", "r_workspace_status", "list_r_packages"].map((tool) => (
                  <div key={tool} className="didal-tool-chip">{TOOL_LABELS[tool] || tool}</div>
                ))}
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

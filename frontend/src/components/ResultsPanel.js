import React, { useState } from "react";

/**
 * ResultsPanel — displays SDM model outputs (suitability maps, metrics,
 * downloadable files) in the auxiliary panel.
 *
 * Props:
 *   modelResults: Array of parsed model result objects from run_maxent_model /
 *                 run_niche_model tool calls.
 *   messages: Chat messages array (fallback: scan content for /workspace/ URLs).
 */

const FILE_ICONS = {
  png: "\u{1F5BC}",   // framed picture
  tif: "\u{1F30D}",   // globe
  tiff: "\u{1F30D}",
  csv: "\u{1F4CA}",   // bar chart
  rds: "\u{1F4E6}",   // package
  txt: "\u{1F4C4}",   // page facing up
  geojson: "\u{1F30E}",
  shp: "\u{1F30E}",
};

const FILE_LABELS = {
  suitability_png: "Suitability Map (PNG)",
  suitability_tif: "Suitability Raster (GeoTIFF)",
  summary_csv: "Model Summary",
  summary_txt: "Model Summary",
  contributions_csv: "Variable Contributions",
  permutation_importance_csv: "Permutation Importance",
  occurrences_csv: "Filtered Occurrences",
  ellipsoid_params: "Ellipsoid Parameters (RDS)",
};

function formatMetricValue(key, value) {
  if (typeof value === "number") {
    if (key === "auc" || key === "training_gain" || key === "neg_loglik") {
      return value.toFixed(4);
    }
    return value.toLocaleString();
  }
  if (Array.isArray(value)) return value.join(", ");
  return String(value);
}

function getFileExtension(path) {
  const parts = path.split(".");
  return parts.length > 1 ? parts.pop().toLowerCase() : "";
}

function getFileName(path) {
  return path.split("/").pop();
}

function MetricsTable({ result }) {
  const rows = [];

  if (result.species) rows.push(["Species", result.species]);
  if (result.algorithm) rows.push(["Algorithm", result.algorithm]);
  if (result.n_points) rows.push(["Presence Points", formatMetricValue("n_points", result.n_points)]);
  if (result.n_background) rows.push(["Background Points", formatMetricValue("n_background", result.n_background)]);
  if (result.auc != null) rows.push(["AUC", formatMetricValue("auc", result.auc)]);
  if (result.training_gain != null) rows.push(["Training Gain", formatMetricValue("training_gain", result.training_gain)]);
  if (result.neg_loglik != null) rows.push(["Neg. Log-Likelihood", formatMetricValue("neg_loglik", result.neg_loglik)]);
  if (result.m_mask) rows.push(["M Mask", result.m_mask]);
  if (result.variables?.length) rows.push(["Variables", result.variables.join(", ")]);

  if (rows.length === 0) return null;

  return (
    <table className="results-metrics-table">
      <tbody>
        {rows.map(([label, value], i) => (
          <tr key={i}>
            <td className="results-metric-label">{label}</td>
            <td className="results-metric-value">{value}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

function FileDownloadList({ files }) {
  if (!files || Object.keys(files).length === 0) return null;

  const entries = Object.entries(files).filter(([, path]) => path);

  return (
    <div className="results-downloads">
      <h4 className="results-section-title">Downloads</h4>
      <div className="results-file-list">
        {entries.map(([key, path]) => {
          const ext = getFileExtension(path);
          const icon = FILE_ICONS[ext] || "\u{1F4C1}";
          const label = FILE_LABELS[key] || getFileName(path);
          const fileName = getFileName(path);
          return (
            <a
              key={key}
              href={path}
              download={fileName}
              className="results-file-item"
              target="_blank"
              rel="noopener noreferrer"
            >
              <span className="results-file-icon">{icon}</span>
              <span className="results-file-info">
                <span className="results-file-label">{label}</span>
                <span className="results-file-name">{fileName}</span>
              </span>
              <span className="results-download-icon">
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none">
                  <path d="M21 15v4a2 2 0 01-2 2H5a2 2 0 01-2-2v-4" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"/>
                  <polyline points="7 10 12 15 17 10" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"/>
                  <line x1="12" y1="15" x2="12" y2="3" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"/>
                </svg>
              </span>
            </a>
          );
        })}
      </div>
    </div>
  );
}

function SuitabilityMapPreview({ files, species }) {
  const pngPath = files?.suitability_png;
  if (!pngPath) return null;

  return (
    <div className="results-map-preview">
      <h4 className="results-section-title">Suitability Map</h4>
      <img
        src={pngPath}
        alt={`${species || "Species"} suitability map`}
        className="results-map-image"
        onClick={() => window.open(pngPath, "_blank")}
      />
    </div>
  );
}

function ResultCard({ result, index, isExpanded, onToggle }) {
  const species = result.species || "Unknown Species";
  const algorithm = result.algorithm || "SDM";
  const success = result.success !== false;
  const aucBadge = result.auc != null ? `AUC: ${result.auc.toFixed(3)}` : null;

  return (
    <div className={`results-card ${success ? "" : "results-card-error"}`}>
      <div className="results-card-header" onClick={onToggle}>
        <div className="results-card-title">
          <span className="results-card-species">{species}</span>
          <span className="results-card-algo">{algorithm}</span>
        </div>
        <div className="results-card-badges">
          {aucBadge && <span className="results-badge results-badge-auc">{aucBadge}</span>}
          {result.n_points && (
            <span className="results-badge results-badge-pts">{result.n_points} pts</span>
          )}
          <span className={`results-expand-icon ${isExpanded ? "expanded" : ""}`}>
            {isExpanded ? "\u25BC" : "\u25B6"}
          </span>
        </div>
      </div>

      {!success && result.error && (
        <div className="results-error-msg">{result.error}</div>
      )}

      {isExpanded && success && (
        <div className="results-card-body">
          <SuitabilityMapPreview files={result.files} species={species} />
          <MetricsTable result={result} />
          <FileDownloadList files={result.files} />
        </div>
      )}
    </div>
  );
}

/**
 * Extract model results from chat messages by scanning tool call results
 * for run_maxent_model / run_niche_model outputs.
 */
function extractModelResults(messages) {
  const results = [];
  if (!messages) return results;

  for (const msg of messages) {
    if (msg.type !== "agent" || !msg.toolCalls) continue;
    for (const tc of msg.toolCalls) {
      if (tc.name !== "run_maxent_model" && tc.name !== "run_niche_model") continue;
      if (!tc.result) continue;

      try {
        const raw = typeof tc.result === "string" ? JSON.parse(tc.result) : tc.result;

        // Check if postprocessed (has model_result key from _postprocess_model_result)
        if (raw.model_result) {
          results.push({ ...raw.model_result, file_urls: raw.file_urls });
          continue;
        }

        // Try extracting [RESULT_JSON] from stdout
        const stdout = raw.stdout || "";
        const match = stdout.match(/\[RESULT_JSON\]\s*(\{.*?\})\s*$/s);
        if (match) {
          const parsed = JSON.parse(match[1]);
          results.push(parsed);
          continue;
        }

        // Fallback: use raw result if it has species/success fields
        if (raw.species || raw.success != null) {
          results.push(raw);
        }
      } catch (_) {
        /* skip unparseable results */
      }
    }
  }
  return results;
}

/**
 * Fallback: scan message content for /workspace/ URLs when no structured
 * tool results are available.
 */
function extractWorkspaceUrls(messages) {
  const urls = new Set();
  if (!messages) return urls;

  for (const msg of messages) {
    if (msg.type !== "agent" || !msg.content) continue;
    // Match markdown images and links with /workspace/ paths
    const re = /(?:!\[[^\]]*\]|(?<!!)\[[^\]]*\])\(([^)]*\/workspace\/[^)]+)\)/g;
    let m;
    while ((m = re.exec(msg.content)) !== null) {
      urls.add(m[1]);
    }
  }
  return urls;
}

export function ResultsPanel({ modelResults: propResults, messages }) {
  const [expandedCards, setExpandedCards] = useState(new Set([0]));

  // Prefer prop results, fall back to extraction from messages
  const results = propResults?.length > 0
    ? propResults
    : extractModelResults(messages || []);

  const workspaceUrls = results.length === 0 ? extractWorkspaceUrls(messages || []) : new Set();

  const toggleCard = (index) => {
    setExpandedCards((prev) => {
      const next = new Set(prev);
      if (next.has(index)) next.delete(index);
      else next.add(index);
      return next;
    });
  };

  if (results.length === 0 && workspaceUrls.size === 0) {
    return (
      <div className="results-panel results-empty">
        <div className="results-empty-icon">
          <svg width="48" height="48" viewBox="0 0 24 24" fill="none">
            <path d="M21 16V8a2 2 0 00-1-1.73l-7-4a2 2 0 00-2 0l-7 4A2 2 0 003 8v8a2 2 0 001 1.73l7 4a2 2 0 002 0l7-4A2 2 0 0021 16z" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" opacity="0.3"/>
            <polyline points="3.27 6.96 12 12.01 20.73 6.96" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" opacity="0.3"/>
            <line x1="12" y1="22.08" x2="12" y2="12" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" opacity="0.3"/>
          </svg>
        </div>
        <p className="results-empty-title">No model results yet</p>
        <p className="results-empty-hint">
          Ask Emily to run a species distribution model. For example:
          <br/>
          <em>"Model the distribution of Panthera onca in Mexico using MaxEnt"</em>
        </p>
      </div>
    );
  }

  // Fallback: show workspace URLs as simple file list
  if (results.length === 0 && workspaceUrls.size > 0) {
    const urlArray = [...workspaceUrls];
    return (
      <div className="results-panel">
        <div className="results-header">
          <h3>Model Outputs</h3>
          <span className="results-count">{urlArray.length} files</span>
        </div>
        <div className="results-file-list">
          {urlArray.map((url, i) => {
            const ext = getFileExtension(url);
            const icon = FILE_ICONS[ext] || "\u{1F4C1}";
            const name = getFileName(url);
            return (
              <a
                key={i}
                href={url}
                download={name}
                className="results-file-item"
                target="_blank"
                rel="noopener noreferrer"
              >
                <span className="results-file-icon">{icon}</span>
                <span className="results-file-info">
                  <span className="results-file-label">{name}</span>
                </span>
                <span className="results-download-icon">
                  <svg width="14" height="14" viewBox="0 0 24 24" fill="none">
                    <path d="M21 15v4a2 2 0 01-2 2H5a2 2 0 01-2-2v-4" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"/>
                    <polyline points="7 10 12 15 17 10" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"/>
                    <line x1="12" y1="15" x2="12" y2="3" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"/>
                  </svg>
                </span>
              </a>
            );
          })}
        </div>
      </div>
    );
  }

  return (
    <div className="results-panel">
      <div className="results-header">
        <h3>Model Results</h3>
        <span className="results-count">{results.length} model{results.length !== 1 ? "s" : ""}</span>
      </div>
      <div className="results-cards">
        {results.map((result, i) => (
          <ResultCard
            key={i}
            result={result}
            index={i}
            isExpanded={expandedCards.has(i)}
            onToggle={() => toggleCard(i)}
          />
        ))}
      </div>
    </div>
  );
}

export { extractModelResults };

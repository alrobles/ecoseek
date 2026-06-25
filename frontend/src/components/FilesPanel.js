import React, { useState, useEffect, useCallback } from "react";

function formatSize(bytes) {
  if (bytes === 0) return "0 B";
  const units = ["B", "KB", "MB", "GB"];
  const i = Math.floor(Math.log(bytes) / Math.log(1024));
  return (bytes / Math.pow(1024, i)).toFixed(i > 0 ? 1 : 0) + " " + units[i];
}

function formatDate(dateStr) {
  try {
    const d = new Date(dateStr);
    return d.toLocaleDateString() + " " + d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
  } catch {
    return dateStr;
  }
}

const DATA_EXTENSIONS = [".csv", ".tsv", ".json", ".parquet", ".tif", ".tiff", ".png", ".geojson", ".gpkg", ".rds", ".rda"];

export function FilesPanel() {
  const [files, setFiles] = useState([]);
  const [path, setPath] = useState("");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [showAll, setShowAll] = useState(false);

  const fetchFiles = useCallback(async (subpath) => {
    setLoading(true);
    setError(null);
    try {
      const url = "/workspace/" + (subpath || "");
      const res = await fetch(url);
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = await res.json();
      setFiles(data);
      setPath(subpath || "");
    } catch (err) {
      setError(err.message);
      setFiles([]);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchFiles("");
  }, [fetchFiles]);

  const handleDownload = (item) => {
    if (item.type === "directory") {
      fetchFiles(path ? path + "/" + item.name : item.name);
    } else {
      const url = "/workspace/" + (path ? path + "/" : "") + item.name;
      window.open(url, "_blank");
    }
  };

  const goUp = () => {
    const parts = path.split("/").filter(Boolean);
    parts.pop();
    fetchFiles(parts.join("/"));
  };

  const isDataFile = (name) => {
    const lower = name.toLowerCase();
    return DATA_EXTENSIONS.some((ext) => lower.endsWith(ext));
  };

  const visibleFiles = files.filter((item) => {
    if (item.type === "directory") return true;
    if (showAll) return true;
    return isDataFile(item.name);
  });

  const dataCount = files.filter((f) => f.type !== "directory" && isDataFile(f.name)).length;
  const totalFileCount = files.filter((f) => f.type !== "directory").length;

  return (
    <div className="files-panel">
      <div className="files-toolbar">
        <div className="files-breadcrumb">
          <button className="files-crumb" onClick={() => fetchFiles("")}>workspace</button>
          {path.split("/").filter(Boolean).map((part, i, arr) => (
            <React.Fragment key={i}>
              <span className="files-separator">/</span>
              <button
                className="files-crumb"
                onClick={() => fetchFiles(arr.slice(0, i + 1).join("/"))}
              >
                {part}
              </button>
            </React.Fragment>
          ))}
        </div>
        <div className="files-actions">
          <button
            className={`files-filter-btn ${!showAll ? "active" : ""}`}
            onClick={() => setShowAll(false)}
            title="Show data files only (CSV, JSON, TIF, etc.)"
          >
            📊 Data ({dataCount})
          </button>
          <button
            className={`files-filter-btn ${showAll ? "active" : ""}`}
            onClick={() => setShowAll(true)}
            title="Show all files"
          >
            📁 All ({totalFileCount})
          </button>
          <button className="files-refresh" onClick={() => fetchFiles(path)} title="Refresh">
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none">
              <path d="M1 4v6h6M23 20v-6h-6" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"/>
              <path d="M20.49 9A9 9 0 005.64 5.64L1 10m22 4l-4.64 4.36A9 9 0 013.51 15" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"/>
            </svg>
          </button>
        </div>
      </div>

      {loading && <div className="files-loading">Loading...</div>}
      {error && (
        <div className="files-empty">
          <p>Workspace not available.</p>
          <p className="files-hint">
            Data files from GBIF queries and model outputs will appear here.
          </p>
        </div>
      )}
      {!loading && !error && visibleFiles.length === 0 && (
        <div className="files-empty">
          <p>{showAll ? "Workspace is empty." : "No data files yet."}</p>
          <p className="files-hint">
            Ask Emily to query GBIF or run a model — CSV, JSON, and TIF outputs
            will appear here for download.
          </p>
        </div>
      )}
      {!loading && !error && visibleFiles.length > 0 && (
        <div className="files-list">
          {path && (
            <div className="files-item files-dir" onClick={goUp}>
              <span className="files-icon">
                <svg width="16" height="16" viewBox="0 0 24 24" fill="none">
                  <path d="M19 12H5M12 19l-7-7 7-7" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"/>
                </svg>
              </span>
              <span className="files-name">..</span>
              <span className="files-size"></span>
              <span className="files-date"></span>
              <span className="files-dl"></span>
            </div>
          )}
          {visibleFiles
            .sort((a, b) => {
              if (a.type === "directory" && b.type !== "directory") return -1;
              if (a.type !== "directory" && b.type === "directory") return 1;
              return a.name.localeCompare(b.name);
            })
            .map((item) => {
              const isData = item.type !== "directory" && isDataFile(item.name);
              return (
                <div
                  key={item.name}
                  className={`files-item ${item.type === "directory" ? "files-dir" : "files-file"}${isData ? " files-data" : ""}`}
                  onClick={() => handleDownload(item)}
                >
                  <span className="files-icon">
                    {item.type === "directory" ? (
                      <svg width="16" height="16" viewBox="0 0 24 24" fill="none">
                        <path d="M22 19a2 2 0 01-2 2H4a2 2 0 01-2-2V5a2 2 0 012-2h5l2 3h9a2 2 0 012 2z" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"/>
                      </svg>
                    ) : (
                      <svg width="16" height="16" viewBox="0 0 24 24" fill="none">
                        <path d="M14 2H6a2 2 0 00-2 2v16a2 2 0 002 2h12a2 2 0 002-2V8z" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"/>
                        <polyline points="14 2 14 8 20 8" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"/>
                      </svg>
                    )}
                  </span>
                  <span className="files-name">{item.name}</span>
                  <span className="files-size">{item.type !== "directory" ? formatSize(item.size || 0) : ""}</span>
                  <span className="files-date">{formatDate(item.mtime)}</span>
                  <span className="files-dl">
                    {item.type !== "directory" && (
                      <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                        <path d="M21 15v4a2 2 0 01-2 2H5a2 2 0 01-2-2v-4"/>
                        <polyline points="7 10 12 15 17 10"/>
                        <line x1="12" y1="15" x2="12" y2="3"/>
                      </svg>
                    )}
                  </span>
                </div>
              );
            })}
        </div>
      )}
    </div>
  );
}

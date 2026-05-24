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

export function FilesPanel() {
  const [files, setFiles] = useState([]);
  const [path, setPath] = useState("");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

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

  const handleClick = (item) => {
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
        <button className="files-refresh" onClick={() => fetchFiles(path)} title="Refresh">
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none">
            <path d="M1 4v6h6M23 20v-6h-6" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"/>
            <path d="M20.49 9A9 9 0 005.64 5.64L1 10m22 4l-4.64 4.36A9 9 0 013.51 15" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"/>
          </svg>
        </button>
      </div>

      {loading && <div className="files-loading">Loading...</div>}
      {error && (
        <div className="files-empty">
          <p>Cannot list workspace files.</p>
          <p className="files-hint">
            Files placed in <code>./workspace/</code> (or <code>$ECOSEEK_WORKSPACE</code>) appear here.
            Hermes Beta can write results to this directory for easy access.
          </p>
        </div>
      )}
      {!loading && !error && files.length === 0 && (
        <div className="files-empty">
          <p>Workspace is empty.</p>
          <p className="files-hint">
            Files from Emily, Hermes Beta, or the terminal will appear here.
            Use the Terminal tab to download files or run scripts.
          </p>
        </div>
      )}
      {!loading && !error && files.length > 0 && (
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
            </div>
          )}
          {files
            .sort((a, b) => {
              if (a.type === "directory" && b.type !== "directory") return -1;
              if (a.type !== "directory" && b.type === "directory") return 1;
              return a.name.localeCompare(b.name);
            })
            .map((item) => (
              <div
                key={item.name}
                className={`files-item ${item.type === "directory" ? "files-dir" : "files-file"}`}
                onClick={() => handleClick(item)}
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
              </div>
            ))}
        </div>
      )}
    </div>
  );
}

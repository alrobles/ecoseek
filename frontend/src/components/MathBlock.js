import React, { useState } from "react";
import katex from "katex";
import "katex/dist/katex.min.css";

function renderKatex(tex, displayMode) {
  try {
    return katex.renderToString(tex, {
      displayMode,
      throwOnError: false,
      trust: true,
      strict: false,
    });
  } catch {
    return null;
  }
}

export function MathInline({ value }) {
  const [showCopy, setShowCopy] = useState(false);
  const [copied, setCopied] = useState(false);
  const html = renderKatex(value, false);

  if (!html) {
    return <code>{value}</code>;
  }

  const handleCopy = async (e) => {
    e.stopPropagation();
    try {
      await navigator.clipboard.writeText(value);
    } catch {
      const ta = document.createElement("textarea");
      ta.value = value;
      document.body.appendChild(ta);
      ta.select();
      document.execCommand("copy");
      document.body.removeChild(ta);
    }
    setCopied(true);
    setTimeout(() => setCopied(false), 1500);
  };

  return (
    <span
      className="math-inline-wrapper"
      onMouseEnter={() => setShowCopy(true)}
      onMouseLeave={() => { setShowCopy(false); setCopied(false); }}
    >
      <span dangerouslySetInnerHTML={{ __html: html }} />
      {showCopy && (
        <button
          className={`math-copy-button inline ${copied ? "copied" : ""}`}
          onClick={handleCopy}
          title="Copy LaTeX"
        >
          {copied ? "✓" : "TeX"}
        </button>
      )}
    </span>
  );
}

export function MathBlock({ value }) {
  const [copied, setCopied] = useState(false);
  const html = renderKatex(value, true);

  if (!html) {
    return (
      <pre className="math-fallback">
        <code>{value}</code>
      </pre>
    );
  }

  const handleCopy = async () => {
    try {
      await navigator.clipboard.writeText(value);
    } catch {
      const ta = document.createElement("textarea");
      ta.value = value;
      document.body.appendChild(ta);
      ta.select();
      document.execCommand("copy");
      document.body.removeChild(ta);
    }
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  return (
    <div className="math-block-wrapper">
      <div className="math-block-content" dangerouslySetInnerHTML={{ __html: html }} />
      <button
        className={`math-copy-button block ${copied ? "copied" : ""}`}
        onClick={handleCopy}
        title={copied ? "Copied LaTeX!" : "Copy LaTeX source"}
      >
        {copied ? (
          <>
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              <polyline points="20 6 9 17 4 12" />
            </svg>
            <span>Copied!</span>
          </>
        ) : (
          <>
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              <rect x="9" y="9" width="13" height="13" rx="2" ry="2" />
              <path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1" />
            </svg>
            <span>Copy LaTeX</span>
          </>
        )}
      </button>
    </div>
  );
}

import React, { useState, useEffect, useRef, useCallback } from "react";
import ReactMarkdown from "react-markdown";
import { MathJax } from "better-react-mathjax";
import "./App.css";
import { ThemeToggle } from "./components/ThemeToggle";
import { ResizableLayout } from "./components/ResizableLayout";
import { CodeBlock } from "./components/CodeBlock";
import { RenderPreview, DiDALPanel } from "./components/RenderPreview";
import { FilesPanel } from "./components/FilesPanel";
import { ReactComponent as EcoSeekLogo } from "./ecoseek-logo.svg";
import emilyAvatar from "./emily-avatar.png";
import emilyThinking from "./emily-avatar-thinking.gif";
import { useAuth } from "./contexts/AuthContext";
import { chatCompletionStream, checkHealth, checkRemoteHealth, BROKER_URL, CHAT_URL, IS_LOCAL_EMILY, HERMES_REMOTE_URL } from "./api/broker";
import { ToolCallsContainer } from "./components/ToolCallCard";
import { extractPdfText, validatePdf } from "./utils/pdfExtract";

function LoginScreen({ onLogin }) {
  return (
    <div className="login-screen">
      <div className="login-card">
        <EcoSeekLogo className="login-logo" />
        <h1>EcoSeek</h1>
        <img src={emilyAvatar} alt="Emily" className="login-emily-avatar" />
        <p className="login-subtitle">
          Meet Emily — your AI ecological research assistant
        </p>
        <button className="login-button" onClick={onLogin}>
          <svg width="20" height="20" viewBox="0 0 24 24" fill="currentColor">
            <path d="M12 0c-6.626 0-12 5.373-12 12 0 5.302 3.438 9.8 8.207 11.387.599.111.793-.261.793-.577v-2.234c-3.338.726-4.033-1.416-4.033-1.416-.546-1.387-1.333-1.756-1.333-1.756-1.089-.745.083-.729.083-.729 1.205.084 1.839 1.237 1.839 1.237 1.07 1.834 2.807 1.304 3.492.997.107-.775.418-1.305.762-1.604-2.665-.305-5.467-1.334-5.467-5.931 0-1.311.469-2.381 1.236-3.221-.124-.303-.535-1.524.117-3.176 0 0 1.008-.322 3.301 1.23.957-.266 1.983-.399 3.003-.404 1.02.005 2.047.138 3.006.404 2.291-1.552 3.297-1.23 3.297-1.23.653 1.653.242 2.874.118 3.176.77.84 1.235 1.911 1.235 3.221 0 4.609-2.807 5.624-5.479 5.921.43.372.823 1.102.823 2.222v3.293c0 .319.192.694.801.576 4.765-1.589 8.199-6.086 8.199-11.386 0-6.627-5.373-12-12-12z" />
          </svg>
          Sign in with GitHub
        </button>
        <p className="login-note">
          {IS_LOCAL_EMILY
            ? "Emily Local \u00b7 GitHub Auth \u00b7 Hermes"
            : "Powered by EcoSeek \u00b7 AgenticPlug \u00b7 Hermes"}
        </p>
      </div>
    </div>
  );
}

function App() {
  const { user, loading, login, logout, handleCallback } = useAuth();
  const [query, setQuery] = useState("");
  const [messages, setMessages] = useState([]);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState(null);
  const [isOnline, setIsOnline] = useState(false);
  const [remoteStatus, setRemoteStatus] = useState(null);
  const [expandedReasoning, setExpandedReasoning] = useState(new Set());
  const [rightPanelTab, setRightPanelTab] = useState("output");
  const [streamingContent, setStreamingContent] = useState("");
  const [streamingReasoning, setStreamingReasoning] = useState("");
  const [activeToolCalls, setActiveToolCalls] = useState([]);
  const [toolProgress, setToolProgress] = useState(null); // {tool, emoji, label, status}
  const [didalStages, setDidalStages] = useState([]); // live progress pipeline
  const [didalExchanges, setDidalExchanges] = useState([]);
  const [lastClassification, setLastClassification] = useState(null);
  const [lastProtocolStages, setLastProtocolStages] = useState(null);
  const [lastTraceId, setLastTraceId] = useState(null);
  const [lastJudgeResult, setLastJudgeResult] = useState(null);
  const [lastHermesTrace, setLastHermesTrace] = useState(null);
  const [reasoningMode, setReasoningMode] = useState("auto"); // "fast" | "deep" | "auto"
  const [elapsedSeconds, setElapsedSeconds] = useState(0);
  const [uploadingPdf, setUploadingPdf] = useState(false);
  const [uploadedFile, setUploadedFile] = useState(null); // {name, text, pages}
  const messagesEndRef = useRef(null);
  const abortRef = useRef(null);
  const timerRef = useRef(null);
  const fileInputRef = useRef(null);

  const currentTheme = document.documentElement.getAttribute("data-theme") || "dark";

  // Elapsed timer — ticks every second while loading
  useEffect(() => {
    if (isLoading) {
      setElapsedSeconds(0);
      timerRef.current = setInterval(() => setElapsedSeconds(s => s + 1), 1000);
    } else {
      clearInterval(timerRef.current);
      timerRef.current = null;
    }
    return () => clearInterval(timerRef.current);
  }, [isLoading]);

  const formatElapsed = (s) => {
    if (s < 60) return `${s}s`;
    const m = Math.floor(s / 60);
    const sec = s % 60;
    return `${m}m ${sec}s`;
  };

  // Handle OAuth callback
  useEffect(() => {
    if (window.location.pathname === "/callback") {
      handleCallback();
    }
  }, [handleCallback]);

  // Health polling (local + remote)
  useEffect(() => {
    const poll = async () => {
      const ok = await checkHealth();
      setIsOnline(ok);
      const remote = await checkRemoteHealth();
      setRemoteStatus(remote);
    };
    poll();
    const id = setInterval(poll, 15000);
    return () => clearInterval(id);
  }, []);

  const scrollToBottom = () => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  };

  const toggleReasoning = (idx) => {
    setExpandedReasoning((prev) => {
      const s = new Set(prev);
      s.has(idx) ? s.delete(idx) : s.add(idx);
      return s;
    });
  };

  // PDF upload handler — extracts text client-side, sends to Emily for LACS
  const handlePdfUpload = useCallback(async (e) => {
    const file = e.target.files?.[0];
    if (!file) return;
    // Reset file input so the same file can be re-uploaded
    e.target.value = "";

    const validation = validatePdf(file);
    if (!validation.ok) {
      setError(validation.error);
      return;
    }

    setUploadingPdf(true);
    setError(null);

    try {
      const { text, pages } = await extractPdfText(file);
      if (!text.trim()) {
        setError("Could not extract text from PDF (might be image-based)");
        setUploadingPdf(false);
        return;
      }

      setUploadedFile({ name: file.name, text, pages });

      // Truncate text preview for the user message (full text goes to Emily)
      const preview = text.slice(0, 300).replace(/\s+/g, " ").trim();
      const userMsg = {
        type: "user",
        content: `I'm uploading a paper: **${file.name}** (${pages} pages).\n\nPlease ingest this document with upload_document, then classify it with LACS and find similar literature.\n\n> ${preview}...`,
      };
      setMessages((prev) => [...prev, userMsg]);
      setIsLoading(true);
      setStreamingContent("");
      setStreamingReasoning("");
      setActiveToolCalls([]);
      setToolProgress(null);
      setDidalStages([]);

      const history = [
        {
          role: "user",
          content: `[PDF Upload: ${file.name}, ${pages} pages]\n\nPlease do the following:\n1. Use upload_document to ingest this paper text into my knowledge base\n2. Use classify_literature to score its domain relevance with LACS\n3. Use literature_search to find similar papers\n\nHere is the full extracted text:\n\n${text}`,
        },
      ];

      const abortController = new AbortController();
      abortRef.current = abortController;

      await chatCompletionStream(
        history,
        {
          reasoningMode: "auto",
          onToken: (t) => { setStreamingContent((prev) => prev + t); scrollToBottom(); },
          onReasoning: (t) => { setStreamingReasoning((prev) => prev + t); },
          onToolCallStart: (tool) => {
            setActiveToolCalls((prev) => [...prev, { ...tool, arguments: "" }]);
          },
          onToolCallDelta: (id, arg) => {
            setActiveToolCalls((prev) =>
              prev.map((tc) => tc.id === id ? { ...tc, arguments: tc.arguments + arg } : tc)
            );
          },
          onToolProgress: (info) => { setToolProgress(info); },
          onDone: (resp) => {
            const content = resp?.choices?.[0]?.message?.content || streamingContent;
            setMessages((prev) => [...prev, { type: "agent", content }]);
            setStreamingContent("");
            setStreamingReasoning("");
            setIsLoading(false);
            setActiveToolCalls([]);
            setToolProgress(null);
            setUploadedFile(null);
          },
          onError: (err) => {
            setError(err.message);
            setIsLoading(false);
            setUploadedFile(null);
          },
          signal: abortController.signal,
        },
      );
    } catch (err) {
      setError(`PDF processing failed: ${err.message}`);
    } finally {
      setUploadingPdf(false);
    }
  }, [streamingContent, scrollToBottom]);

  const handleSubmit = useCallback(
    async (e) => {
      e.preventDefault();
      if (!query.trim() || isLoading) return;

      const userMsg = { type: "user", content: query };
      setMessages((prev) => [...prev, userMsg]);
      setIsLoading(true);
      setError(null);
      setQuery("");
      setStreamingContent("");
      setStreamingReasoning("");
      setActiveToolCalls([]);
      setToolProgress(null);
      setDidalStages([]);

      const history = [...messages, userMsg]
        .filter((m) => m.type === "user" || m.type === "agent")
        .slice(-20)
        .map((m) => ({
          role: m.type === "user" ? "user" : "assistant",
          content: m.content,
        }));

      const abortController = new AbortController();
      abortRef.current = abortController;

      try {
        await chatCompletionStream(
          history,
          {
            reasoningMode,
            onToken: (text) => {
              setStreamingContent((prev) => prev + text);
              scrollToBottom();
            },
            onReasoning: (text) => {
              setStreamingReasoning((prev) => prev + text);
            },
            onToolCallStart: (tool) => {
              setActiveToolCalls((prev) => [...prev, { ...tool, arguments: "" }]);
              if (["escalate_remote", "dialectical_exchange", "didal_protocol", "classify_prompt"].includes(tool.name)) {
                setDidalExchanges((prev) => [
                  ...prev,
                  {
                    id: tool.id,
                    tool: tool.name,
                    status: "running",
                    startedAt: new Date().toISOString(),
                  },
                ]);
              }
            },
            onToolCallDelta: (id, argDelta) => {
              setActiveToolCalls((prev) =>
                prev.map((tc) =>
                  tc.id === id
                    ? { ...tc, arguments: tc.arguments + argDelta }
                    : tc
                )
              );
            },
            onToolProgress: (info) => {
              setToolProgress(info);
              // Parse DiDAL progress from label text like "[DiDAL] Classifying — analyzing question complexity"
              const label = info.label || info.tool || "";
              if (label.startsWith("[DiDAL]") || (info.tool && info.tool.includes("didal"))) {
                const stageMatch = label.match(/\[DiDAL\]\s*(\w+)/);
                if (stageMatch) {
                  const stageName = stageMatch[1];
                  const detail = label.replace(/\[DiDAL\]\s*\w+\s*[—–-]?\s*/, "").trim();
                  setDidalStages((prev) => {
                    const existing = prev.find((s) => s.name === stageName);
                    if (existing) {
                      return prev.map((s) => s.name === stageName ? { ...s, detail, status: "done" } : s);
                    }
                    // Mark previous as done, add new as active
                    return [
                      ...prev.map((s) => ({ ...s, status: "done" })),
                      { name: stageName, detail, status: "active", time: Date.now() },
                    ];
                  });
                }
              }
              if (info.status === "completed") {
                setTimeout(() => setToolProgress(null), 1500);
              }
            },
            onTrace: (trace) => {
              setLastHermesTrace(trace);
            },
            onDone: (result) => {
              setMessages((prev) => [
                ...prev,
                {
                  type: "agent",
                  content: result.content,
                  reasoning: result.reasoning,
                  agentName: result.model || "Emily",
                  finishReason: result.finishReason,
                  toolCalls: result.toolCalls,
                  didalPhase: result.toolCalls?.some(
                    (tc) => tc.name === "escalate_remote" || tc.name === "dialectical_exchange"
                  ),
                },
              ]);
              setStreamingContent("");
              setStreamingReasoning("");
              setToolProgress(null);
              setActiveToolCalls((prev) => prev.map((tc) => ({ ...tc, status: "done" })));
              setDidalExchanges((prev) =>
                prev.map((ex) => ({
                  ...ex,
                  status: "done",
                  completedAt: new Date().toISOString(),
                }))
              );

              // Extract classification and trace_id from didal_protocol results
              if (result.toolCalls) {
                for (const tc of result.toolCalls) {
                  if (tc.name === "didal_protocol" || tc.name === "classify_prompt") {
                    try {
                      const parsed = typeof tc.result === "string" ? JSON.parse(tc.result) : tc.result;
                      if (parsed?.classification) setLastClassification(parsed.classification);
                      if (parsed?.stages) setLastProtocolStages(parsed.stages);
                      if (parsed?.trace_id) setLastTraceId(parsed.trace_id);
                      if (parsed?.judge) setLastJudgeResult(parsed.judge);
                    } catch (_) { /* ignore parse errors */ }
                  }
                }
              }

              setTimeout(() => setActiveToolCalls([]), 3000);
              scrollToBottom();
            },
            onError: (err) => {
              console.error("Stream error:", err);
              setError(err.message);
              setDidalExchanges((prev) =>
                prev.map((ex) =>
                  ex.status === "running" ? { ...ex, status: "error" } : ex
                )
              );
            },
          },
          "hermes",
          abortController.signal,
        );
      } catch (err) {
        if (err.name !== "AbortError") {
          console.error("Chat error:", err);
          const errMsg = err.message || "Failed to get response";
          setError(errMsg);
          setMessages((prev) => [
            ...prev,
            { type: "error", content: `Error: ${errMsg}` },
          ]);
        }
      } finally {
        setIsLoading(false);
        setStreamingContent("");
        setStreamingReasoning("");
        abortRef.current = null;
      }
    },
    [query, messages, isLoading]
  );

  if (loading) {
    return (
      <div className="app">
        <div className="loading-screen">Loading...</div>
      </div>
    );
  }

  if (!user) {
    return <LoginScreen onLogin={login} />;
  }

  return (
    <div className="app">
      <header className="header">
        <div className="header-brand">
          <div className="logo-container">
            <EcoSeekLogo className="logo-icon" />
          </div>
          <div className="brand-text">
            <h1>EcoSeek</h1>
          </div>
        </div>
        <div className="header-status">
          <div
            className={`status-indicator ${isOnline ? "online" : "offline"}`}
          >
            <div className="status-dot"></div>
            <span className="status-text">
              {isOnline
                ? IS_LOCAL_EMILY
                  ? "Emily Local"
                  : "Emily Remote"
                : "Offline"}
            </span>
          </div>
        </div>
        <div className="header-actions">
          <div className="user-info">
            {user.avatarUrl && (
              <img
                src={user.avatarUrl}
                alt={user.login}
                className="user-avatar"
              />
            )}
            <span className="user-name">{user.login}</span>
          </div>
          <a
            href="https://github.com/alrobles/ecoseek"
            target="_blank"
            rel="noopener noreferrer"
            className="action-button github-link"
            aria-label="View on GitHub"
          >
            <svg width="20" height="20" viewBox="0 0 24 24" fill="currentColor">
              <path d="M12 0c-6.626 0-12 5.373-12 12 0 5.302 3.438 9.8 8.207 11.387.599.111.793-.261.793-.577v-2.234c-3.338.726-4.033-1.416-4.033-1.416-.546-1.387-1.333-1.756-1.333-1.756-1.089-.745.083-.729.083-.729 1.205.084 1.839 1.237 1.839 1.237 1.07 1.834 2.807 1.304 3.492.997.107-.775.418-1.305.762-1.604-2.665-.305-5.467-1.334-5.467-5.931 0-1.311.469-2.381 1.236-3.221-.124-.303-.535-1.524.117-3.176 0 0 1.008-.322 3.301 1.23.957-.266 1.983-.399 3.003-.404 1.02.005 2.047.138 3.006.404 2.291-1.552 3.297-1.23 3.297-1.23.653 1.653.242 2.874.118 3.176.77.84 1.235 1.911 1.235 3.221 0 4.609-2.807 5.624-5.479 5.921.43.372.823 1.102.823 2.222v3.293c0 .319.192.694.801.576 4.765-1.589 8.199-6.086 8.199-11.386 0-6.627-5.373-12-12-12z" />
            </svg>
          </a>
          <ThemeToggle />
          <button className="action-button logout-button" onClick={logout}>
            Sign out
          </button>
        </div>
      </header>

      <main className="main">
        <ResizableLayout initialLeftWidth={50}>
          <div className="chat-section">
            <h2>Chat</h2>
            <div className="messages">
              {messages.length === 0 ? (
                <div className="welcome-message">
                  <EcoSeekLogo className="welcome-logo" />
                  <h3>Hi, I'm Emily!</h3>
                  <p>
                    I'm your ecological research assistant. Ask me about
                    species distribution models, GBIF data, phylogenetic
                    analysis, niche modeling, or any ecological workflow.
                  </p>
                  <div className="quick-prompts">
                    {[
                      "Help me build a species distribution model for jaguar",
                      "Query GBIF for bird occurrences in Costa Rica",
                      "What R packages do I need for niche modeling?",
                      "Explain MaxEnt vs. GLM for presence-only data",
                    ].map((prompt) => (
                      <button
                        key={prompt}
                        className="quick-prompt"
                        onClick={() => {
                          setQuery(prompt);
                        }}
                      >
                        {prompt}
                      </button>
                    ))}
                  </div>
                </div>
              ) : (
                messages.map((msg, index) => (
                  <div
                    key={index}
                    className={`message ${
                      msg.type === "user"
                        ? "user-message"
                        : msg.type === "agent"
                        ? "agent-message"
                        : "error-message"
                    }`}
                  >
                    <div className="message-header">
                      {msg.type === "agent" && (
                        <>
                          <img src={emilyAvatar} alt="Emily" className="emily-avatar" />
                          <span className="agent-name">Emily</span>
                        </>
                      )}
                      {msg.type === "agent" && msg.reasoning && (
                        <>
                          {expandedReasoning.has(index) && (
                            <div className="reasoning-content">
                              <ReactMarkdown>{msg.reasoning}</ReactMarkdown>
                            </div>
                          )}
                          <button
                            className="reasoning-toggle"
                            onClick={() => toggleReasoning(index)}
                            title={
                              expandedReasoning.has(index)
                                ? "Hide reasoning"
                                : "Show reasoning"
                            }
                          >
                            {expandedReasoning.has(index) ? "\u25BC" : "\u25B6"}{" "}
                            Reasoning
                          </button>
                        </>
                      )}
                    </div>
                    {msg.type === "agent" && msg.toolCalls && msg.toolCalls.length > 0 && (
                      <ToolCallsContainer toolCalls={msg.toolCalls} status="done" />
                    )}
                    <div className="message-content">
                      <MathJax>
                        <ReactMarkdown
                          components={{
                            code({ node, inline, className, children, ...props }) {
                              if (inline) {
                                return <code className="inline-code" {...props}>{children}</code>;
                              }
                              return (
                                <CodeBlock className={className} theme={currentTheme}>
                                  {children}
                                </CodeBlock>
                              );
                            },
                          }}
                        >
                          {msg.content}
                        </ReactMarkdown>
                      </MathJax>
                    </div>
                  </div>
                ))
              )}

              {/* Streaming response — shown while tokens arrive */}
              {isLoading && (streamingContent || streamingReasoning || activeToolCalls.length > 0) && (
                <div className="message agent-message streaming-message">
                  <div className="message-header">
                    <img src={emilyThinking} alt="Emily" className="emily-avatar emily-avatar-thinking" />
                    <span className="agent-name">Emily</span>
                    <span className="streaming-indicator">
                      <span className="streaming-dot" />
                      <span className="streaming-dot" />
                      <span className="streaming-dot" />
                    </span>
                    <span className="elapsed-timer">{formatElapsed(elapsedSeconds)}</span>
                  </div>
                  {activeToolCalls.length > 0 && (
                    <ToolCallsContainer toolCalls={activeToolCalls} status="running" />
                  )}
                  {streamingContent && (
                    <div className="message-content">
                      <MathJax>
                        <ReactMarkdown
                          components={{
                            code({ node, inline, className, children, ...props }) {
                              if (inline) {
                                return <code className="inline-code" {...props}>{children}</code>;
                              }
                              return (
                                <CodeBlock className={className} theme={currentTheme}>
                                  {children}
                                </CodeBlock>
                              );
                            },
                          }}
                        >
                          {streamingContent}
                        </ReactMarkdown>
                      </MathJax>
                    </div>
                  )}
                </div>
              )}

              <div ref={messagesEndRef} />
            </div>

            {isLoading && !streamingContent && (
              <div className="loading-animation">
                <img src={emilyThinking} alt="Emily" className="emily-avatar-loading" />
                <div className="loading-info">
                  {toolProgress && toolProgress.status === "running" ? (
                    <span className="tool-progress-label">
                      {toolProgress.emoji || "🔧"} {toolProgress.label || toolProgress.tool}
                    </span>
                  ) : activeToolCalls.length > 0 ? (
                    <span className="tool-progress-label">
                      🔧 {activeToolCalls[activeToolCalls.length - 1]?.name || "Working"}...
                    </span>
                  ) : (
                    <span className="tool-progress-label">Emily is thinking...</span>
                  )}
                  <span className="elapsed-timer">{formatElapsed(elapsedSeconds)}</span>
                  {didalStages.length > 0 && (
                    <div className="didal-progress-pipeline">
                      {didalStages.map((s, i) => (
                        <span key={i} className={`didal-pip-stage ${s.status}`}>
                          {s.status === "active" ? "◉" : "✓"} {s.name}
                        </span>
                      ))}
                    </div>
                  )}
                </div>
              </div>
            )}

            <form onSubmit={handleSubmit} className="input-form">
              <div className="reasoning-toggle" title="Reasoning mode: Fast (hermes-fast) skips agent loop for sub-second answers, Deep (hermes-reasoner) enables thinking mode, Auto (hermes-agent) uses full agentic loop">
                {[
                  { key: "fast", label: "Fast", icon: "\u26A1" },
                  { key: "auto", label: "Auto", icon: "\uD83D\uDD04" },
                  { key: "deep", label: "Deep", icon: "\uD83E\uDDE0" },
                ].map(({ key, label, icon }) => (
                  <button
                    key={key}
                    type="button"
                    className={`reasoning-btn ${reasoningMode === key ? "active" : ""}`}
                    onClick={() => setReasoningMode(key)}
                    disabled={isLoading}
                    aria-label={label}
                  >
                    <span className="reasoning-icon">{icon}</span>
                    <span className="reasoning-label">{label}</span>
                  </button>
                ))}
              </div>
              <input
                type="text"
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                placeholder={
                  reasoningMode === "fast" ? "Quick question for Emily..."
                    : reasoningMode === "deep" ? "Deep scientific question for Emily..."
                    : "Ask Emily about ecology..."
                }
                disabled={isLoading}
              />
              <div className="action-buttons">
                {/* Hidden file input for PDF upload */}
                <input
                  ref={fileInputRef}
                  type="file"
                  accept=".pdf,application/pdf"
                  style={{ display: "none" }}
                  onChange={handlePdfUpload}
                />
                <button
                  type="button"
                  className={`icon-button upload-btn ${uploadingPdf ? "uploading" : ""}`}
                  disabled={isLoading || uploadingPdf}
                  onClick={() => fileInputRef.current?.click()}
                  aria-label="Upload PDF paper"
                  title="Upload a PDF paper for LACS classification"
                >
                  {uploadingPdf ? (
                    <span className="upload-spinner" />
                  ) : (
                    <svg width="18" height="18" viewBox="0 0 24 24" fill="none">
                      <path
                        d="M21.44 11.05l-9.19 9.19a6 6 0 01-8.49-8.49l9.19-9.19a4 4 0 015.66 5.66l-9.2 9.19a2 2 0 01-2.83-2.83l8.49-8.48"
                        stroke="currentColor"
                        strokeWidth="2"
                        strokeLinecap="round"
                        strokeLinejoin="round"
                      />
                    </svg>
                  )}
                </button>
                <button
                  type="submit"
                  disabled={isLoading || !query.trim()}
                  className="icon-button"
                  aria-label="Send message"
                >
                  <svg width="18" height="18" viewBox="0 0 24 24" fill="none">
                    <path
                      d="M22 2L11 13M22 2L15 22L11 13M22 2L2 9L11 13"
                      stroke="currentColor"
                      strokeWidth="2"
                      strokeLinecap="round"
                      strokeLinejoin="round"
                    />
                  </svg>
                </button>
              </div>
              {uploadedFile && (
                <div className="upload-badge">
                  <span className="upload-badge-icon">&#128196;</span>
                  <span className="upload-badge-name">{uploadedFile.name}</span>
                  <span className="upload-badge-pages">({uploadedFile.pages} pages)</span>
                  <button
                    className="upload-badge-remove"
                    onClick={() => setUploadedFile(null)}
                    aria-label="Remove uploaded file"
                  >&times;</button>
                </div>
              )}
            </form>
          </div>

          <div className="computer-section">
            <div className="panel-tabs">
              <button
                className={`panel-tab ${rightPanelTab === "output" ? "active" : ""}`}
                onClick={() => setRightPanelTab("output")}
              >
                Output
              </button>
              <button
                className={`panel-tab ${rightPanelTab === "terminal" ? "active" : ""}`}
                onClick={() => setRightPanelTab("terminal")}
              >
                Terminal
              </button>
              <button
                className={`panel-tab ${rightPanelTab === "files" ? "active" : ""}`}
                onClick={() => setRightPanelTab("files")}
              >
                Files
              </button>
              <button
                className={`panel-tab ${rightPanelTab === "didal" ? "active" : ""}`}
                onClick={() => setRightPanelTab("didal")}
              >
                DiDAL
                {remoteStatus && <span className="tab-dot connected" />}
              </button>
              <button
                className={`panel-tab ${rightPanelTab === "info" ? "active" : ""}`}
                onClick={() => setRightPanelTab("info")}
              >
                Info
              </button>
            </div>
            <div className="content">
              {rightPanelTab === "output" && (
                <RenderPreview messages={messages} streamingContent={streamingContent} isLoading={isLoading} didalStages={didalStages} />
              )}
              {rightPanelTab === "terminal" && (
                <div className="terminal-panel">
                  <iframe
                    src="http://localhost:8001"
                    title="Local Terminal"
                    className="terminal-iframe"
                    sandbox="allow-scripts allow-same-origin allow-forms"
                  />
                  <div className="terminal-fallback">
                    <p>Terminal runs on <code>localhost:8001</code> via ttyd.</p>
                    <p>Start with: <code>bash emily-start.sh</code> (includes terminal container).</p>
                    <p>Or manually: <code>docker run -d --name ecoseek-terminal -p 8001:7681 tsl0922/ttyd:latest bash</code></p>
                  </div>
                </div>
              )}
              {rightPanelTab === "files" && (
                <FilesPanel />
              )}
              {rightPanelTab === "didal" && (
                <DiDALPanel
                  messages={messages}
                  remoteStatus={remoteStatus}
                  isOnline={isOnline}
                  didalExchanges={didalExchanges}
                  activeToolCalls={activeToolCalls}
                  lastClassification={lastClassification}
                  lastProtocolStages={lastProtocolStages}
                  lastTraceId={lastTraceId}
                  lastJudgeResult={lastJudgeResult}
                />
              )}
              {rightPanelTab === "info" && (
              <div className="info-panel">
                <div className="info-section">
                  <h3>Emily Local</h3>
                  <div className="info-row">
                    <span className="info-label">Endpoint</span>
                    <span className="info-value">{CHAT_URL}</span>
                  </div>
                  <div className="info-row">
                    <span className="info-label">Status</span>
                    <span
                      className={`info-value ${
                        isOnline ? "text-success" : "text-error"
                      }`}
                    >
                      {isOnline ? "Connected" : "Disconnected"}
                    </span>
                  </div>
                </div>

                <div className="info-section">
                  <h3>Hermes Beta (reumanlab)</h3>
                  <div className="info-row">
                    <span className="info-label">Endpoint</span>
                    <span className="info-value">{HERMES_REMOTE_URL}</span>
                  </div>
                  <div className="info-row">
                    <span className="info-label">Status</span>
                    <span
                      className={`info-value ${
                        remoteStatus ? "text-success" : "text-error"
                      }`}
                    >
                      {remoteStatus ? "Connected" : "Disconnected"}
                    </span>
                  </div>
                  {remoteStatus && (
                    <div className="info-row">
                      <span className="info-label">Platform</span>
                      <span className="info-value">
                        {remoteStatus.platform || "hermes-agent"}
                      </span>
                    </div>
                  )}
                  <div className="info-row">
                    <span className="info-label">DiDAL</span>
                    <span className={`info-value ${remoteStatus ? "text-success" : "text-muted"}`}>
                      {remoteStatus ? "Protocol v2 Active" : "Unavailable"}
                    </span>
                  </div>
                  {remoteStatus && (
                    <div className="info-row">
                      <span className="info-label">Tools</span>
                      <span className="info-value info-tools">
                        16 tools: DiDAL, LACS, Web Search, PDF Upload, R Compute, Niche Model, EcoAgent...
                      </span>
                    </div>
                  )}
                  <div className="info-row">
                    <span className="info-label">Phoenix</span>
                    <span className={`info-value ${lastTraceId ? "text-success" : "text-muted"}`}>
                      {lastTraceId ? `Tracing (${lastTraceId.slice(0, 8)}…)` : "Not connected"}
                    </span>
                  </div>
                </div>

                <div className="info-section">
                  <h3>Auth</h3>
                  <div className="info-row">
                    <span className="info-label">Broker</span>
                    <span className="info-value">{BROKER_URL}</span>
                  </div>
                  <div className="info-row">
                    <span className="info-label">Mode</span>
                    <span className="info-value">
                      {IS_LOCAL_EMILY ? "Emily Local + Hermes Remote" : "Emily Remote"}
                    </span>
                  </div>
                </div>

                <div className="info-section">
                  <h3>User</h3>
                  <div className="info-row">
                    <span className="info-label">Login</span>
                    <span className="info-value">{user.login}</span>
                  </div>
                  {user.name && (
                    <div className="info-row">
                      <span className="info-label">Name</span>
                      <span className="info-value">{user.name}</span>
                    </div>
                  )}
                  {user.email && (
                    <div className="info-row">
                      <span className="info-label">Email</span>
                      <span className="info-value">{user.email}</span>
                    </div>
                  )}
                </div>

                {lastHermesTrace && (
                  <div className="info-section">
                    <h3>Hermes Trace</h3>
                    {lastHermesTrace.agent_loop && (
                      <>
                        <div className="info-row">
                          <span className="info-label">Iterations</span>
                          <span className="info-value">{lastHermesTrace.agent_loop.iterations}</span>
                        </div>
                        <div className="info-row">
                          <span className="info-label">Total</span>
                          <span className="info-value">{lastHermesTrace.agent_loop.total_ms}ms</span>
                        </div>
                        {lastHermesTrace.agent_loop.llm_calls?.length > 0 && (
                          <div className="info-row">
                            <span className="info-label">LLM Calls</span>
                            <span className="info-value">{lastHermesTrace.agent_loop.llm_calls.length}</span>
                          </div>
                        )}
                        {lastHermesTrace.agent_loop.tool_calls?.length > 0 && (
                          <div className="info-row">
                            <span className="info-label">Tools</span>
                            <span className="info-value info-tools">
                              {lastHermesTrace.agent_loop.tool_calls.map(tc => tc.name).join(", ")}
                            </span>
                          </div>
                        )}
                      </>
                    )}
                    {lastHermesTrace.gateway && (
                      <div className="info-row">
                        <span className="info-label">Gateway</span>
                        <span className="info-value">{lastHermesTrace.gateway.version || "active"}</span>
                      </div>
                    )}
                  </div>
                )}

                {error && (
                  <div className="info-section error-section">
                    <h3>Last Error</h3>
                    <p className="error-text">{error}</p>
                  </div>
                )}

                <div className="info-section">
                  <h3>About Emily</h3>
                  <p className="info-text">
                    Emily is Alpha in the DiDAL (Dialectical Dual-Agent Loop)
                    system. She plans and designs ecological analyses locally,
                    then delegates heavy computation to Hermes Beta on reumanlab
                    for execution on the KU HPC cluster (A100/MI210 GPUs).
                  </p>
                  <p className="info-text" style={{ marginTop: '8px', fontSize: '0.8em', opacity: 0.7 }}>
                    EcoSeek is built on a fork of AgenticSeek. We gratefully
                    acknowledge the AgenticSeek project and contributors.
                  </p>
                </div>
              </div>
              )}
            </div>
          </div>
        </ResizableLayout>
      </main>
    </div>
  );
}

export default App;

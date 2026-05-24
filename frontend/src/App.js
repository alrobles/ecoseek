import React, { useState, useEffect, useRef, useCallback } from "react";
import ReactMarkdown from "react-markdown";
import remarkMath from "remark-math";
import rehypeKatex from "rehype-katex";
import "katex/dist/katex.min.css";
import "./App.css";
import { ThemeToggle } from "./components/ThemeToggle";
import { ResizableLayout } from "./components/ResizableLayout";
import { CodeBlock } from "./components/CodeBlock";
import { RenderPreview, DiDALPanel } from "./components/RenderPreview";
import { ReactComponent as EcoSeekLogo } from "./ecoseek-logo.svg";
import emilyAvatar from "./emily-avatar.png";
import { useAuth } from "./contexts/AuthContext";
import { chatCompletion, checkHealth, checkRemoteHealth, BROKER_URL, CHAT_URL, IS_LOCAL_EMILY, HERMES_REMOTE_URL } from "./api/broker";

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
  const [rightPanelTab, setRightPanelTab] = useState("preview");
  const messagesEndRef = useRef(null);

  const currentTheme = document.documentElement.getAttribute("data-theme") || "dark";

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

  const handleSubmit = useCallback(
    async (e) => {
      e.preventDefault();
      if (!query.trim() || isLoading) return;

      const userMsg = { type: "user", content: query };
      setMessages((prev) => [...prev, userMsg]);
      setIsLoading(true);
      setError(null);
      setQuery("");

      // Build conversation context (last 20 messages)
      const history = [...messages, userMsg]
        .filter((m) => m.type === "user" || m.type === "agent")
        .slice(-20)
        .map((m) => ({
          role: m.type === "user" ? "user" : "assistant",
          content: m.content,
        }));

      try {
        const data = await chatCompletion(history);
        const choice = data.choices?.[0];
        const content = choice?.message?.content || "";
        const reasoning = choice?.message?.reasoning_content || null;

        setMessages((prev) => [
          ...prev,
          {
            type: "agent",
            content,
            reasoning,
            agentName: data.model || "Hermes",
            finishReason: choice?.finish_reason,
          },
        ]);
        scrollToBottom();
      } catch (err) {
        console.error("Chat error:", err);
        const errMsg = err.message || "Failed to get response";
        setError(errMsg);
        setMessages((prev) => [
          ...prev,
          { type: "error", content: `Error: ${errMsg}` },
        ]);
      } finally {
        setIsLoading(false);
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
                    <div className="message-content">
                      <ReactMarkdown
                        remarkPlugins={[remarkMath]}
                        rehypePlugins={[rehypeKatex]}
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
                    </div>
                  </div>
                ))
              )}
              <div ref={messagesEndRef} />
            </div>

            {isLoading && (
              <div className="loading-animation">
                <img src={emilyAvatar} alt="Emily" className="emily-avatar" />
                Emily is thinking...
              </div>
            )}

            <form onSubmit={handleSubmit} className="input-form">
              <input
                type="text"
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                placeholder="Ask Emily about ecology..."
                disabled={isLoading}
              />
              <div className="action-buttons">
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
            </form>
          </div>

          <div className="computer-section">
            <div className="panel-tabs">
              <button
                className={`panel-tab ${rightPanelTab === "preview" ? "active" : ""}`}
                onClick={() => setRightPanelTab("preview")}
              >
                Preview
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
              {rightPanelTab === "preview" && (
                <RenderPreview messages={messages} />
              )}
              {rightPanelTab === "didal" && (
                <DiDALPanel
                  messages={messages}
                  remoteStatus={remoteStatus}
                  isOnline={isOnline}
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
                      {remoteStatus ? "Phase 2 Active" : "Unavailable"}
                    </span>
                  </div>
                  {remoteStatus && (
                    <div className="info-row">
                      <span className="info-label">Tools</span>
                      <span className="info-value info-tools">
                        eco_analyze, ku_hpc, escalate_remote, dialectical_exchange
                      </span>
                    </div>
                  )}
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

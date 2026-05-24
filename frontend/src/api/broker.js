/**
 * Broker API client — talks to AgenticPlug broker or Emily local agent.
 *
 * When REACT_APP_BROKER_URL points to a local Emily agent (e.g. http://localhost:8642),
 * auth is handled by the Emily API key instead of GitHub OAuth.
 * When pointing to broker.ecoseek.org, auth uses GitHub OAuth sessions.
 */

const BROKER_URL =
  process.env.REACT_APP_BROKER_URL || "https://broker.ecoseek.org";

/**
 * Detect whether we're talking to a local Emily agent vs the remote broker.
 * Local Emily doesn't need GitHub OAuth — it uses a simple API key.
 */
const IS_LOCAL_EMILY =
  BROKER_URL.includes("localhost") || BROKER_URL.includes("127.0.0.1");

// ── Session helpers ────────────────────────────────────────────────────

const SESSION_KEY = "ecoseek_session";

export function getSession() {
  try {
    const raw = localStorage.getItem(SESSION_KEY);
    return raw ? JSON.parse(raw) : null;
  } catch {
    return null;
  }
}

export function saveSession(sessionId, user) {
  localStorage.setItem(
    SESSION_KEY,
    JSON.stringify({ session_id: sessionId, user, broker_url: BROKER_URL })
  );
}

export function clearSession() {
  localStorage.removeItem(SESSION_KEY);
}

export function getSessionId() {
  return getSession()?.session_id || null;
}

// ── Auth ───────────────────────────────────────────────────────────────

const LOCAL_EMILY_KEY = process.env.REACT_APP_EMILY_KEY || "emily-local-key";

/**
 * Start GitHub OAuth — redirect the browser to the broker's OAuth endpoint.
 * For local Emily, skip OAuth and create a local session directly.
 */
export function startLogin(returnTo) {
  if (IS_LOCAL_EMILY) {
    saveSession(LOCAL_EMILY_KEY, { login: "local", name: "Local User" });
    window.location.href = returnTo || window.location.origin;
    return;
  }
  const url = `${BROKER_URL}/auth/github/start?return_to=${encodeURIComponent(
    returnTo || window.location.origin + "/callback"
  )}`;
  window.location.href = url;
}

/**
 * Fetch current user identity via GET /v1/me.
 * For local Emily, returns a local identity without network call.
 */
export async function fetchMe() {
  const sid = getSessionId();
  if (!sid) return null;
  if (IS_LOCAL_EMILY) {
    return { login: "local", name: "Local User", mode: "emily-local" };
  }
  try {
    const res = await fetch(`${BROKER_URL}/v1/me`, {
      headers: { Authorization: `Bearer ${sid}` },
    });
    if (!res.ok) return null;
    return await res.json();
  } catch {
    return null;
  }
}

// ── Health ──────────────────────────────────────────────────────────────

export async function checkHealth() {
  try {
    const endpoint = IS_LOCAL_EMILY
      ? `${BROKER_URL}/health`
      : `${BROKER_URL}/healthz`;
    const res = await fetch(endpoint);
    return res.ok;
  } catch {
    return false;
  }
}

// ── Emily persona ──────────────────────────────────────────────────────

const EMILY_SYSTEM_PROMPT = `You are Emily, an expert ecological scientist and AI assistant for EcoSeek.

Your specialties include:
- Ecological niche modeling and species distribution models (SDMs)
- Biogeography and macroecology
- GBIF biodiversity data analysis
- Phylogenetic analysis and comparative methods
- Population ecology and stochastic demography
- R programming for ecological analysis (vegan, terra, dismo, ape, picante)
- Spatial analysis and GIS

Personality:
- You are warm, knowledgeable, and passionate about biodiversity.
- You explain complex ecological concepts clearly and accessibly.
- You always suggest reproducible workflows and cite data sources.
- When appropriate, you provide R or Python code snippets.
- You encourage best practices in open science and data provenance.
- You know about GBIF, WoRMS, IUCN, and other biodiversity databases.

Always introduce yourself as Emily on the first interaction. Keep responses focused and scientifically rigorous.`;

// ── Chat completions ───────────────────────────────────────────────────

/**
 * Send a chat completion request.
 *
 * - Local Emily: talks directly to Hermes gateway (personality is in config.yaml)
 * - Remote broker: prepends Emily system prompt (broker forwards to remote Hermes)
 *
 * @param {Array} messages  OpenAI-style messages array
 * @param {string} model    Model name (default: openclaw/main)
 * @returns {Promise<object>} Parsed response body
 */
export async function chatCompletion(messages, model = "openclaw/main") {
  const sid = getSessionId();
  if (!sid) throw new Error("Not logged in");

  // Local Emily has personality baked into Hermes config — no need for system prompt.
  // Remote broker needs the system prompt injected by the frontend.
  const fullMessages = IS_LOCAL_EMILY
    ? messages
    : [{ role: "system", content: EMILY_SYSTEM_PROMPT }, ...messages];

  const res = await fetch(`${BROKER_URL}/v1/chat/completions`, {
    method: "POST",
    headers: {
      Authorization: `Bearer ${sid}`,
      "Content-Type": "application/json",
    },
    body: JSON.stringify({ model, messages: fullMessages }),
  });

  const body = await res.json();
  if (!res.ok) {
    const msg = body?.error?.message || body?.error || `HTTP ${res.status}`;
    throw new Error(msg);
  }
  return body;
}

export { BROKER_URL, IS_LOCAL_EMILY };

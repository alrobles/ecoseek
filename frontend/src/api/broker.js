/**
 * Broker API client — talks to AgenticPlug broker (broker.ecoseek.org).
 *
 * Handles session-based auth and chat completions via the Hermes gateway.
 */

const BROKER_URL =
  process.env.REACT_APP_BROKER_URL || "https://broker.ecoseek.org";

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

/**
 * Start GitHub OAuth — redirect the browser to the broker's OAuth endpoint.
 * After auth, the broker redirects back to `returnTo` with ?session_id=...
 */
export function startLogin(returnTo) {
  const url = `${BROKER_URL}/auth/github/start?return_to=${encodeURIComponent(
    returnTo || window.location.origin + "/callback"
  )}`;
  window.location.href = url;
}

/**
 * Fetch current user identity via GET /v1/me.
 */
export async function fetchMe() {
  const sid = getSessionId();
  if (!sid) return null;
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
    const res = await fetch(`${BROKER_URL}/healthz`);
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
 * Send a chat completion request through the broker to Hermes.
 * Automatically prepends Emily's system prompt.
 *
 * @param {Array} messages  OpenAI-style messages array
 * @param {string} model    Model name (default: openclaw/main)
 * @returns {Promise<object>} Parsed response body
 */
export async function chatCompletion(messages, model = "openclaw/main") {
  const sid = getSessionId();
  if (!sid) throw new Error("Not logged in");

  const fullMessages = [
    { role: "system", content: EMILY_SYSTEM_PROMPT },
    ...messages,
  ];

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

export { BROKER_URL };

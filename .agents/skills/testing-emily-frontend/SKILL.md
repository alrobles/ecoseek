---
name: testing-emily-frontend
description: Test the Emily frontend end-to-end — health check, login, avatar, math rendering, code blocks, auxiliary panel (Preview/Terminal/Files/DiDAL/Info), theme toggle, and CORS. Use when verifying Emily Docker networking, API server, frontend branding, rich content rendering, or UI changes.
---

# Testing Emily Frontend

## Prerequisites

- Emily Docker image built from `emily/Dockerfile` (includes hermes-agent + aiohttp)
- Docker running on the machine
- Frontend Docker image built from `frontend/Dockerfile`

## Devin Secrets Needed

- None required for basic frontend testing
- `DEEPSEEK_API_KEY` needed only if testing actual chat responses (can mock via fetch override for avatar/UI tests)
- GitHub OAuth credentials needed only if testing real login flow (can bypass via Playwright CDP)

## Setup Steps

### 1. Build & Run via emily-start.sh (Recommended)

```bash
cd /home/ubuntu/repos/ecoseek
DEEPSEEK_API_KEY=sk-your-key bash emily-start.sh
```

This builds both Docker images, generates a shared API key, and starts emily-local + ecoseek-frontend + ecoseek-terminal containers.

**Known issue:** The ttyd terminal container may crash if `emily-start.sh` passes `bash` instead of `ttyd -W bash` as the entrypoint. If `docker ps` shows `ecoseek-terminal` in `Restarting` state, fix manually:
```bash
docker stop ecoseek-terminal && docker rm ecoseek-terminal
docker run -d --name ecoseek-terminal -p 127.0.0.1:8000:7681 \
  -v "$(pwd)/workspace:/workspace" tsl0922/ttyd:latest ttyd -W bash
```

### 2. Manual Build (Alternative)

```bash
# Build Emily
docker build -t emily-local emily/

# Get or set API key
EMILY_KEY=$(openssl rand -hex 16)

# Run Emily
docker run -d --name emily-local \
  -p 127.0.0.1:8642:8642 \
  -e "API_SERVER_KEY=$EMILY_KEY" \
  -e "API_SERVER_CORS_ORIGINS=http://localhost:3001,http://localhost:4000" \
  emily-local

# Build frontend (REACT_APP_* vars must be set at BUILD time for CRA)
docker build -t ecoseek-frontend \
  --build-arg REACT_APP_EMILY_URL=http://localhost:8642 \
  --build-arg "REACT_APP_EMILY_KEY=$EMILY_KEY" \
  -f frontend/Dockerfile frontend/

# Run frontend
docker run -d --name ecoseek-frontend -p 127.0.0.1:4000:80 ecoseek-frontend
```

### 3. Verify Health Check

```bash
curl -s http://localhost:8642/health
# Expected: {"status":"ok","platform":"hermes-agent"}

curl -s -o /dev/null -w "%{http_code}" http://localhost:4000/
# Expected: 200
```

## Auth Bypass for Testing

GitHub OAuth requires valid broker.ecoseek.org session. For testing without real credentials, use **Playwright CDP fetch override**:

```python
import asyncio
from playwright.async_api import async_playwright

async def main():
    async with async_playwright() as p:
        browser = await p.chromium.connect_over_cdp("http://localhost:29229")
        context = browser.contexts[0]
        page = [pg for pg in context.pages if "localhost:4000" in pg.url][0]

        # Override fetch to fake auth + optionally mock chat responses
        await page.evaluate("""() => {
            const _origFetch = window.fetch;
            window.fetch = async function(...args) {
                const url = typeof args[0] === 'string' ? args[0] : args[0]?.url;
                if (url && url.includes('/v1/me')) {
                    return new Response(JSON.stringify({
                        user: { login: "test-user", avatarUrl: "https://avatars.githubusercontent.com/u/1?v=4" }
                    }), { status: 200, headers: { 'Content-Type': 'application/json' } });
                }
                if (url && url.includes('/v1/chat/completions')) {
                    return new Response(JSON.stringify({
                        id: "fake", object: "chat.completion", model: "hermes",
                        choices: [{ index: 0, message: { role: "assistant",
                            content: "Hello! I'm Emily, your ecological research assistant.",
                            reasoning_content: "User greeted me." }, finish_reason: "stop" }],
                        usage: { prompt_tokens: 100, completion_tokens: 50, total_tokens: 150 }
                    }), { status: 200, headers: { 'Content-Type': 'application/json' } });
                }
                return _origFetch.apply(this, args);
            };
        }""")

        # Set fake session + reload
        await page.evaluate("""() => {
            localStorage.setItem('ecoseek_session', JSON.stringify({
                session_id: 'fake-test-session', user: null,
                broker_url: 'https://broker.ecoseek.org'
            }));
        }""")
        await page.reload(wait_until="networkidle")

asyncio.run(main())
```

**Key insight:** Playwright route interception (`page.route()`) does NOT persist after the script exits. Use `window.fetch` override via `page.evaluate()` instead — it persists in the page's JS context.

**Better approach for reliable auth bypass:** Use `page.route()` for `/v1/me` interception, then `page.add_init_script()` to inject the fetch override before React loads. This way the override survives page reloads:

```python
# Intercept /v1/me via page.route (works during script lifetime)
await page.route("**/v1/me", lambda route: route.fulfill(
    status=200, content_type="application/json",
    body='{"user":{"login":"test-user","avatarUrl":""}}'
))

# Inject persistent fetch override via addInitScript
await page.add_init_script("""...(your mock JSON)...""")
await page.reload(wait_until="networkidle")
```

**For rich content testing:** Include LaTeX math (`$$...$$`, `$...$`) and fenced code blocks (` ```python `) in mock chat responses to exercise KaTeX rendering and CodeBlock component.

## Test Procedure

### Test 1: Health Check (Shell)
```bash
curl -s -w "\nHTTP_CODE:%{http_code}" http://localhost:8642/health
```
- Pass: HTTP 200 + `{"status":"ok","platform":"hermes-agent"}`

### Test 2: Login Screen (Browser — no auth needed)
- Open `http://localhost:4000`
- Pass: EcoSeek logo → title → **Emily avatar (96px circular)** → subtitle → GitHub button → footer
- Footer should read "Emily Local · GitHub Auth · Hermes" when `REACT_APP_EMILY_URL` is set
- Avatar should have transparent background, work on the dark login card

### Test 3: Status Indicator (Browser — auth required)
- Use Playwright auth bypass above, then check header
- Pass: Green dot + "EMILY LOCAL" badge in header

### Test 4: Info Panel — Three Sections (Browser — auth required)
- After auth bypass, check the right-side Information panel
- Pass: Three sections visible:
  - **EMILY LOCAL** — Endpoint=localhost:8642, Status=Connected (green)
  - **HERMES REMOTE (REUMANLAB)** — Endpoint=hermes.ecoseek.org, Status (see CORS note)
  - **AUTH** — Broker=broker.ecoseek.org, Mode=Emily Local + Hermes Remote

### Test 5: Emily Avatar on Agent Messages (Browser — auth + mock chat)
- Use the full fetch override (including chat mock) from the auth bypass section
- Send a message in the chat input
- Pass: Agent message shows Emily avatar (28px circular) + "Emily" label + Reasoning toggle

### Test 6: Emily Avatar on Loading Indicator (Browser)
- Send a message (without chat mock, so it hits the real backend which takes time)
- Pass: Loading area shows Emily avatar (28px) + "Emily is thinking..." text

### Test 7: Favicon (Browser)
- Check the browser tab icon
- Pass: Green EcoSeek search/leaf SVG icon, tab title "EcoSeek"

### Test 8: Theme Toggle (Browser — auth required)
- Click theme toggle button in header
- Pass: UI switches between dark/light, avatar remains visible and clean on both

### Test 9: KaTeX Math Rendering (Browser — auth + mock chat with LaTeX)
- Send message intercepted by mock returning `$$S = k_B \ln \Omega$$` and inline `$\alpha$`
- Pass: Display math renders as centered KaTeX equation (`.katex` elements in DOM), inline math shows Greek letters (not raw `$...$` text)

### Test 10: Code Block + Copy Button (Browser — auth + mock chat with code)
- Mock response includes ` ```python ` fenced code block
- Pass: Code block has "PYTHON" language header, line numbers, syntax highlighting, "Copy" button that changes to "Copied!" with checkmark on click

### Test 11: Preview Panel — Extracted Blocks (Browser — after Test 9/10)
- Click "Preview" tab in right panel
- Pass: Shows extracted Python code block + rendered KaTeX display equation from chat messages

### Test 12: Terminal Tab — ttyd (Browser)
- Click "Terminal" tab
- Pass: iframe loads ttyd web terminal showing bash prompt (dark terminal UI). Fallback text shows `localhost:8000`

### Test 13: Files Tab — Workspace Browser (Browser)
- Place a test file in `./workspace/` before testing, then click "Files" tab
- Pass: Shows file listing with name, size, date. Breadcrumb shows "workspace". Refresh button visible.
- If workspace mount is broken, shows error message instead of file list

### Test 14: DiDAL Tab — Status + Tools (Browser)
- Click "DiDAL" tab
- Pass: Alpha (Emily) shows "Online" green, Beta (Hermes) shows status, arrow connector, "DiDAL Phase 3" description, 4 remote tool chips (eco_analyze, ku_hpc, escalate_remote, dialectical_exchange)

## Workspace Setup for Files Tab

The Files tab reads from `./workspace/` via nginx JSON autoindex at `/workspace/`. Create the directory and add a test file before testing:
```bash
mkdir -p ./workspace
echo "test content" > ./workspace/sample-data.csv
```

Verify the endpoint works:
```bash
curl -s http://localhost:4000/workspace/
# Expected: JSON array with file objects [{"name":"sample-data.csv","type":"file",...}]
```

## Common Gotchas

1. **REACT_APP_* vars are build-time only:** Create React App bakes env vars at webpack compile time. Setting them at container runtime does nothing. Must pass as `--build-arg` when building the Docker image.

2. **CORS on hermes.ecoseek.org:** The Hermes gateway on reumanlab might not serve CORS headers. Browser `fetch()` from localhost will fail with CORS error even though `curl` works. The "Hermes Remote" status will show "Disconnected" in the browser. This is a known limitation — fix requires adding CORS headers to the Hermes gateway config or proxying through Emily local.

3. **CORS on Emily container:** If Emily container was started without `API_SERVER_CORS_ORIGINS` including the frontend port, browser fetches fail. Always include `http://localhost:4000` in CORS origins.

4. **aiohttp missing:** If Dockerfile doesn't install aiohttp, gateway starts but health endpoint never responds. Fix: ensure aiohttp is in pip install.

5. **API server binding:** Must be `0.0.0.0` inside Docker. Default `127.0.0.1` is container loopback only.

6. **Auth bypass approach:** Do NOT try to modify AuthContext.js for testing. Use Playwright CDP + fetch override instead — it's non-destructive and doesn't require code changes.

7. **Playwright route vs fetch override:** `page.route()` only works while the Playwright script is running. For persistent interception, override `window.fetch` via `page.evaluate()`.

8. **Frontend port:** When using Docker (nginx), frontend serves on port 4000 (mapped from 80). When using `npm start` dev server, it's port 3001 (hardcoded in package.json).

9. **ttyd container entrypoint:** The `tsl0922/ttyd:latest` image needs `ttyd -W bash` as the command, not just `bash`. If the container keeps restarting (check `docker ps`), the entrypoint is wrong.

10. **Code block theme in light mode:** The CodeBlock component reads `currentTheme` from `document.documentElement.getAttribute("data-theme")` at render time but may not re-render reactively when theme toggles. Code blocks might keep the dark (oneDark) syntax theme after switching to light mode. Low priority.

11. **Math rendering pipeline:** Chat messages use `remarkMath` + `rehypeKatex` plugins in ReactMarkdown — KaTeX renders directly via the rehype plugin. The `MathBlock`/`MathInline` components (with copy buttons) are only used in the Preview panel's `MathPreview`, not in chat messages.

12. **Health mock for Info/DiDAL panels:** The Info and DiDAL panels poll `/api/hermes-health` (nginx proxy) and local `/health`. If testing without real backends, mock both via `page.add_init_script()` to show "Connected" status.

## Cleanup

```bash
docker stop emily-local ecoseek-frontend ecoseek-terminal 2>/dev/null
docker rm emily-local ecoseek-frontend ecoseek-terminal 2>/dev/null
docker rmi emily-local ecoseek-frontend 2>/dev/null
```

---
name: testing-emily-frontend
description: Test the Emily frontend end-to-end — health check, status indicator, favicon, login screen, and CORS. Use when verifying Emily Docker networking, API server, or frontend branding changes.
---

# Testing Emily Frontend

## Prerequisites

- Emily Docker image built from `emily/Dockerfile` (includes hermes-agent + aiohttp)
- Docker running on the machine
- Node.js available for frontend dev server

## Devin Secrets Needed

- None required for basic frontend testing
- `DEEPSEEK_API_KEY` needed only if testing chat functionality (out of scope for status/branding tests)

## Setup Steps

### 1. Build Emily Docker Image

```bash
cd /home/ubuntu/repos/ecoseek
docker build -t emily-local-test emily/
```

**Known issue:** The Dockerfile does `git clone` from GitHub for hermes-agent. If the repo is private, the build will fail. Workaround: ensure hermes-agent repo is public, or modify the Dockerfile to COPY from a local checkout.

### 2. Run Emily Container

```bash
docker run -d --name emily-test \
  -p 127.0.0.1:8642:8642 \
  -e "API_SERVER_KEY=test-key-12345" \
  -e "API_SERVER_CORS_ORIGINS=http://localhost:3001,http://localhost:4000" \
  emily-local-test
```

**Important:** The CORS origins must include the frontend dev server port. The frontend runs on port **3001** by default (hardcoded in `package.json` via `cross-env PORT=3001`), NOT 4000 even if you pass `PORT=4000` as env var.

### 3. Verify Health Check

```bash
curl -s http://localhost:8642/health
# Expected: {"status":"ok","platform":"hermes-agent"}
```

If this fails:
- Check `docker logs emily-test` for errors
- Common error: `hermes: error: unrecognized arguments: --api-only` means entrypoint.sh uses wrong gateway command
- Common error: `WARNING: aiohttp not installed` means Dockerfile is missing `aiohttp` dependency
- Container restart loop means the gateway command is crashing — check entrypoint.sh

### 4. Start Frontend Dev Server

```bash
cd /home/ubuntu/repos/ecoseek/frontend
REACT_APP_EMILY_URL=http://localhost:8642 \
REACT_APP_EMILY_KEY=test-key-12345 \
REACT_APP_BROKER_URL=https://broker.ecoseek.org \
npm start
```

The `REACT_APP_*` env vars are baked in at webpack compile time (Create React App). They must be set BEFORE `npm start`, not after.

## Test Procedure

### Test 1: Health Check (Shell)
```bash
curl -s -w "\nHTTP_CODE:%{http_code}" http://localhost:8642/health
```
- Pass: HTTP 200 + `{"status":"ok","platform":"hermes-agent"}`

### Test 2: Status Indicator (Browser)
- Open `http://localhost:3001`
- The status indicator only shows when logged in
- **To test without real GitHub OAuth:** Temporarily add a local-test bypass in `AuthContext.js` (check for a special `session_id` value like `'local-test'` and return a fake user). Set `localStorage.setItem('ecoseek_session', JSON.stringify({session_id:'local-test',...}))` in the console, then reload
- Pass: Header shows green dot + "EMILY LOCAL" badge; info panel shows "Connected" in green
- **Remember to revert the auth bypass after testing**

### Test 3: Favicon (Browser)
- Check the browser tab icon at `http://localhost:3001`
- Pass: Green EcoSeek search/leaf SVG icon, tab title "EcoSeek"
- Fail: React default logo or old AgenticSeek icon

### Test 4: Login Screen (Browser)
- Clear localStorage and reload `http://localhost:3001`
- Pass: Footer reads "Emily Local · GitHub Auth · Hermes"
- Fail: Footer reads "Powered by EcoSeek · AgenticPlug · Hermes" (means REACT_APP_EMILY_URL not set)

### Bonus: CORS Verification (Browser Console)
```javascript
fetch('http://localhost:8642/health').then(r=>r.json()).then(d=>console.log(JSON.stringify(d)))
```
- Pass: Returns the health JSON without CORS errors

## Common Gotchas

1. **Frontend port mismatch:** `package.json` hardcodes `PORT=3001` via `cross-env`. Your `PORT=4000` env var gets overridden. Always use 3001 for CORS config.

2. **CORS not set on Emily container:** If the container was started without `API_SERVER_CORS_ORIGINS` including the frontend port, browser fetches will fail with CORS errors even though curl works fine.

3. **aiohttp missing:** If the Dockerfile doesn't install aiohttp, the gateway starts but logs `No adapter available for api_server`. Health endpoint never responds. Fix: add `aiohttp` to pip install in Dockerfile.

4. **API server binding:** Must be `0.0.0.0` inside Docker (set via `API_SERVER_HOST` env var in entrypoint.sh). Default `127.0.0.1` is container loopback only — unreachable from host.

5. **Auth bypass for testing:** The status indicator requires a logged-in user. GitHub OAuth needs broker CORS configured for localhost. For testing, use the temporary AuthContext bypass described above rather than trying to complete the full OAuth flow.

## Cleanup

```bash
docker stop emily-test && docker rm emily-test
# Kill frontend dev server (Ctrl+C in its terminal)
# Revert any temporary auth bypass changes in AuthContext.js
```

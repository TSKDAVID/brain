# Chaster Brain

Standalone backend intelligence layer for Chaster.

## What is included

- FastAPI backend runtime + gateway + orchestration + control APIs
- TypeScript dashboard at `dashboard/` for control and observability
- Per-conversation memory manager (rolling Groq summaries + Redis hot cache)
- LLM-based intent classifier with rules fallback and Redis caching
- Trigram retrieval + token-overlap rerank + FAQ answer cache
- Render deploy configuration (`render.yaml`, `Dockerfile`, `runtime.txt`)
- Supabase migrations for:
  - `knowledge_chunks`
  - `app_configurations`
  - control-plane tables (`brain_runtime_control`, `brain_parameters`, `brain_index_jobs`, `brain_metrics_daily`)
  - `brain_conversation_summaries` (rolling chat memory)

## 1) Apply Supabase migrations

Run from the project that owns the Supabase link (typically `atomic-crm` or this repo if linked):

```bash
npx supabase db push --yes --linked
```

## 2) Run backend API locally

1. Create `.env` from `.env.example`.
   - Set `GROQ_API_KEY`
   - Keep `GROQ_MODEL=llama-3.3-70b-versatile` for answer generation (and memory compression).
   - Optional: `GROQ_INTENT_MODEL` defaults to `openai/gpt-oss-20b` for fast intent routing (tiny JSON).
   - `REDIS_URL` is optional locally — leave it empty to use the in-process shim.
2. Install Python deps:

```bash
python -m pip install -e .[dev]
```

3. Start API:

```bash
uvicorn app.main:app --reload --port 8010
```

## 3) Run dashboard

```bash
cd dashboard
npm install
npm run dev
```

Set `dashboard/.env` with:

```bash
VITE_API_BASE_URL=http://127.0.0.1:8010
```

## Optional one-command dev start (PowerShell)

```powershell
.\scripts\start-dev.ps1
```

## Production hosting on Render

The repo ships a `render.yaml` blueprint that provisions:

- a Python web service running `uvicorn app.main:app`
- a managed Redis (Render Key-Value) instance for hot caches and memory

### Deploy steps

1. Push this repo to GitHub.
2. In the Render dashboard, click **New + → Blueprint** and point it at the repo.
3. Render parses `render.yaml`, creates the web service + Redis, and asks you to set the secret env vars (marked `sync: false`):
   - `SUPABASE_URL`, `SUPABASE_SERVICE_ROLE_KEY`
   - `SUPABASE_JWT_ISSUER`, `SUPABASE_JWKS_URL`
   - `GROQ_API_KEY`
   - `CORS_ALLOW_ORIGINS` — comma-separated list including your GitHub Pages URL, e.g.
     `https://<your-user>.github.io,https://<your-user>.github.io/atomic-crm`
4. Apply the Supabase migrations against the same project (`npx supabase db push --linked`).
5. Wait for the deploy to go green, then test:

```bash
curl https://<your-service>.onrender.com/health
```

### Production hardening checklist

- Leave `CHASTER_BRAIN_DEV_GATEWAY_SECRET` unset in production.
- Restrict `CORS_ALLOW_ORIGINS` to your GitHub Pages origin (and any custom domain you own); avoid `*`.
- Increase `WIDGET_SESSION_TTL_SECONDS` only if your widget needs longer continuity (default 30 minutes).
- Watch the `/health` endpoint and Render Redis metrics after the first day.

### Docker (optional)

A `Dockerfile` is included for portability:

```bash
docker build -t chaster-brain .
docker run --rm -p 8010:8010 --env-file .env chaster-brain
```

## Public Widget Compatibility API

The public chat widget now uses compatibility endpoints layered on top of the existing gateway/orchestrator flow:

- `POST /v1/handshake`
  - Validates `app_id` + `tenant_id` binding and origin allowlist via `app_configurations`
  - Verifies request HMAC (`X-Signature`, `X-Timestamp`, `X-Nonce`)
  - Issues a short-lived widget session JWT
  - Accepts optional `conversation_id` to **resume** an existing chat without creating a new conversation row
- `POST /v1/process`
  - Requires widget session bearer token from handshake
  - Re-validates request HMAC + replay/origin checks
  - Loads conversation summary + recent verbatim turns from the memory manager and threads them into the LLM prompt
  - Routes through existing AI orchestration and returns normalized response with `sender_type` and `ai_handling`
- `POST /v1/widget/reset`
  - Drops cached summaries / hot turns for the conversation in the bearer token
  - Used by the widget's "New chat" button before re-handshaking
- `GET /v1/widget/messages`
  - Returns the last N persisted messages for the conversation in the bearer token
  - Used by the widget on resume so chat history re-renders from a trusted source

### Widget session env vars

Add these to `chaster-brain/.env`:

```bash
WIDGET_SESSION_SECRET=change-this-in-production
WIDGET_SESSION_TTL_SECONDS=900
REDIS_URL=
```

### Script embed flow (high level)

1. Host page loads `chaster-widget` bundle.
2. Host backend computes per-request HMAC headers (never expose shared secret in browser).
3. On first load: widget calls `/v1/handshake` and stores `session_token` + `conversation_id` in `localStorage`.
4. On a refresh: widget reads `localStorage`, calls `/v1/handshake` with the saved `conversation_id` to resume, then `/v1/widget/messages` to re-render history.
5. Widget sends user text to `/v1/process` with session token + signed headers.
6. Clicking **New chat** clears `localStorage`, calls `/v1/widget/reset`, and re-handshakes for a brand new conversation.

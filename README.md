# Chaster Brain

Standalone backend intelligence layer for Chaster.

## What is included

- FastAPI backend runtime + gateway + orchestration + control APIs
- TypeScript dashboard at `dashboard/` for control and observability
- Supabase migrations for:
  - `knowledge_chunks`
  - `app_configurations`
  - control-plane tables (`brain_runtime_control`, `brain_parameters`, `brain_index_jobs`, `brain_metrics_daily`)

## 1) Apply Supabase migrations

Run from `atomic-crm`:

```bash
npx supabase db push --yes --linked
```

## 2) Run backend API

1. Create `.env` from `.env.example`.
   - Set `GROQ_API_KEY`
   - Keep `GROQ_MODEL=llama3-70b-8192` (Llama 3 70B)
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

## Public Widget Compatibility API

The public chat widget now uses compatibility endpoints layered on top of the existing gateway/orchestrator flow:

- `POST /v1/handshake`
  - Validates `app_id` + `tenant_id` binding and origin allowlist via `app_configurations`
  - Verifies request HMAC (`X-Signature`, `X-Timestamp`, `X-Nonce`)
  - Issues a short-lived widget session JWT
- `POST /v1/process`
  - Requires widget session bearer token from handshake
  - Re-validates request HMAC + replay/origin checks
  - Routes through existing AI orchestration and returns normalized response with `sender_type` and `ai_handling`

### Widget session env vars

Add these to `chaster-brain/.env`:

```bash
WIDGET_SESSION_SECRET=change-this-in-production
WIDGET_SESSION_TTL_SECONDS=900
```

### Script embed flow (high level)

1. Host page loads `chaster-widget` bundle.
2. Host backend computes per-request HMAC headers (never expose shared secret in browser).
3. Widget calls `/v1/handshake` and receives session token.
4. Widget sends user text to `/v1/process` with session token + signed headers.

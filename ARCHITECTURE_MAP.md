# Chaster Brain Architecture Map

This file is a practical, factual map of how the current `chaster-brain` system works and where to change behavior safely.

## 1) End-to-End Request Flow

```mermaid
flowchart TD
A[Dashboard Simulator / Widget] --> B[/v1/gateway/message in app/main.py]
B --> C[Security checks in app/gateway/service.py]
C --> D[LangGraph orchestrator in app/orchestrator/graph.py]
D --> E1[FAQ path in app/orchestrator/nodes.py]
D --> E2[Personal path in app/orchestrator/nodes.py]
E1 --> F1[Retrieve FAQ chunks via app/rag/retriever.py]
E2 --> F2[MCP stub via app/mcp/client.py]
F1 --> G[Generate response via Groq in app/orchestrator/llm.py]
F2 --> G
G --> H[Confidence node + threshold gate in app/main.py]
H --> I[Response back to dashboard/widget]
```

## 2) Core Files and Responsibilities

- `app/main.py`
  - FastAPI entrypoint and route definitions.
  - Control endpoints (runtime/params/index/stats).
  - Gateway endpoint (`/v1/gateway/message`) orchestration and final response gating.

- `app/gateway/service.py`
  - Request security validation: JWT (or dev-secret bypass), signature, timestamp, nonce, origin, tenant checks.

- `app/orchestrator/graph.py`
  - LangGraph topology: intent node -> faq/personal node -> confidence node.

- `app/orchestrator/nodes.py`
  - Intent classifier.
  - FAQ path behavior.
  - Personal request path behavior.
  - Confidence calculation.

- `app/orchestrator/llm.py`
  - Groq chat completion call, prompting strategy, and LLM failure fallback.

- `app/rag/retriever.py`
  - FAQ chunk retrieval logic (currently Postgres trigram RPC path + fallback row fetch).

- `app/indexing/pipeline.py`
  - Text indexing pipeline from dashboard input into `knowledge_base_documents` and `knowledge_chunks`.

- `app/db/client.py`
  - Supabase REST helper methods (select, insert, upsert, patch, count, rpc).

- `dashboard/src/App.tsx`
  - Dashboard UI: tenant load, params, runtime, indexing form, simulator.

- `dashboard/src/api.ts`
  - Browser API client to backend endpoints.

- `atomic-crm/supabase/migrations/*.sql`
  - Schema and DB-side behavior (tables, functions, indexes, RLS, RPC functions).

## 3) Data Model Mental Model

- `knowledge_base_documents`
  - Logical uploaded/indexed document records.
  - Metadata level object.

- `knowledge_chunks`
  - Retrieval units used for FAQ answers.
  - `chunk_text` is what retrieval uses.

- `brain_index_jobs`
  - Lifecycle of indexing submissions (queued/processing/completed/failed).

- `brain_parameters`
  - Tenant-level AI tuning (`confidence_threshold`, `max_context_chunks`, `response_tone`, `mcp_enabled`).

- `brain_runtime_control`
  - Per-tenant start/stop toggle and mode.

- `brain_metrics_daily`
  - Per-day aggregate usage and quality counters.

## 4) "Change X" -> Where to Edit

- Change model/provider behavior:
  - `app/orchestrator/llm.py`
  - `app/config.py`
  - `.env`

- Change intent routing rules:
  - `app/orchestrator/nodes.py` (`intent_classifier`)

- Improve FAQ retrieval quality:
  - `app/rag/retriever.py`
  - relevant SQL migration/RPC in `atomic-crm/supabase/migrations`

- Change confidence behavior:
  - `app/orchestrator/nodes.py` (`confidence_node`)
  - `app/main.py` (final threshold override behavior)

- Change security policy:
  - `app/main.py` (header parsing / dev-secret path)
  - `app/gateway/service.py` (core validation)

- Change dashboard UX:
  - `dashboard/src/App.tsx`
  - `dashboard/src/api.ts`

## 5) Debug Playbook

When behavior looks wrong, debug in this order:

1. Gateway result shape in dashboard:
   - Check `intent`, `confidence`, `sources`, `response`.

2. LLM reachability:
   - Validate `GROQ_API_KEY` and `GROQ_MODEL` in `.env`.
   - If fallback text appears, inspect backend logs for LLM call failures.

3. Retrieval quality:
   - Confirm expected chunks exist in `knowledge_chunks` for the tenant.
   - Confirm required DB migrations are applied and RPC functions exist.

4. Security issues:
   - Verify JWT or dev-secret flow headers.
   - Verify signature/timestamp/nonce/origin values are present and valid.

5. Threshold overrides:
   - Check tenant `confidence_threshold` in dashboard.
   - Confirm final low-confidence guard behavior in `app/main.py`.

## 6) Practical Development Loop (Stay on Track)

Use this loop for every behavior change:

1. Define one expected outcome.
2. Identify layer (security, retrieval, routing, LLM, confidence, UI).
3. Change one file/concern first.
4. Run 3-5 fixed simulator prompts.
5. Compare outputs (`intent`, `confidence`, `sources`, `response`) before/after.
6. Record a short note: what changed and why.

## 7) Current System Behavior Snapshot

- Gateway requests are security-validated before orchestration.
- FAQ answers use indexed chunk retrieval and then Groq for final wording.
- Personal/account-like queries route through personal path logic.
- Confidence can modify final response behavior depending on intent and threshold.
- Dashboard lets you control runtime, params, indexing input, and simulation traffic.

Keep this doc updated whenever core flow, routing rules, retrieval logic, or confidence policy changes.

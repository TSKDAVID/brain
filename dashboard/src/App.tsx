import { FormEvent, useEffect, useState } from "react";
import { api, GatewaySimResponse, Parameters, RuntimeControl, Stats } from "./api";

const defaultStats: Stats = {
  tenant_id: "",
  knowledge_chunks: 0,
  index_jobs_total: 0,
  index_jobs_pending: 0,
  support_cases_open: 0,
  conversations_total: 0,
  ai_requests_today: 0,
  low_confidence_today: 0
};

const defaultParams: Parameters = {
  tenant_id: "",
  confidence_threshold: 0.6,
  max_context_chunks: 8,
  response_tone: "professional",
  mcp_enabled: true
};

export function App() {
  const [tenantId, setTenantId] = useState("");
  const [runtime, setRuntime] = useState<RuntimeControl | null>(null);
  const [params, setParams] = useState<Parameters>(defaultParams);
  const [stats, setStats] = useState<Stats>(defaultStats);
  const [indexDocTitle, setIndexDocTitle] = useState("Support FAQ");
  const [indexFaqText, setIndexFaqText] = useState("");
  const [statusText, setStatusText] = useState("Ready");
  const [loading, setLoading] = useState(false);
  const [simAppId, setSimAppId] = useState("app_demo_001");
  const [simOrigin, setSimOrigin] = useState("http://localhost:5174");
  const [simJwt, setSimJwt] = useState("");
  const [simDevSecret, setSimDevSecret] = useState(
    () => (import.meta.env.VITE_CHASTER_DEV_GATEWAY_SECRET as string | undefined) || ""
  );
  const [simHmacSecret, setSimHmacSecret] = useState("");
  const [simMessage, setSimMessage] = useState("Hi, what are your support hours?");
  const [simResult, setSimResult] = useState<GatewaySimResponse | null>(null);
  const [simLatencyMs, setSimLatencyMs] = useState<number | null>(null);
  const [simError, setSimError] = useState("");

  async function hmacSha256Hex(secret: string, input: string): Promise<string> {
    const enc = new TextEncoder();
    const key = await crypto.subtle.importKey(
      "raw",
      enc.encode(secret),
      { name: "HMAC", hash: "SHA-256" },
      false,
      ["sign"]
    );
    const signature = await crypto.subtle.sign("HMAC", key, enc.encode(input));
    return Array.from(new Uint8Array(signature))
      .map((b) => b.toString(16).padStart(2, "0"))
      .join("");
  }

  async function runSimulation(message: string) {
    const useDev = Boolean(simDevSecret.trim());
    if (!tenantId || !simAppId || !simHmacSecret) {
      setSimError("Simulation requires tenant_id, app_id, and HMAC secret.");
      return;
    }
    if (!useDev && !simJwt.trim()) {
      setSimError("Add a Supabase JWT, or set Dev gateway secret (same as CHASTER_BRAIN_DEV_GATEWAY_SECRET on the API) to skip JWT.");
      return;
    }
    try {
      setSimError("");
      const timestamp = Math.floor(Date.now() / 1000).toString();
      const nonce = crypto.randomUUID();
      const toSign = `${tenantId}:${simAppId}:${timestamp}:${nonce}:${message}`;
      const signature = await hmacSha256Hex(simHmacSecret, toSign);
      const { response, elapsedMs } = await api.simulateGateway(
        {
          app_id: simAppId,
          tenant_id: tenantId,
          message,
          metadata: { channel: "dashboard_simulator" }
        },
        {
          jwt: useDev ? undefined : simJwt,
          devSecret: useDev ? simDevSecret : undefined,
          signature,
          timestamp,
          nonce,
          origin: simOrigin
        }
      );
      setSimResult(response);
      setSimLatencyMs(elapsedMs);
      setStatusText(`Simulation success (${elapsedMs}ms)`);
      await refresh();
    } catch (err) {
      setSimError(String(err));
      setStatusText("Simulation failed");
    }
  }

  async function runScenarioSuite() {
    const scenarios = [
      "Hello there",
      "What is your refund policy?",
      "My order #1234 has not arrived, what is the status?"
    ];
    for (const scenario of scenarios) {
      // Run serially so each result and stats update is easy to inspect.
      // eslint-disable-next-line no-await-in-loop
      await runSimulation(scenario);
    }
  }

  async function refresh() {
    if (!tenantId.trim()) return;
    setLoading(true);
    try {
      const [r, p, s] = await Promise.all([
        api.getRuntime(tenantId),
        api.getParameters(tenantId),
        api.getStats(tenantId)
      ]);
      setRuntime(r);
      setParams(p);
      setStats(s);
      setStatusText("Loaded latest control data");
    } catch (err) {
      setStatusText(`Load failed: ${String(err)}`);
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    void refresh();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  async function onStart() {
    if (!tenantId) return;
    try {
      setRuntime(await api.startRuntime(tenantId));
      setStatusText("Brain started");
    } catch (err) {
      setStatusText(`Start failed: ${String(err)}`);
    }
  }

  async function onStop() {
    if (!tenantId) return;
    try {
      setRuntime(await api.stopRuntime(tenantId));
      setStatusText("Brain stopped");
    } catch (err) {
      setStatusText(`Stop failed: ${String(err)}`);
    }
  }

  async function onSaveParams(e: FormEvent) {
    e.preventDefault();
    try {
      const payload = { ...params, tenant_id: tenantId };
      const result = await api.saveParameters(payload);
      setParams(result);
      setStatusText("Parameters updated");
    } catch (err) {
      setStatusText(`Save failed: ${String(err)}`);
    }
  }

  async function onIndexSubmit(e: FormEvent) {
    e.preventDefault();
    if (!indexFaqText.trim()) {
      setStatusText("Paste FAQ or policy text before indexing.");
      return;
    }
    try {
      const result = await api.submitIndexData({
        tenant_id: tenantId,
        source_type: "text",
        payload: {
          title: indexDocTitle.trim() || "FAQ / policy",
          content: indexFaqText
        }
      });
      const extra =
        typeof result.chunks_indexed === "number"
          ? ` — ${result.chunks_indexed} chunk(s) indexed`
          : result.message
            ? ` — ${result.message}`
            : "";
      setStatusText(`Index ${result.status}${extra}`);
      await refresh();
    } catch (err) {
      setStatusText(`Index submit failed: ${String(err)}`);
    }
  }

  return (
    <div className="container">
      <h1>Chaster Brain Control Platform</h1>
      <p className="sub">Start/stop AI, manage indexing data, tune parameters, and inspect live stats.</p>

      <section className="card">
        <label>Tenant ID</label>
        <div className="row">
          <input value={tenantId} onChange={(e) => setTenantId(e.target.value)} placeholder="tenant uuid" />
          <button onClick={() => void refresh()} disabled={loading || !tenantId.trim()}>
            {loading ? "Loading..." : "Load"}
          </button>
        </div>
      </section>

      <section className="card">
        <h2>Runtime Control</h2>
        <div className="row">
          <span className={`badge ${runtime?.is_running ? "on" : "off"}`}>
            {runtime?.is_running ? "Running" : "Stopped"}
          </span>
          <button onClick={() => void onStart()} disabled={!tenantId}>Start</button>
          <button onClick={() => void onStop()} disabled={!tenantId}>Stop</button>
        </div>
      </section>

      <section className="card">
        <h2>Parameters</h2>
        <form onSubmit={onSaveParams}>
          <div className="grid">
            <label>
              Confidence Threshold
              <input
                type="number"
                min={0}
                max={1}
                step={0.01}
                value={params.confidence_threshold}
                onChange={(e) => setParams({ ...params, confidence_threshold: Number(e.target.value) })}
              />
            </label>
            <label>
              Max Context Chunks
              <input
                type="number"
                min={1}
                max={30}
                value={params.max_context_chunks}
                onChange={(e) => setParams({ ...params, max_context_chunks: Number(e.target.value) })}
              />
            </label>
            <label>
              Response Tone
              <input
                value={params.response_tone}
                onChange={(e) => setParams({ ...params, response_tone: e.target.value })}
              />
            </label>
            <label className="checkbox">
              <input
                type="checkbox"
                checked={params.mcp_enabled}
                onChange={(e) => setParams({ ...params, mcp_enabled: e.target.checked })}
              />
              Enable MCP Personal Data Retrieval
            </label>
          </div>
          <button type="submit" disabled={!tenantId}>Save Parameters</button>
        </form>
      </section>

      <section className="card">
        <h2>Index FAQ / policy (for simulator)</h2>
        <p className="sub">
          Chunks your text and stores it in Supabase <code>knowledge_chunks</code>. FAQ matching uses Postgres{" "}
          <code>pg_trgm</code> (no embedding API). Answers still use Groq (GROQ_API_KEY on the API). Apply migration{" "}
          <code>20260421140000_chaster_brain_faq_trgm.sql</code> via <code>supabase db push</code> so the match function is
          available.
        </p>
        <form onSubmit={onIndexSubmit}>
          <label>
            Document title
            <input value={indexDocTitle} onChange={(e) => setIndexDocTitle(e.target.value)} />
          </label>
          <label>
            FAQ or policy text
            <textarea
              rows={10}
              value={indexFaqText}
              onChange={(e) => setIndexFaqText(e.target.value)}
              placeholder="Paste shipping policy, refund rules, hours, etc. Double blank lines split chunks."
            />
          </label>
          <button type="submit" disabled={!tenantId}>
            Index text for FAQ
          </button>
        </form>
      </section>

      <section className="card">
        <h2>Customer Simulator (Real-world test)</h2>
        <p className="sub">
          Runs the same signed gateway request your client widget would send. HMAC + origin are always required. Use dev secret
          below to skip JWT when you cannot log in as a tenant user (local testing only).
        </p>
        <div className="grid">
          <label>
            App ID
            <input value={simAppId} onChange={(e) => setSimAppId(e.target.value)} />
          </label>
          <label>
            Origin
            <input value={simOrigin} onChange={(e) => setSimOrigin(e.target.value)} />
          </label>
        </div>
        <label>
          Dev gateway secret (optional, matches CHASTER_BRAIN_DEV_GATEWAY_SECRET on API)
          <input
            type="password"
            autoComplete="off"
            value={simDevSecret}
            onChange={(e) => setSimDevSecret(e.target.value)}
            placeholder="Leave empty to use JWT instead"
          />
        </label>
        <label>
          Supabase User JWT (if dev secret is empty)
          <textarea rows={3} value={simJwt} onChange={(e) => setSimJwt(e.target.value)} />
        </label>
        <label>
          Widget HMAC Secret
          <input value={simHmacSecret} onChange={(e) => setSimHmacSecret(e.target.value)} />
        </label>
        <label>
          Customer Message
          <textarea rows={3} value={simMessage} onChange={(e) => setSimMessage(e.target.value)} />
        </label>
        <div className="row">
          <button onClick={() => void runSimulation(simMessage)} disabled={!tenantId}>Run Single Test</button>
          <button onClick={() => void runScenarioSuite()} disabled={!tenantId}>Run Scenario Suite</button>
        </div>
        {simError ? <p className="error">{simError}</p> : null}
        {simResult ? (
          <div className="sim-result">
            <p><strong>Intent:</strong> {simResult.intent}</p>
            <p><strong>Confidence:</strong> {simResult.confidence}</p>
            <p><strong>Latency:</strong> {simLatencyMs ?? "-"} ms</p>
            <p><strong>Sources:</strong> {simResult.used_sources.join(", ") || "none"}</p>
            <p><strong>Response:</strong> {simResult.response}</p>
          </div>
        ) : null}
      </section>

      <section className="card">
        <h2>Statistics</h2>
        <div className="stats">
          <div><strong>Knowledge Chunks</strong><span>{stats.knowledge_chunks}</span></div>
          <div><strong>Index Jobs (Total)</strong><span>{stats.index_jobs_total}</span></div>
          <div><strong>Index Jobs (Pending)</strong><span>{stats.index_jobs_pending}</span></div>
          <div><strong>Open Support Cases</strong><span>{stats.support_cases_open}</span></div>
          <div><strong>Total Conversations</strong><span>{stats.conversations_total}</span></div>
          <div><strong>AI Requests Today</strong><span>{stats.ai_requests_today}</span></div>
          <div><strong>Low Confidence Today</strong><span>{stats.low_confidence_today}</span></div>
        </div>
      </section>

      <p className="status">{statusText}</p>
    </div>
  );
}

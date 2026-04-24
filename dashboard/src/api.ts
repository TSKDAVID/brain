export type RuntimeControl = {
  tenant_id: string;
  is_running: boolean;
  mode: string;
  updated_at?: string;
};

export type Parameters = {
  tenant_id: string;
  confidence_threshold: number;
  max_context_chunks: number;
  response_tone: string;
  mcp_enabled: boolean;
  updated_at?: string;
};

export type Stats = {
  tenant_id: string;
  knowledge_chunks: number;
  index_jobs_total: number;
  index_jobs_pending: number;
  support_cases_open: number;
  conversations_total: number;
  ai_requests_today: number;
  low_confidence_today: number;
};

export type GatewaySimResponse = {
  tenant_id: string;
  app_id: string;
  intent: "faq_or_general" | "complex_personal_request";
  confidence: number;
  response: string;
  used_sources: string[];
};

const API_BASE = import.meta.env.VITE_API_BASE_URL || "http://127.0.0.1:8010";

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const extra = init?.headers;
  const mergedHeaders: Record<string, string> = {
    "Content-Type": "application/json",
    ...(extra && typeof extra === "object" && !(extra instanceof Headers)
      ? (extra as Record<string, string>)
      : {})
  };
  const res = await fetch(`${API_BASE}${path}`, {
    ...init,
    headers: mergedHeaders
  });
  if (!res.ok) throw new Error(await res.text());
  return res.json() as Promise<T>;
}

export const api = {
  getRuntime: (tenantId: string) => request<RuntimeControl>(`/v1/control/runtime/${tenantId}`),
  startRuntime: (tenantId: string) =>
    request<RuntimeControl>("/v1/control/start", {
      method: "POST",
      body: JSON.stringify({ tenant_id: tenantId, is_running: true, mode: "manual" })
    }),
  stopRuntime: (tenantId: string) =>
    request<RuntimeControl>("/v1/control/stop", {
      method: "POST",
      body: JSON.stringify({ tenant_id: tenantId, is_running: false, mode: "manual" })
    }),
  getParameters: (tenantId: string) => request<Parameters>(`/v1/control/parameters/${tenantId}`),
  saveParameters: (payload: Parameters) =>
    request<Parameters>("/v1/control/parameters", {
      method: "POST",
      body: JSON.stringify(payload)
    }),
  submitIndexData: (payload: {
    tenant_id: string;
    source_type: "text" | "url" | "document";
    source_ref?: string;
    payload: Record<string, unknown>;
  }) =>
    request<{
      id: string;
      tenant_id: string;
      source_type: string;
      status: string;
      chunks_indexed?: number | null;
      message?: string | null;
    }>("/v1/control/index", {
      method: "POST",
      body: JSON.stringify(payload)
    }),
  getStats: (tenantId: string) => request<Stats>(`/v1/control/stats/${tenantId}`),
  simulateGateway: async (payload: {
    app_id: string;
    tenant_id: string;
    message: string;
    metadata: Record<string, unknown>;
  }, headers: {
    jwt?: string;
    devSecret?: string;
    signature: string;
    timestamp: string;
    nonce: string;
    origin: string;
  }) => {
    const started = performance.now();
    const hdr: Record<string, string> = {
      "Content-Type": "application/json",
      "X-Signature": headers.signature,
      "X-Timestamp": headers.timestamp,
      "X-Nonce": headers.nonce,
      Origin: headers.origin
    };
    if (headers.devSecret?.trim()) {
      hdr["X-Chaster-Dev-Secret"] = headers.devSecret.trim();
    } else if (headers.jwt) {
      hdr.Authorization = `Bearer ${headers.jwt}`;
    }
    const response = await request<GatewaySimResponse>("/v1/gateway/message", {
      method: "POST",
      headers: hdr,
      body: JSON.stringify(payload)
    });
    const elapsedMs = Math.round(performance.now() - started);
    return { response, elapsedMs };
  }
};

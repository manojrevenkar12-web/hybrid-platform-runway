import type { Calendar, ClusterCapacity, DriftReport, Outcome, Summary, VmDetail, VmRow, Wave } from "./types";

export class ApiError extends Error {
  constructor(
    readonly status: number,
    readonly body: unknown,
  ) {
    super(typeof body === "object" && body && "detail" in body ? String((body as { detail: unknown }).detail) : `HTTP ${status}`);
  }
}

type Fetch = typeof fetch;

export function createClient(base = "/api", doFetch: Fetch = (...a) => fetch(...a), token?: string) {
  async function call<T>(path: string, init: RequestInit = {}): Promise<T> {
    const res = await doFetch(base + path, {
      ...init,
      headers: { ...(token ? { Authorization: `Bearer ${token}` } : {}), ...(init.headers ?? {}) },
    });
    const text = await res.text();
    const body = text ? JSON.parse(text) : null;
    if (!res.ok) throw new ApiError(res.status, body);
    return body as T;
  }
  return {
    summary: () => call<Summary>("/summary"),
    waves: () => call<Wave[]>("/waves"),
    calendar: () => call<Calendar>("/calendar"),
    vms: (q: { verdict?: string; site?: string; q?: string } = {}) => {
      const p = new URLSearchParams(Object.entries(q).filter(([, v]) => v) as [string, string][]);
      return call<VmRow[]>(`/vms${p.toString() ? `?${p}` : ""}`);
    },
    vm: (name: string) => call<VmDetail>(`/vms/${encodeURIComponent(name)}`),
    capacity: () => call<ClusterCapacity[]>("/capacity"),
    drift: () => call<DriftReport>("/drift"),
    runWave: (index: number) => call<{ wave: number; outcomes: Outcome[] }>(`/waves/${index}/run`, { method: "POST" }),
  };
}

export type Client = ReturnType<typeof createClient>;
export const api = createClient();

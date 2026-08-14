import type { Merchant, Paginated, Ticket, WebPresenceReview } from "./types";

const API_BASE = import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8000";

class ApiError extends Error {
  status: number;

  constructor(message: string, status: number) {
    super(message);
    this.status = status;
  }
}

async function request<T>(path: string, options: RequestInit = {}): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    ...options,
    headers: { "Content-Type": "application/json", ...options.headers },
  });
  if (!res.ok) {
    const body = await res.text();
    throw new ApiError(body || res.statusText, res.status);
  }
  if (res.status === 204) return undefined as T;
  return res.json();
}

export const api = {
  listMerchants: () => request<Paginated<Merchant>>("/api/merchants/"),
  getMerchant: (id: string) => request<Merchant>(`/api/merchants/${id}/`),
  createMerchant: (business_name: string, website_url: string) =>
    request<Merchant>("/api/merchants/", {
      method: "POST",
      body: JSON.stringify({ business_name, website_url }),
    }),
  getMerchantReviews: (id: string) =>
    request<WebPresenceReview[]>(`/api/merchants/${id}/reviews/`),
  rereview: (id: string) =>
    request<WebPresenceReview>(`/api/merchants/${id}/rereview/`, { method: "POST" }),
  setMonitoring: (id: string, enabled: boolean, interval_hours: number) =>
    request<Merchant>(`/api/merchants/${id}/monitoring/`, {
      method: "POST",
      body: JSON.stringify({ enabled, interval_hours }),
    }),

  listTickets: (filters: Record<string, string> = {}) => {
    const qs = new URLSearchParams(filters).toString();
    return request<Paginated<Ticket>>(`/api/tickets/${qs ? `?${qs}` : ""}`);
  },
  injectFault: (tier: 1 | 2 | 3, faultKey?: string) =>
    request<Ticket>("/api/tickets/inject/", {
      method: "POST",
      body: JSON.stringify({ tier, fault_key: faultKey || undefined }),
    }),
  verifyTicket: (id: string) =>
    request<{ resolved: boolean; ticket: Ticket }>(`/api/tickets/${id}/verify/`, {
      method: "POST",
    }),
  closeTicket: (id: string, resolution_notes = "") =>
    request<Ticket>(`/api/tickets/${id}/close/`, {
      method: "POST",
      body: JSON.stringify({ resolution_notes }),
    }),
};

export { ApiError };

import { useEffect, useState } from "react";
import { api, ApiError } from "../api";
import type { Ticket, TicketStatus } from "../types";

const STATUS_FILTERS: (TicketStatus | "all")[] = ["all", "open", "in_progress", "resolved", "closed"];

export default function Tickets() {
  const [tickets, setTickets] = useState<Ticket[] | null>(null);
  const [statusFilter, setStatusFilter] = useState<TicketStatus | "all">("all");
  const [tier, setTier] = useState<1 | 2 | 3>(1);
  const [faultKey, setFaultKey] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busyId, setBusyId] = useState<string | null>(null);
  const [injecting, setInjecting] = useState(false);

  const load = () => {
    api
      .listTickets(statusFilter === "all" ? {} : { status: statusFilter })
      .then((data) => setTickets(data.results))
      .catch((e) => setError(e instanceof ApiError ? e.message : String(e)));
  };

  useEffect(load, [statusFilter]);

  const handleInject = async () => {
    setInjecting(true);
    setError(null);
    try {
      await api.injectFault(tier, faultKey.trim() || undefined);
      setFaultKey("");
      load();
    } catch (e) {
      setError(e instanceof ApiError ? e.message : String(e));
    } finally {
      setInjecting(false);
    }
  };

  const handleVerify = async (id: string) => {
    setBusyId(id);
    setError(null);
    try {
      const { resolved } = await api.verifyTicket(id);
      if (!resolved) setError("Still broken — the underlying condition hasn't been fixed yet.");
      load();
    } catch (e) {
      setError(e instanceof ApiError ? e.message : String(e));
    } finally {
      setBusyId(null);
    }
  };

  const handleClose = async (id: string) => {
    setBusyId(id);
    setError(null);
    try {
      await api.closeTicket(id);
      load();
    } catch (e) {
      setError(e instanceof ApiError ? e.message : String(e));
    } finally {
      setBusyId(null);
    }
  };

  return (
    <div>
      <div className="card">
        <h2>Break something</h2>
        <p className="empty-state">
          Tier 1 = app/data layer (always available). Tier 2 = Docker Compose services (needs{" "}
          <code>docker compose up -d</code>). Tier 3 = real AWS infra drift (needs LocalStack +{" "}
          <code>pulumi up</code>).
        </p>
        <div className="form-row">
          <select value={tier} onChange={(e) => setTier(Number(e.target.value) as 1 | 2 | 3)}>
            <option value={1}>Tier 1 — app/data</option>
            <option value={2}>Tier 2 — Docker services</option>
            <option value={3}>Tier 3 — real AWS drift</option>
          </select>
          <input
            placeholder="fault key (blank = random)"
            value={faultKey}
            onChange={(e) => setFaultKey(e.target.value)}
          />
          <button className="btn danger" onClick={handleInject} disabled={injecting}>
            {injecting ? "Breaking…" : "Break it"}
          </button>
        </div>
      </div>

      {error && <div className="error-banner">{error}</div>}

      <div className="card">
        <div className="form-row" style={{ justifyContent: "space-between" }}>
          <h2 style={{ margin: 0 }}>Ticket queue</h2>
          <select value={statusFilter} onChange={(e) => setStatusFilter(e.target.value as TicketStatus | "all")}>
            {STATUS_FILTERS.map((s) => (
              <option key={s} value={s}>
                {s}
              </option>
            ))}
          </select>
        </div>

        {tickets === null ? (
          <p className="empty-state">Loading…</p>
        ) : tickets.length === 0 ? (
          <p className="empty-state">No tickets.</p>
        ) : (
          tickets.map((t) => (
            <div key={t.id} className="ticket-card">
              <div>
                <strong>{t.title}</strong>
                <div className="meta">
                  <span className={`badge ${t.priority}`}>{t.priority}</span>
                  <span className={`badge ${t.status}`}>{t.status}</span>
                  <span className="badge low">{t.category}</span>
                  <span className="badge low">{t.source.replace("_", " ")}</span>
                </div>
                <p className="desc">{t.description}</p>
              </div>
              <div className="ticket-actions">
                {t.status !== "resolved" && t.status !== "closed" && (
                  <button
                    className="btn secondary"
                    onClick={() => handleVerify(t.id)}
                    disabled={busyId === t.id}
                  >
                    Verify fix
                  </button>
                )}
                {t.status === "resolved" && (
                  <button className="btn" onClick={() => handleClose(t.id)} disabled={busyId === t.id}>
                    Close
                  </button>
                )}
              </div>
            </div>
          ))
        )}
      </div>
    </div>
  );
}

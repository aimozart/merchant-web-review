import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { api, ApiError } from "../api";
import type { Merchant, WebPresenceReview } from "../types";

export default function MerchantDetail() {
  const { id } = useParams<{ id: string }>();
  const [merchant, setMerchant] = useState<Merchant | null>(null);
  const [reviews, setReviews] = useState<WebPresenceReview[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [monitoringEnabled, setMonitoringEnabled] = useState(false);
  const [intervalHours, setIntervalHours] = useState(24);
  const [busy, setBusy] = useState(false);

  const load = () => {
    if (!id) return;
    api
      .getMerchant(id)
      .then((m) => {
        setMerchant(m);
        setMonitoringEnabled(m.monitoring_enabled);
        setIntervalHours(m.monitoring_interval_hours);
      })
      .catch((e) => setError(e instanceof ApiError ? e.message : String(e)));
    api
      .getMerchantReviews(id)
      .then(setReviews)
      .catch((e) => setError(e instanceof ApiError ? e.message : String(e)));
  };

  useEffect(load, [id]);

  const handleRereview = async () => {
    if (!id) return;
    setBusy(true);
    try {
      await api.rereview(id);
      load();
    } catch (e) {
      setError(e instanceof ApiError ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };

  const handleMonitoringSave = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!id) return;
    setBusy(true);
    try {
      const updated = await api.setMonitoring(id, monitoringEnabled, intervalHours);
      setMerchant(updated);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };

  if (!merchant) return <p className="empty-state">Loading…</p>;

  return (
    <div>
      <p>
        <Link to="/">&larr; All merchants</Link>
      </p>
      {error && <div className="error-banner">{error}</div>}

      <div className="card">
        <h2>{merchant.business_name}</h2>
        <p className="empty-state">{merchant.website_url}</p>
        <div className="form-row">
          <button className="btn" onClick={handleRereview} disabled={busy}>
            Trigger re-review now
          </button>
        </div>
      </div>

      <div className="card">
        <h3>Merchant Monitoring</h3>
        <form onSubmit={handleMonitoringSave} className="form-row">
          <label className="form-row" style={{ gap: "0.4rem" }}>
            <input
              type="checkbox"
              checked={monitoringEnabled}
              onChange={(e) => setMonitoringEnabled(e.target.checked)}
            />
            Enabled
          </label>
          <label className="form-row" style={{ gap: "0.4rem" }}>
            Every
            <input
              type="number"
              min={1}
              value={intervalHours}
              onChange={(e) => setIntervalHours(Number(e.target.value))}
              style={{ width: "5rem" }}
            />
            hours
          </label>
          <button className="btn secondary" type="submit" disabled={busy}>
            Save
          </button>
        </form>
      </div>

      <div className="card">
        <h3>Review history</h3>
        {reviews === null ? (
          <p className="empty-state">Loading…</p>
        ) : reviews.length === 0 ? (
          <p className="empty-state">No reviews yet.</p>
        ) : (
          reviews.map((r) => (
            <div key={r.id} style={{ borderBottom: "1px solid var(--border)", padding: "0.8rem 0" }}>
              <div className="form-row">
                <span className="badge low">{r.status}</span>
                {r.recommendation && <span className={`badge ${r.recommendation}`}>{r.recommendation}</span>}
                {r.is_monitoring_check && <span className="badge low">monitoring check</span>}
                <span className="empty-state">{new Date(r.created_at).toLocaleString()}</span>
              </div>
              {r.summary && <p style={{ marginBottom: "0.3rem" }}>{r.summary}</p>}
              {r.error_message && <p className="error-banner">{r.error_message}</p>}
              {r.signals.length > 0 && (
                <ul className="signal-list">
                  {r.signals.map((s) => (
                    <li key={s.id}>
                      <span className={`badge ${s.severity}`}>{s.severity}</span>
                      <strong>{s.label}</strong>
                      {s.detail && <span className="detail">— {s.detail}</span>}
                    </li>
                  ))}
                </ul>
              )}
            </div>
          ))
        )}
      </div>
    </div>
  );
}

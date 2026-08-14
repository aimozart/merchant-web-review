import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api, ApiError } from "../api";
import type { Merchant } from "../types";

export default function Dashboard() {
  const [merchants, setMerchants] = useState<Merchant[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [businessName, setBusinessName] = useState("");
  const [websiteUrl, setWebsiteUrl] = useState("");
  const [submitting, setSubmitting] = useState(false);

  const load = () => {
    api
      .listMerchants()
      .then((data) => setMerchants(data.results))
      .catch((e) => setError(e instanceof ApiError ? e.message : String(e)));
  };

  useEffect(load, []);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    setSubmitting(true);
    try {
      await api.createMerchant(businessName, websiteUrl);
      setBusinessName("");
      setWebsiteUrl("");
      load();
    } catch (e) {
      setError(e instanceof ApiError ? e.message : String(e));
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div>
      <div className="card">
        <h2>Submit a merchant for review</h2>
        <form onSubmit={handleSubmit} className="form-row">
          <input
            placeholder="Business name"
            value={businessName}
            onChange={(e) => setBusinessName(e.target.value)}
            required
          />
          <input
            placeholder="https://merchant-site.example"
            value={websiteUrl}
            onChange={(e) => setWebsiteUrl(e.target.value)}
            required
            style={{ flex: 1, minWidth: "16rem" }}
          />
          <button className="btn" type="submit" disabled={submitting}>
            {submitting ? "Submitting…" : "Submit for review"}
          </button>
        </form>
      </div>

      {error && <div className="error-banner">{error}</div>}

      <div className="card">
        <h2>Merchants</h2>
        {merchants === null ? (
          <p className="empty-state">Loading…</p>
        ) : merchants.length === 0 ? (
          <p className="empty-state">No merchants submitted yet.</p>
        ) : (
          <table>
            <thead>
              <tr>
                <th>Business</th>
                <th>Website</th>
                <th>Latest review</th>
                <th>Monitoring</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              {merchants.map((m) => (
                <tr key={m.id}>
                  <td>{m.business_name}</td>
                  <td>{m.website_url}</td>
                  <td>
                    {m.latest_review ? (
                      m.latest_review.recommendation ? (
                        <span className={`badge ${m.latest_review.recommendation}`}>
                          {m.latest_review.recommendation}
                        </span>
                      ) : (
                        <span className="badge low">{m.latest_review.status}</span>
                      )
                    ) : (
                      <span className="empty-state">none</span>
                    )}
                  </td>
                  <td>{m.monitoring_enabled ? `every ${m.monitoring_interval_hours}h` : "off"}</td>
                  <td>
                    <Link to={`/merchants/${m.id}`}>View</Link>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
}

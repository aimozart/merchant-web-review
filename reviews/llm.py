"""
Synthesizes a raw WebPresenceSnapshot into a structured underwriting recommendation
and a set of categorized risk signals — the "analysis" half of the Web Presence
Review, using an LLM the same way TrueBiz's own product does: as a reasoning layer
over deterministically-gathered web data, not as the data source itself.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass

from .scraping import WebPresenceSnapshot


@dataclass
class SignalResult:
    category: str  # matches RiskSignal.CATEGORY_CHOICES
    severity: str  # matches RiskSignal.SEVERITY_CHOICES
    label: str
    detail: str = ""


@dataclass
class AnalysisResult:
    recommendation: str  # "pass" | "fail" | "review"
    summary: str
    signals: list[SignalResult]


PROMPT_TEMPLATE = """You are an underwriting risk analyst reviewing a merchant's web presence \
for a payments company, in the same spirit as TrueBiz's automated merchant risk platform.

Merchant: {business_name}
Website: {url}
HTTP status: {status_code}
Resolved IP: {resolved_ip}
Page title: {title}
Meta description: {meta_description}
Social links found: {social_links}
Prohibited-category keyword hits: {prohibited_hits}
Negative-reputation keyword hits: {reputation_hits}
Fetch error (if any): {fetch_error}

Based only on this evidence, produce a JSON object with exactly these fields:
{{
  "recommendation": "pass" | "fail" | "review",
  "summary": "1-3 sentence underwriting summary explaining the recommendation",
  "signals": [
    {{"category": "domain"|"content"|"social"|"reputation",
      "severity": "info"|"low"|"medium"|"high",
      "label": "short signal name",
      "detail": "one sentence explaining this specific signal"}}
  ]
}}

Rules:
- If the fetch failed entirely, recommendation should be "review" (insufficient evidence to \
pass or fail outright) with a signal explaining the fetch failure.
- Any prohibited-category keyword hit should push toward "fail" with a "high" severity content signal.
- No social presence at all is a mild "low" severity social signal, not automatically disqualifying.
- Respond with ONLY the JSON object, no other text.
"""


def _rule_based_fallback(snapshot: WebPresenceSnapshot) -> AnalysisResult:
    """Deterministic analysis used when no LLM API key is configured, so the whole
    pipeline runs end-to-end with zero external dependencies."""
    signals: list[SignalResult] = []

    if snapshot.fetch_error:
        return AnalysisResult(
            recommendation="review",
            summary=f"Could not retrieve the merchant's website: {snapshot.fetch_error}. "
            "Manual review recommended due to insufficient evidence.",
            signals=[
                SignalResult(
                    category="domain",
                    severity="medium",
                    label="Website unreachable",
                    detail=snapshot.fetch_error,
                )
            ],
        )

    if snapshot.prohibited_keyword_hits:
        signals.append(
            SignalResult(
                category="content",
                severity="high",
                label="Prohibited-category keywords detected",
                detail=f"Found: {', '.join(snapshot.prohibited_keyword_hits)}",
            )
        )

    if snapshot.reputation_keyword_hits:
        signals.append(
            SignalResult(
                category="reputation",
                severity="medium",
                label="Negative reputation signals on page",
                detail=f"Found: {', '.join(snapshot.reputation_keyword_hits)}",
            )
        )

    if snapshot.social_links:
        signals.append(
            SignalResult(
                category="social",
                severity="info",
                label=f"{len(snapshot.social_links)} social presence link(s) found",
                detail=", ".join(snapshot.social_links[:5]),
            )
        )
    else:
        signals.append(
            SignalResult(
                category="social",
                severity="low",
                label="No social presence detected",
                detail="No links to major social platforms found on the page.",
            )
        )

    signals.append(
        SignalResult(
            category="domain",
            severity="info",
            label="Domain resolved" if snapshot.resolved_ip else "Domain did not resolve",
            detail=snapshot.resolved_ip or "DNS resolution failed.",
        )
    )

    if snapshot.prohibited_keyword_hits:
        recommendation = "fail"
        summary = (
            f"{snapshot.title or snapshot.url} shows prohibited-category content "
            "and should not be approved without further review."
        )
    elif snapshot.reputation_keyword_hits or not snapshot.resolved_ip:
        recommendation = "review"
        summary = "Some risk indicators present; recommend manual underwriter review."
    else:
        recommendation = "pass"
        summary = (
            f"{snapshot.title or snapshot.url} shows no prohibited content or major "
            "negative reputation signals in this automated review."
        )

    return AnalysisResult(recommendation=recommendation, summary=summary, signals=signals)


def _llm_analyze(snapshot: WebPresenceSnapshot, business_name: str) -> AnalysisResult:
    import google.generativeai as genai

    genai.configure(api_key=os.environ["GEMINI_API_KEY"])
    model = genai.GenerativeModel("gemini-1.5-flash")

    prompt = PROMPT_TEMPLATE.format(
        business_name=business_name,
        url=snapshot.url,
        status_code=snapshot.status_code,
        resolved_ip=snapshot.resolved_ip,
        title=snapshot.title,
        meta_description=snapshot.meta_description,
        social_links=", ".join(snapshot.social_links) or "none",
        prohibited_hits=", ".join(snapshot.prohibited_keyword_hits) or "none",
        reputation_hits=", ".join(snapshot.reputation_keyword_hits) or "none",
        fetch_error=snapshot.fetch_error or "none",
    )
    response = model.generate_content(prompt)
    raw = response.text.strip().strip("`").removeprefix("json").strip()
    data = json.loads(raw)

    return AnalysisResult(
        recommendation=data["recommendation"],
        summary=data["summary"],
        signals=[SignalResult(**s) for s in data.get("signals", [])],
    )


def analyze(snapshot: WebPresenceSnapshot, business_name: str) -> AnalysisResult:
    """Entry point: LLM analysis if configured, deterministic fallback otherwise —
    never lets an LLM/API hiccup break the review pipeline."""
    from ops.models import OpsFlag

    if OpsFlag.is_set("llm_analysis_disabled"):
        return _rule_based_fallback(snapshot)

    if os.environ.get("GEMINI_API_KEY"):
        try:
            return _llm_analyze(snapshot, business_name)
        except Exception:
            pass
    return _rule_based_fallback(snapshot)

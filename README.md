# Merchant Web Review

[![CI](https://github.com/aimozart/merchant-web-review/actions/workflows/ci.yml/badge.svg)](https://github.com/aimozart/merchant-web-review/actions/workflows/ci.yml)

A merchant web-presence risk review service — submit a business, it scrapes and analyzes the
business's website, and returns a structured underwriting recommendation (`pass` / `fail` /
`review`) backed by categorized risk signals and the original scraped evidence.

## Purpose

This isn't a one-off demo — it's a standing practice environment for keeping Python/Django/AWS
skills sharp on an ongoing basis, the same way they'd get exercised day-to-day in a real job:
real product code, real infrastructure-as-code verified against a real (if local) AWS emulation,
and a ticket queue to work against as if genuinely on call. The **SRE break/fix trainer**
(below) is the core of that: it files tickets against this exact stack and only lets you close
one once the underlying system has actually recovered, so working through it stays honest
practice rather than a checklist.

Full-stack, end to end: Django/DRF backend, async Celery pipeline, an LLM-with-deterministic-
fallback analysis layer, a React frontend, and Pulumi (Python) infrastructure-as-code verified
against LocalStack.

## What it does

1. Submit a merchant (business name + website URL) via the API or the React UI.
2. A Celery task scrapes the site, extracts signals (title, social links, prohibited-category
   keyword hits, reputation keyword hits, DNS resolution), and stores the raw snapshot as
   auditable evidence in S3-compatible object storage.
3. An LLM (Gemini) reasons over that structured evidence to produce a recommendation and a list
   of categorized risk signals — falling back to a deterministic rule-based analyzer if no LLM
   key is configured, or if the LLM call fails, so the pipeline never breaks on an external
   dependency.
4. Optional **Merchant Monitoring**: a merchant can be flagged for periodic re-review on a
   configurable interval, run by Celery Beat.

```
Submit merchant ─▶ Django/DRF API ─▶ Postgres
                                        │
                                        ▼
                         Celery task queued via Redis
                                        │
                                        ▼
                 scrape ─▶ store snapshot (S3/MinIO) ─▶ analyze (LLM or fallback)
                                        │
                                        ▼
                          recommendation + risk signals ─▶ Postgres
```

## Tech stack

| Layer | Tools |
|---|---|
| Backend | Python, Django, Django REST Framework, PostgreSQL |
| Async pipeline | Celery, Celery Beat, Redis |
| Object storage | MinIO (local), S3 (production) via boto3 |
| LLM analysis | Google Gemini, with a deterministic rule-based fallback |
| Observability | Prometheus, Grafana, django-prometheus, custom business metrics |
| Frontend | React, TypeScript, Vite |
| Infrastructure as Code | Pulumi (Python) targeting AWS — ECS Fargate, RDS, ElastiCache, S3, ALB, VPC/VPN |
| Local infra verification | LocalStack Ultimate |
| CI | GitHub Actions — lint, Django checks, migrations, full test suite against real Postgres/Redis |

## Getting started

```bash
# 1. Local dev stack: Postgres, Redis, MinIO, Prometheus, Grafana
docker compose up -d

# 2. Python environment
python -m venv venv && source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # fill in GEMINI_API_KEY if you want real LLM analysis

# 3. Django
python manage.py migrate
python manage.py runserver

# 4. Celery, in separate terminals
celery -A merchantreview worker -l info
celery -A merchantreview beat -l info

# 5. Frontend
cd frontend && npm install && npm run dev
```

The API is at `http://localhost:8000/api/`, the frontend dev server at `http://localhost:5173`.

## The SRE break/fix trainer

On top of the product itself, `ops/` is a self-contained incident-response practice tool: inject a
real fault, get a ticket describing only the *symptom*, fix the actual underlying state, and only
close the ticket once the system has genuinely recovered — verified against real state, not the
ticket's own status field.

Three tiers, in increasing order of how much of the stack needs to be running:

- **Tier 1 — application/data layer** (Django only): stuck reviews, overdue monitoring, a
  degraded-LLM feature flag, bad data, failure spikes.
- **Tier 2 — Docker Compose/service layer** (needs `docker compose up -d`): real container
  stop/start against Postgres, Redis, MinIO, Grafana — including distinguishing "the service is
  down" from "the service is up but misconfigured."
- **Tier 3 — real infrastructure drift** (needs LocalStack + `pulumi up` in `infra/`): security
  group rules, route tables, load balancer health checks, and a site-to-site VPN connection
  modified directly via the AWS API, bypassing Pulumi — simulating out-of-band changes and
  practicing the reconcile-via-`pulumi refresh`/`pulumi up` workflow.

```bash
python manage.py break_something [--fault <key>]     # Tier 1
python manage.py break_infra [--fault <key>]          # Tier 2
python manage.py break_network [--fault <key>]        # Tier 3

python manage.py verify_fix / verify_infra_fix / verify_network_fix <ticket_id>
python manage.py reveal_fault / reveal_infra_fault / reveal_network_fault <ticket_id>
python manage.py list_faults / list_infra_faults / list_network_faults
```

Also reachable through the same `Ticket` API the React "Ops / Tickets" page uses:
`POST /api/tickets/inject/` (`{"tier": 1|2|3, "fault_key": "..."}`),
`POST /api/tickets/{id}/verify/`, `POST /api/tickets/{id}/close/`.

## Infrastructure as code

`infra/` is a Pulumi (Python) program describing the AWS deployment target: a VPC with public/
private subnets, RDS Postgres, ElastiCache Redis, an S3 snapshot bucket, an ECS Fargate cluster
running the web/celery-worker/celery-beat services behind an ALB, and a site-to-site VPN to a
simulated branch office. The same code targets LocalStack (`local` stack) for free, local
end-to-end verification, or real AWS (a `prod` stack with no endpoint overrides) unchanged.

```bash
cd infra
localstack start -d
pulumi stack select local   # or: pulumi stack init local
pulumi up
```

## Testing

```bash
ruff check .
python manage.py check
python manage.py test
```

Runs automatically on every push/PR via GitHub Actions against real Postgres and Redis service
containers — see the badge above.

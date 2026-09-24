# Changelog

All notable changes to this project are documented here. The format is based on
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and this project adheres
to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [2.1.0] - 2026

### Added
- **Amazon Bedrock AI provider** (default model **Amazon Nova Lite**,
  `amazon.nova-lite-v1:0`) alongside Gemini and OpenAI. Configure with
  `AI_PROVIDER=bedrock` (or as failover with `AI_SECONDARY_PROVIDER=bedrock`).
  Uses the Bedrock **Converse API** via `boto3` and the standard AWS credential
  chain (IAM role / instance profile / environment / `~/.aws`), or explicit
  `AWS_ACCESS_KEY_ID` / `AWS_SECRET_ACCESS_KEY` keys.
- New configuration: `BEDROCK_MODEL`, `AWS_REGION` (falls back to
  `AWS_DEFAULT_REGION`), `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`,
  `AWS_SESSION_TOKEN` (documented in `backend/.env.example`).

## [2.0.0] - 2026

Complete rewrite of the "AI Maintenance Assistant for Zabbix 7.2+" from a
monolithic backend + inline widget into a clean, modular v2 with the backend and
the Zabbix dashboard widget deployed independently.

### Added
- **Modular Flask backend** split into `core/`, `ai/`, `zabbix/`, `services/`,
  `api/`, `i18n/`, `cache/`, `observability/` behind an app factory.
- **Deterministic recurrence engine** in a pure core: the AI extracts intent
  (day/month/occurrence names, hours, duration) and the backend computes the
  Zabbix bitmasks — no bitmask arithmetic in the AI prompt.
- **All maintenance types verified** end-to-end (once / daily / weekly / monthly
  by day-of-month and by day-of-week) with property-based and parity tests.
- **Internationalization (es / en / pt)** in both backend and widget, following
  the Zabbix user's language.
- **Ticket of any nomenclature** (`INC0012345`, `JIRA-4521`, `CHG-2024-001`,
  `#88213`, `100-178306`, ...): AI-extracted with a broad backend fallback.
- **Security**: every endpoint that touches Zabbix requires a validated
  logged-in Zabbix user (401 otherwise). Rate limiting and a user-validation
  cache included.
- **Observability**: `GET /health` and `GET /metrics` (Prometheus).
- **AI provider abstraction** with failover and JSON-Schema validation
  (Google Gemini via `google-genai`, OpenAI).
- **Widget modernization**: thin orchestrator + HTTP/formatter/renderer modules,
  Zabbix classic-blue theme (light/dark), WCAG affordances, clickable example
  cards, discreet connection status chip.
- **Docker** (`python:3.12-slim`) + `docker-compose` (aima1..aima5) and CI that
  publishes the backend image to GHCR and attaches the widget zip to releases.

### Changed
- **BREAKING — deployment topology**: backend and widget are now separate
  artifacts deployed independently. The widget talks to the backend through a
  configurable **Backend API URL**.
- **BREAKING — AI SDK**: migrated from the deprecated `google-generativeai` to
  the official `google-genai` SDK (compatible with current Python runtimes).
- **BREAKING — default model**: `GEMINI_MODEL` default is now
  `gemini-flash-lite-latest` (the previous `gemini-2.0-flash` was retired).
- Configuration is centralized in `config.py` (`AppConfig.from_env`); see
  `backend/.env.example` for the full, documented variable set.

### Security
- No secrets are baked into the image or committed to the repo (`.env` is
  git-ignored and excluded from the Docker build context).
- All Zabbix-facing endpoints now enforce logged-in Zabbix user validation.

### Migration guide (v1 -> v2)
1. **Deploy the backend separately** (Docker or local). Copy
   `backend/.env.example` to `backend/.env` and set `ZABBIX_API_URL`,
   `ZABBIX_TOKEN`, the AI provider key, and `CORS_ALLOWED_ORIGINS`.
2. **Install the widget** from `widget/aimaintenance/` into
   `/usr/share/zabbix/ui/modules/aimaintenance/`, then enable it in
   Administration -> General -> Modules (Scan directory).
3. **Point the widget** to the backend via the **Backend API URL** field.
4. **Rotate credentials** if they were ever used with the v1 setup.
5. The v1 (monolithic) line is preserved on the `v1-legacy` branch and the
   `v1.5.4` tag.

## [1.5.4] - prior
Last v1 (monolithic backend + inline widget) release. Preserved on the
`v1-legacy` branch and the `v1.5.4` tag.

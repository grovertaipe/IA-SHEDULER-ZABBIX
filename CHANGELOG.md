# Changelog

All notable changes to this project are documented here. The format is based on
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and this project adheres
to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [2.6.1] - 2026

### Fixed
- **Problem tags now actually reach Zabbix on creation.** In 2.6.0 the AI
  extracted problem tags but they were dropped in transit: the `/chat` response
  did not include `problem_tags` / `tags_evaltype` / `maintenance_type`, and the
  widget did not forward them on `/create_maintenance`, so maintenances were
  created without tags. The `/chat` response now surfaces these fields and the
  widget resends them on create; the create endpoint already accepted them.
- The confirmation popup now shows a **Problem tags** line and a **without data
  collection** indicator when applicable.

### Note
- This touches the WIDGET — reinstall the widget (v2.6.1 zip) in Zabbix and hard-
  refresh the browser for the create-side tag forwarding to take effect.

## [2.6.0] - 2026

### Added
- **Maintenance problem tags from natural language.** You can now scope a
  maintenance to specific problems — e.g. "maintenance for NBJOSCCMA01 tomorrow
  22:00-23:00 but only CPU" or "group Virtual machines, only problems with
  class=os". The AI extracts `problem_tags` (`tag`/`value`/`operator`),
  `tags_evaltype` (And-Or / Or) and `maintenance_type` (with / without data
  collection). Colloquial resources map to `component=*` (CPU→`component=cpu`,
  disk/memory/network), and explicit `key=value` tags are kept literally.
  Problem tags are only applied with data collection enabled (Zabbix constraint).
- The AI also distinguishes **host discovery by tag** (`trigger_tags` — "all
  hosts with tag X=Y") from problem-suppression tags, so both use cases work.

### Notes
- This is a prompt-only enhancement; the backend already validated and forwarded
  these fields to Zabbix. The AI never computes anything — it only extracts the
  tags; the backend builds the `maintenance.create` payload.

## [2.5.2] - 2026

### Changed
- **`/health` now reports the real released version automatically.** The
  application version is baked into the Docker image at build time from the git
  tag (a `APP_VERSION` Docker build-arg set by CI, exposed as an `ENV` the
  backend reads), so no manual `.env` editing is needed per release. Setting
  `APP_VERSION` in the environment still works as an explicit override.
- Bumped the module-constant version fallback to the current release and
  documented that the authoritative version comes from the image build. Note:
  a deployment whose `.env` pins `APP_VERSION` will keep overriding the baked
  value — remove that line to let the image version show through.

## [2.5.1] - 2026

### Fixed
- **Maintenances without a ticket can now be created** (e.g. a group or
  tag-based maintenance with no ticket). Zabbix rejected them with
  `Invalid parameter "/1/name": cannot be empty.` because the generated name
  collapsed to an empty string: the widget's create call carries no prose and,
  without a ticket, there was nothing left to name the maintenance.
- The backend name generator now guarantees a non-empty name, restoring the v1
  behaviour: with no ticket and no summary it builds the name from the resolved
  resource names (up to 3 hosts, then up to 2 groups as `Grupo <name>`, with a
  "+N more" suffix), falling back to `AI Maintenance` when nothing is resolved.
  Ticketed names are unchanged.

## [2.5.0] - 2026

### Added
- **Multi-turn conversation memory.** Users can now supply maintenance details
  across several chat messages and the assistant accumulates them instead of
  re-asking in a loop. The widget resends the recent conversation history on
  each `/chat` call and the AI re-reads it to merge fields across turns (later
  turns override earlier ones for the same field). The backend stays fully
  stateless — no server-side sessions or storage.
- The history is **scoped to the maintenance in progress** so previously
  created maintenances never leak into the AI context: the widget resets the
  history automatically when a maintenance is created or cancelled, plus a
  manual "New request" / "Nueva solicitud" control to reset on demand. A safety
  cap limits the resent history to the last 10 turns.

### Changed
- `POST /chat` (and `/parse`) accept an optional `history` array of
  `{role, content}` turns; when absent, behaviour is identical to before. The
  AI-provider `extract(...)` interface takes an optional `history` argument,
  threaded through all providers (Gemini / OpenAI / Bedrock) and the failover
  wrapper. The prompt renders the prior turns as a compact transcript; user
  text is brace-escaped so it never breaks prompt formatting. The AI still
  never computes timestamps or bitmasks.

## [2.4.4] - 2026

### Fixed
- **Recurring maintenances (daily/weekly/monthly) can now be created**, not just
  previewed. Creation failed with "Falta start_time en la configuración
  recurrente" because of a contract drift: `/chat` emitted the schedule as a
  Zabbix-format `recurrence_config` (`start_time`/`duration` in seconds,
  `dayofweek`/`month` bitmasks) which the widget resent verbatim, but
  `POST /create_maintenance` only understood the intent-format `recurrence`
  object (`start_hour`/`duration_hours`). Only `once` created successfully.
- `POST /create_maintenance` now also accepts the Zabbix-format
  `recurrence_config`, mapping it to the engine's inputs (`start_time` →
  `start_hour`, `duration` → `duration_hours`, and the precomputed
  `dayofweek`/`month` bitmasks threaded through and validated). Backward
  compatible: the intent-format `recurrence` object and the `once` path are
  unchanged, and explicit intent-format values take precedence.
- The `/chat` `recurrence_config` now includes `duration` (seconds) so the
  create round-trip has the maintenance length. The AI still never computes
  timestamps or bitmasks.

## [2.4.3] - 2026

### Fixed
- **Confirmation popup now shows the Period for recurring maintenances too.**
  The `/chat` (and `/parse`) response now returns the top-level `start_time` /
  `end_time` display strings (`YYYY-MM-DD HH:MM`) for EVERY maintenance type,
  not just `once`. These are the maintenance active window (Zabbix
  `active_since` / `active_till`), exactly as the legacy monolith emitted them,
  so daily / weekly / monthly maintenances no longer show "Period: -". Recurring
  types still additionally carry `recurrence_config` for the schedule detail.
- Unified the window computation on a single code path: the backend core builds
  the time period once and derives the active window deterministically; the AI
  never computes timestamps or bitmasks.

## [2.4.2] - 2026

### Fixed
- **Confirmation popup now shows the schedule for recurring maintenances.**
  The `/chat` (and `/parse`) response now includes a `recurrence_config` object
  for daily / weekly / monthly maintenances, carrying the Zabbix fields the
  widget renders (`start_time`, `every`, `dayofweek`, `day`, `month`). These are
  computed deterministically by the backend core (`build_timeperiod`); the AI
  never computes bitmasks. Previously the response only carried
  `recurrence_type`, so the widget skipped the recurrence/technical-configuration
  line and a routine maintenance showed no schedule at all.

## [2.4.1] - 2026

### Fixed
- **Confirmation popup now shows the Period for one-time ("once") maintenances.**
  The `/chat` (and `/parse`) response again includes `start_time` / `end_time`
  display strings (`YYYY-MM-DD HH:MM`) for the once case, derived deterministically
  by the backend from the resolved window (explicit epochs, or
  `start_date` + `start_hour` + `duration_hours`). The widget preview showed
  "Period: -" because those strings were absent after the once refactor.
- The widget confirmation panel no longer risks rendering "Period: undefined -
  undefined" for recurring maintenances: the Period line is now shown only when
  a concrete window is present (recurring types display their schedule from the
  recurrence configuration instead).

## [2.4.0] - 2026

### Fixed
- **One-time ("once") maintenances now create correctly from natural language.**
  The AI returns a structured `start_date` (ISO `YYYY-MM-DD`, resolved from
  today/tomorrow) plus `start_hour` and `duration_hours`, and the backend core
  computes the epoch `start_ts` / `end_ts` deterministically. Previously the
  once path required the AI to return epoch timestamps it was explicitly told
  not to compute, so once requests stalled with
  `missing_fields=["start_ts","end_ts"]`.
- The confirmation detail popup reappears for once maintenances now that the
  schedule resolves to a complete, valid window before the create step.

### Changed
- `ONCE` completeness is satisfied by either explicit epochs
  (`start_ts` + `end_ts`) or the structured trio
  (`start_date` + `start_hour` + `duration_hours`).

### Unchanged (invariant)
- The AI never computes timestamps or bitmasks; it extracts intent and the
  backend core computes all numeric schedule values.

## [2.3.0] - 2026

### Added
- **Amazon Bedrock API key (bearer token) authentication.** Set
  `AWS_BEARER_TOKEN_BEDROCK` (plus `AWS_REGION`) to authenticate Bedrock with a
  Bedrock API key instead of IAM access keys — boto3 uses it automatically.

### Changed
- Bumped `boto3` to 1.40.30 (the version line that supports
  `AWS_BEARER_TOKEN_BEDROCK`).
- Bedrock credential precedence: explicit IAM access keys > Bedrock API key
  (bearer token) > default AWS credential chain (env / ~/.aws / IAM role).
- Config no longer warns about "no credentials" for Bedrock when a bearer token
  is present.

## [2.2.0] - 2026

### Added
- **Natural-language replies in the operator's own language.** The AI now
  returns an `assistant_message` written in the SAME language the user typed
  (any language), with a natural but guided tone that steers toward creating a
  Zabbix maintenance. Used for the conversational replies (help / clarification
  / off-topic / "ready to create").

### Changed
- Conversational text prefers the AI-written `assistant_message`; when the AI is
  unavailable it falls back to the fixed es/en/pt catalog messages using the
  browser/Zabbix locale. System errors and the creation confirmation remain
  templated (localized es/en/pt) for precision.
- The scope safeguard keeps the assistant within the Zabbix-maintenance domain
  (off-topic requests are politely redirected).

### Unchanged (invariant)
- Maintenance DATA (hosts, groups, schedule) is still extracted structurally and
  the bitmasks are computed deterministically by the backend core; the AI never
  computes bitmasks. `assistant_message` is conversational prose only.

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

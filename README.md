# Adhyantra

Adhyantra is a full-stack, subject-aware study application. The frontend is Next.js 16.2.1 with React 18.3.1, TypeScript, and the Pages Router. The backend is FastAPI with SQLAlchemy. Local development and deterministic tests use SQLite; deployed environments are expected to use PostgreSQL through the tracked `psycopg2-binary` driver unless SQLite is explicitly allowed for a small deployment.

UPSC has the deepest native knowledge-base coverage. SSC and Banking are selectable exam profiles, but their native material is limited and retrieval can fall back to the shared general-studies corpus. Treat those profiles as product scaffolding with partial content, not equivalent multi-exam corpus depth.

## What is included

- FastAPI and SQLAlchemy backend with SQLite/PostgreSQL database support
- Next.js 16.2.1, React 18.3.1, and TypeScript frontend using the Pages Router
- Local markdown knowledge base with dynamically discovered subject-scoped topics and shared-corpus fallback
- Gemini-first AI provider abstraction with Groq fallback, Mistral QA/testing support, and explicit mock fallback
- Email-OTP authentication over console, SMTP, or Resend, with DB-backed sessions
- Stripe/Razorpay billing adapters, premium entitlements and usage enforcement, disabled by default until configured
- Role-based content and operations administration endpoints
- Lesson exports, TTS audio jobs, and scene/narration ZIP packages; no encoded MP4 renderer
- Adaptive quiz difficulty, weak-topic detection, and lightweight revision planning
- Deterministic backend tests covering product, security, billing, media, operations, and setup behavior

## Project structure

```text
project-root/
  backend/
  frontend/
  docs/
  requirements.txt
  package-lock.json
  .env.example
  .env.staging.example
  README.md
```

## Environment variables

No environment variable is required for the safe local default: it uses SQLite, mock AI, console OTP delivery, disabled billing/TTS, and local media storage. The application reads an optional untracked `.env`, but clean setup and tests must not depend on a developer's existing file. Never commit or paste real secret values into documentation.

Conditionally required names:

- PostgreSQL: `EXAM_GURU_DB_URL`
- Gemini/Groq live AI: `GEMINI_API_KEY`, `GROQ_API_KEY`
- SMTP OTP: `EMAIL_FROM_ADDRESS`, `SMTP_HOST`; `SMTP_USERNAME` and `SMTP_PASSWORD` when the server requires authentication
- Resend OTP: `EMAIL_FROM_ADDRESS`, `RESEND_API_KEY`
- Stripe billing: `PAYMENT_PROVIDER`, `PAYMENT_PREMIUM_PRICE_ID`, `PAYMENT_STRIPE_SECRET_KEY`, `PAYMENT_STRIPE_WEBHOOK_SECRET`
- Razorpay billing: `PAYMENT_PROVIDER`, `PAYMENT_PREMIUM_PRICE_ID`, `PAYMENT_RAZORPAY_KEY_ID`, `PAYMENT_RAZORPAY_KEY_SECRET`, `PAYMENT_RAZORPAY_WEBHOOK_SECRET`
- OpenAI TTS: `TTS_PROVIDER`, `TTS_OPENAI_API_KEY`
- Deployed origins/security: `FRONTEND_ORIGIN`, `BACKEND_PUBLIC_URL`, `CORS_ALLOWED_ORIGINS`, `TRUSTED_HOSTS`, `SECURE_SESSION_COOKIES`

Optional configuration names are grouped in `.env.example`: `APP_ENV`, release metadata, AI provider/model/base-URL settings, `EXAM_GURU_EXAM`, `EXAM_GURU_SUBJECT`, frontend API/debug settings, session/cookie settings, OTP limits, SMTP/Resend settings, payment settings, TTS settings, media-worker/storage settings, and staging smoke-check settings. `.env.staging.example` documents the stricter deployed contract with blank secret fields.

Copy `.env.example` to `.env` in the project root if you want to override defaults for the backend.

```powershell
Copy-Item .env.example .env
```

Supported variables:

- `APP_ENV`: defaults to `development`. Supported canonical environments are `development`, `test`, `staging`, and `production`; aliases such as `dev`, `local`, `testing`, `stage`, and `prod` are normalized internally.
- `APP_VERSION`, `RELEASE_COMMIT`, `DEPLOYMENT_ID`: optional release metadata surfaced safely through health/readiness responses.
- `AI_PROVIDER`: `mock` by default. Use `gemini` for the primary live path, `groq` for the fallback live path, or `mistral` only for explicit local QA/testing.
- `AI_PROVIDER_CHAIN`: comma-separated provider route. The normal live chain is `gemini,groq,mock`; `mock` is appended automatically when omitted. Do not include `mistral` in staging or production chains.
- `GEMINI_MODEL`, `GEMINI_API_KEY`, `GEMINI_BASE_URL`: primary Gemini provider settings.
- `GROQ_MODEL`, `GROQ_API_KEY`, `GROQ_BASE_URL`: Groq fallback provider settings. Groq uses the shared OpenAI-compatible chat path.
- `MISTRAL_MODEL`, `MISTRAL_API_KEY`, `MISTRAL_BASE_URL`: testing-only Mistral provider settings for QA/comparison runs. Deployed config validation rejects `mistral` in staging or production provider chains.
- `OPENAI_MODEL`, `OPENAI_API_KEY`, `OPENAI_BASE_URL`: backward-compatible OpenAI provider settings. The backend posts OpenAI-compatible providers to `/chat/completions`.
- `EXAM_GURU_DB_URL`: defaults to the project-root SQLite file `./exam_guru.db`.
- `EXAM_GURU_SUBJECT`: defaults to `polity`.
- `EXAM_GURU_EXAM`: defaults to `upsc`.
- `NEXT_PUBLIC_API_BASE_URL`: frontend API base URL. The frontend already defaults to `http://127.0.0.1:8000`.
- `FRONTEND_ORIGIN`: backend CORS origin for the frontend. Production must use the deployed HTTPS frontend origin, not localhost.
- `BACKEND_PUBLIC_URL`: optional deployed backend URL used for deployment config validation.
- `CORS_ALLOWED_ORIGINS`: optional comma-separated extra allowed frontend origins. Wildcards are rejected because session cookies require credentialed CORS.
- `CORS_ALLOWED_METHODS`, `CORS_ALLOWED_HEADERS`, `CORS_MAX_AGE_SECONDS`: optional CORS allowlist tuning. Local development defaults to broad methods/headers; staging and production default to explicit method/header allowlists and reject `*`.
- `TRUSTED_HOSTS`: optional comma-separated backend Host header allowlist. In deployed environments, `BACKEND_PUBLIC_URL` also contributes the backend host so reverse-proxy Host checks can be enabled.
- `LOG_LEVEL`: optional backend log verbosity override. Supported values are `DEBUG`, `INFO`, `WARNING`, `ERROR`, and `CRITICAL`; when blank, the environment policy default is used.
- `SESSION_TTL_DAYS`: absolute DB-backed session lifetime. Values below 1 day are clamped to 1 day for safety.
- `SESSION_IDLE_TIMEOUT_MINUTES`: optional idle timeout. `0` keeps idle timeout disabled for local/dev compatibility.
- `SESSION_COOKIE_SAMESITE`: `lax` by default. Supported values are `lax`, `strict`, and `none`; `none` forces secure cookies.
- `SESSION_COOKIE_DOMAIN` / `SESSION_COOKIE_PATH`: optional cookie scope settings for deployments that need a shared domain or non-root path.
- `SECURE_SESSION_COOKIES`: force secure session cookies. `APP_ENV=staging` and `APP_ENV=production` also force secure cookies.
- `EMAIL_DELIVERY_MODE`: defaults to `console` for local development. Use `email` or `smtp` for real OTP email delivery. `EMAIL_OTP_DELIVERY_MODE` is still accepted as a backward-compatible alias.
- `EMAIL_TRANSPORT`: real-email transport selector. `smtp` and `resend` are implemented; `EMAIL_PROVIDER` is accepted as a compatibility alias. Console delivery is selected through `EMAIL_DELIVERY_MODE=console`, not as a deployed transport.
- `AUTH_DEV_RETURN_OTP`: defaults to `false`. Set it to `true` only with `EMAIL_DELIVERY_MODE=console` when you intentionally want the local auth response to expose the development OTP in the browser. It is ignored for real email delivery and suppressed in staging/production.
- `EMAIL_OTP_MAX_VERIFY_ATTEMPTS_PER_HOUR_PER_EMAIL`: caps verification attempts for one email in a rolling hour.
- `EMAIL_OTP_MAX_VERIFY_ATTEMPTS_PER_HOUR_PER_IP`: caps verification attempts from one connection in a rolling hour.
- `EMAIL_FROM_NAME`, `EMAIL_FROM_ADDRESS`, `EMAIL_REPLY_TO_ADDRESS`: sender and reply-to identity for real email delivery.
- `SMTP_HOST`, `SMTP_PORT`, `SMTP_USERNAME`, `SMTP_PASSWORD`, `SMTP_USE_TLS`, `SMTP_USE_SSL`, `SMTP_TIMEOUT_SECONDS`: SMTP transport settings used when real email delivery is enabled. `SMTP_USE_TLS=true` uses STARTTLS; `SMTP_USE_SSL=true` uses implicit TLS and skips STARTTLS.
- `RESEND_API_KEY`: Resend credential required only when `EMAIL_TRANSPORT=resend`. The pinned Resend 2.4.0 SDK supports the `resend.api_key` and `resend.Emails.send(...)` API used by the backend.
- `PAYMENT_PROVIDER`, `PAYMENT_TIMEOUT_SECONDS`, `PAYMENT_PREMIUM_PRICE_ID`: billing provider selection and shared checkout configuration. Billing stays disabled by default.
- `PAYMENT_STRIPE_SECRET_KEY`, `PAYMENT_STRIPE_WEBHOOK_SECRET`, `PAYMENT_STRIPE_BASE_URL`: Stripe checkout/webhook settings.
- `PAYMENT_RAZORPAY_KEY_ID`, `PAYMENT_RAZORPAY_KEY_SECRET`, `PAYMENT_RAZORPAY_WEBHOOK_SECRET`, `PAYMENT_RAZORPAY_BASE_URL`, `PAYMENT_RAZORPAY_TOTAL_COUNT`: Razorpay subscription/webhook settings.
- `TTS_PROVIDER`, `TTS_TIMEOUT_SECONDS`, `TTS_OUTPUT_FORMAT`, `TTS_OPENAI_MODEL`, `TTS_OPENAI_API_KEY`, `TTS_OPENAI_BASE_URL`, `TTS_OPENAI_VOICE`: optional TTS generation settings; disabled by default.
- `MEDIA_RENDER_OUTPUT_DIR`, `MEDIA_RENDER_WORKER_MODE`, `MEDIA_RENDER_WORKER_POLL_SECONDS`, `MEDIA_RENDER_CLAIM_LEASE_SECONDS`, `MEDIA_RENDER_WORKER_HEARTBEAT_SECONDS`, `MEDIA_RENDER_WORKER_STALE_AFTER_SECONDS`, `MEDIA_RENDER_ARTIFACT_RETENTION_HOURS`: local/mounted filesystem media configuration.
- `ALLOW_MOCK_AI_IN_PRODUCTION`: defaults to `false`. Set to `true` only when intentionally deploying without live AI.
- `ALLOW_SQLITE_IN_PRODUCTION`: defaults to `false`. Set to `true` only for an intentional small SQLite deployment.
- `STAGING_BACKEND_URL`, `STAGING_FRONTEND_URL`, `STAGING_SMOKE_EMAIL`, `STAGING_SMOKE_SCENARIO`, `STAGING_SMOKE_TIMEOUT_SECONDS`: smoke-check inputs used by `npm run smoke:staging` and `npm run smoke:scenario`. Keep `STAGING_SMOKE_EMAIL` as a dedicated deployed verification mailbox; local deterministic demo accounts intentionally use the separate `@adhyantra.test` domain.

For local real-email testing, copy `.env.example`, select `EMAIL_DELIVERY_MODE` and `EMAIL_TRANSPORT`, then supply only the corresponding SMTP or Resend fields in the untracked `.env`.

Deployment config validation runs at backend startup when `APP_ENV=staging` or `APP_ENV=production`. The backend now resolves `APP_ENV` through one environment policy layer, so cookies, CORS, email delivery, dev OTP visibility, AI strictness, SQLite strictness, and default log level are controlled in one place. Staging and production fail fast for unsafe deployed defaults such as console email delivery, unsupported real-email transports, localhost CORS origins, or non-HTTPS deployed origins. Production additionally blocks mock AI and local SQLite unless explicitly allowed. Staging emits warnings for mock AI and SQLite so a staging box can boot intentionally while still making production gaps visible.

Internal compatibility note: a few env var names, cookie names, and local database files intentionally still use `EXAM_GURU_*` or `exam_guru` identifiers. They are runtime compatibility surfaces, not user-facing branding, and should only be renamed in a coordinated migration.

If `AI_PROVIDER=gemini` and `AI_PROVIDER_CHAIN` is left empty, the backend uses the default live route `gemini,groq,mock`. If Gemini fails and Groq is configured, the response is generated by Groq and labeled with Groq provider metadata. If all configured live providers are unavailable, the app gracefully falls back to explicit mock mode so local development still works.

The normal live provider chain uses the names `AI_PROVIDER`, `AI_PROVIDER_CHAIN`, `GEMINI_API_KEY`, and `GROQ_API_KEY`. Mistral remains local QA/testing-only. Use `.env.example` as the authoritative name/default reference rather than copying credentials from documentation.

## Backend setup

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python -m pytest
python -m uvicorn backend.main:app --reload
```

On macOS/Linux, activate with `source .venv/bin/activate`. The root `requirements.txt` delegates to `backend/requirements.txt`; install from the root so local and deployed setup use the same declaration. `python -m pytest` is the canonical backend-suite command. `pytest.ini` pins discovery to `backend/tests`, disables the repository cache, and keeps pytest temporary files under the ignored `.test-runtime/` directory. The test harness establishes isolated SQLite, mock-AI, console-email, disabled-payment/TTS, and per-process media paths before application modules are imported; it does not consume the developer's `.env` values.

If you are on Windows PowerShell and `npm` resolves differently on your machine, use `npm.cmd`.

Backend endpoints:

- `GET /health`: backward-compatible lightweight health and safe runtime summary.
- `GET /health/live`: lightweight liveness check for process/runtime boot state.
- `GET /health/ready`: readiness check for deployment monitors; verifies boot state, DB ping/schema, and config sanity without exposing secrets.
- `GET /ready`: alias for `GET /health/ready`.
- `GET /api/subjects`
- `GET /api/topics`
- `POST /api/tutor/explain`
- `POST /api/tutor/doubt`
- `POST /api/test/generate`
- `POST /api/test/submit`
- `GET /api/progress/summary`
- `GET /api/progress/history`

## Frontend setup

Open a second terminal:

```powershell
npm ci
npm run typecheck
npm run build
npm run start
```

Run these commands from the repository root. `npm ci` installs exactly from the tracked workspace lockfile and does not reuse packages from an existing `node_modules`. The frontend runs at `http://localhost:3000`.

If you want hot reload and your environment supports the Next.js dev worker process, you can also run:

```powershell
npm run dev
```

## Current product and deployment scope

- Authentication uses expiring email OTP challenges and DB-backed session records. Local console delivery is for development only; SMTP and Resend are the external transports.
- Premium lesson modes, exports, and media jobs are protected by centralized authentication, entitlement, and usage enforcement. Billing adapters support Stripe and Razorpay, but the default provider is disabled and real checkout requires provider credentials and verified webhooks.
- Admin APIs are role-gated for content review/import/workflow and operational visibility. They are not a substitute for an external identity or secrets-management platform.
- Audio jobs can produce TTS files when configured. Video-style jobs produce downloadable ZIP archives containing scene manifests/assets and optional narration audio. They are not MP4 files or cinematic video encoding.
- UPSC is the primary native corpus. SSC and Banking exam profiles reuse parts of the shared corpus when native exam-specific files are absent.
- The repository contains provider-neutral staging scripts and a runbook, but no Vercel or Render service definition or verified public deployment metadata. Do not infer that either deployment exists or is healthy from local configuration.
- Alembic provides a reviewed PostgreSQL migration baseline while current API and worker startup still use SQLAlchemy table creation plus SQLite compatibility updates. Managed PostgreSQL rollout remains a separate, backup-first operation; see `docs/migrations.md`.

## Staging deployment checks

- Use `.env.staging.example` as the staging environment contract. Values should be supplied through the staging platform secret manager or process environment, not committed with real secrets.
- The staging example is intentionally not launchable as copied: preflight fails until `EXAM_GURU_DB_URL` is supplied, and live AI/email/billing credentials are required only for the providers enabled for that deployment.
- Use `npm run ops:preflight -- --env-file .env.staging` before launch to reuse the current API config, worker config, media storage, and readiness expectations in one place.
- Staging must use HTTPS `FRONTEND_ORIGIN`, HTTPS `BACKEND_PUBLIC_URL`, explicit `CORS_ALLOWED_ORIGINS`, explicit CORS methods/headers, `TRUSTED_HOSTS` or `BACKEND_PUBLIC_URL` for Host checks, real `EMAIL_DELIVERY_MODE=email`, either SMTP or Resend with its required settings, and `SECURE_SESSION_COOKIES=true`.
- If `MEDIA_RENDER_WORKER_MODE=external`, use an absolute shared `MEDIA_RENDER_OUTPUT_DIR` that both API and worker processes can read and write. A Linux deployment might use a mounted path like `/var/lib/adhyantra/media-renders`; the staging template uses a Windows-safe absolute example so local preflight commands stay readable too.
- API and worker startup create and verify the configured local or mounted media directory idempotently before accepting render work. Health/readiness checks only inspect storage and never create it. Object-storage URIs such as `s3://...` are not supported by the current filesystem renderer.
- `GET /health/live` is the lightweight process check. `GET /health/ready` is the deployment gate because it verifies boot state, DB readiness, and config sanity.
- Readiness responses include a safe `summary` with boot status, DB status, config issue counts, email mode, session/CORS posture, worker expectations, and media pipeline availability. Structured logs use `event=...` fields and redact secret-shaped keys before writing.
- Full staging launch guidance lives in `docs/staging-runbook.md`.
- Start the worker separately only when the worker mode is external. Embedded mode keeps queue execution inside the API process.
- Preflight staging config before launching:

```powershell
npm run staging:config -- --env-file .env.staging
```

- Preflight DB readiness and current schema-management posture:

```powershell
npm run db:preflight -- --env-file .env.staging
```

- Apply the lightweight schema path before first boot or after pulling schema-related code:

```powershell
npm run db:apply-schema -- --env-file .env.staging
```

- Start staging-style backend and frontend processes:

```powershell
npm run staging:backend -- --env-file .env.staging
npm run staging:worker -- --env-file .env.staging
npm run staging:frontend -- --env-file .env.staging --build
```

- `staging:worker` should be used only when `MEDIA_RENDER_WORKER_MODE=external`. The worker wrapper validates that startup assumption before it launches the process.
- The new ops aliases keep the same runtime behavior but make the operational path easier to remember:

```powershell
npm run ops:preflight -- --env-file .env.staging
npm run ops:backend -- --env-file .env.staging
npm run ops:worker -- --env-file .env.staging
npm run ops:frontend -- --env-file .env.staging --build
npm run ops:smoke
```

- Run the smoke script against already-running staging services:

```powershell
$env:STAGING_BACKEND_URL="https://api-staging.example.com"
$env:STAGING_FRONTEND_URL="https://staging.example.com"
npm run smoke:staging
```

- To include a real OTP delivery check, set `STAGING_SMOKE_EMAIL` to a dedicated staging verification mailbox. The smoke script requests an OTP and reports delivery mode and timing metadata, but it never prints the OTP code:

```powershell
$env:STAGING_SMOKE_EMAIL="staging-smoke@example.com"
npm run smoke:staging
```

- To run the full pre-rollout smoke flow, use a dedicated staging smoke account and enter the OTP received by email. This verifies OTP login, `/api/auth/me`, settings/profile persistence, tutor explanation, quiz generation/submission, progress summary, Today's Plan, revision due, coach summary, and logout:

```powershell
$env:STAGING_SMOKE_EMAIL="staging-smoke@example.com"
npm run smoke:staging -- --interactive-otp --require-auth-flow
```

- For repeatable local QA against deterministic demo data, load a named scenario first and then run the scenario-aware smoke path. This is a local demo workflow, not a staging-user-data workflow:

```powershell
npm run db:load-scenarios -- --reset-first --yes --scenario weak_topic_repair
npm run smoke:scenario -- --backend-url http://127.0.0.1:8000 --frontend-url http://localhost:3000 --scenario weak_topic_path
```

- If the frontend is not deployed yet, run `python scripts/staging_smoke.py --skip-frontend --backend-url https://api-staging.example.com`.
- Run authenticated smoke checks against the public HTTPS backend URL when staging/prod secure cookies are enabled; direct HTTP backend URLs cannot round-trip `Secure` session cookies.

## Local data hygiene

- Adhyantra now treats runtime data as separate lanes:
  - `local_dev_reset_data`: clean local SQLite state after reset or before first boot
  - `deterministic_demo_data`: intentionally seeded local demo/QA state with an active demo marker
  - `ordinary_local_runtime_data`: normal user-owned local product state
  - `staging_verification_data`: deployed smoke-account data used only for staging verification
- `demo_runtime_state.py status` and `npm run db:preflight` now report the current local data lane, note, and lightweight user/history counts so it is easier to see when local demo seeds and ordinary runtime data have been mixed.
- The only intended local SQLite database path is the project-root file `./exam_guru.db`.
- `backend/exam_guru.db` is a legacy path and should not be used for normal local runs.
- Markdown knowledge-base files are seeded content. Quiz history, progress, revision signals, and coach outputs are not auto-seeded.
- PostgreSQL now has a reviewed Alembic model/schema baseline. The current runtime still creates missing tables and applies compatibility updates to older SQLite development databases; changing startup schema behavior is intentionally deferred.
- `db:reset` and demo seeding are intentionally local-only and are blocked when `APP_ENV=staging` or `APP_ENV=production`.
- Local reset creates a timestamped SQLite backup first unless `--skip-backup` is passed.
- For managed staging/production databases, use provider-native backups and follow `docs/migrations.md`. Do not stamp or migrate an existing database until its schema compatibility is independently verified, and do not use local reset or demo seed tooling.
- Use the safer wrapper workflow for local hygiene:
  - inspect current lane: `python scripts/demo_runtime_state.py status`
  - reset to a clean local lane: `python scripts/demo_runtime_state.py reset --yes`
  - load deterministic demo accounts: `python scripts/demo_runtime_state.py seed-accounts --reset-first --yes`
  - load named deterministic scenarios: `python scripts/demo_runtime_state.py load-scenarios --reset-first --yes --scenario <key>`
- To start from a clean local database intentionally:

```powershell
python scripts/demo_runtime_state.py reset --yes
```

- To create a timestamped backup of the active local SQLite database before reset/seed/migration work:

```powershell
python scripts/backup_sqlite_db.py
```

- To create explicit demo quiz/progress data for screenshots or manual testing:

```powershell
python scripts/demo_runtime_state.py seed-accounts --reset-first --yes
```

- Running the deterministic demo workflows writes `.exam_guru_demo_seed.json`, and the local runtime status now treats that DB as `deterministic_demo_data` until it is reset or replaced.
- The same workflows are also available through the root package scripts:

```powershell
npm run db:runtime-status
npm run db:reset
npm run db:backup
npm run db:preflight
npm run db:apply-schema
npm run db:seed-demo-accounts -- --reset-first --yes
npm run db:load-scenarios -- --reset-first --yes --scenario fresh_start
```
## Subject layer

- Supported subject codes now come from one backend registry: `polity`, `economy`, `history`, `geography`, `environment`
- `GET /api/subjects` returns one clean subject list with `id`, `code`, `label`, optional `description`, availability, topic count, and chapter count for the frontend
- The app still defaults to `polity` when no subject is provided
- Core API routes now accept or return `subject`, and the backend internally resolves `subject + chapter + topic` for study, quiz, progress, revision, and coach logic
- On SQLite startup, legacy rows with missing subject or chapter values are safely backfilled to `polity` and `General`
- The Tutor, Test, and Progress pages keep the existing flow and can scope requests by subject without a major UI redesign

## Topic discovery

Topics are discovered dynamically by scanning markdown files recursively under:

```text
backend/knowledge_base/<subject>/<chapter>/**/*.md
```

The app infers:

- the subject from the top-level folder name
- the chapter from nested folders or optional markdown metadata
- the topic from markdown front matter, the first `# Heading`, or the filename

To add a new subject topic:

1. Create or reuse a subject folder like `backend/knowledge_base/economy/`
2. Add a chapter folder like `mechanics/`
3. Drop a `.md` file such as `newtons_laws.md`
4. Include a title as front matter or a first-level heading
5. Restart the backend if it is already running

The topic will appear automatically in `GET /api/topics?subject=...`, and the subject will surface in `GET /api/subjects` when it has markdown content.

Subject discovery is hybrid by design:

- the supported subject list comes from one centralized registry in `backend/config.py`
- availability, topic count, and chapter count are discovered dynamically from `backend/knowledge_base/<subject>/`

## Hybrid AI behavior

`POST /api/tutor/explain`

- tries to retrieve knowledge-base context for the selected topic
- sends topic plus context to the AI layer using a dedicated provider abstraction
- returns a deeper teaching response including simple explanation, detailed explanation, examples, common traps, memory hooks, and practice questions
- still returns an explanation even if no local context is found
- enforces authentication and premium entitlement checks for premium lesson modes before lesson generation; standard lesson modes retain their existing access policy

`POST /api/tutor/doubt`

- accepts any student question
- searches the knowledge base using topic names, question keywords, and partial matches
- returns a tutor-style answer with direct answer, explanation, common confusion, exam tip, and follow-up prompt
- returns `answer_mode = syllabus_grounded` when local context is found
- returns `answer_mode = general_ai_answer` when no local context is found
- uses the LLM even for unknown questions when OpenAI is configured
- also includes `answer_source` for backward compatibility with the current frontend

`GET /api/progress/summary`

- keeps the existing recent quizzes, weak topics, and recommended next step fields
- also returns `strong_topics`, `recommended_next_reason`, and `revision_recommendations`
- enriches each topic row with recent accuracy, repeated mistakes, recent failed attempts, and revision timing

## Mock mode

If `AI_PROVIDER=mock`, if `AI_PROVIDER_CHAIN=mock`, or if no configured live provider in the chain has usable credentials, the backend uses built-in mock logic:

- explanations are created from the local markdown files
- doubt answers are generated from the same local topic notes
- unknown-topic explanations and doubts still return a generic fallback answer
- quizzes come from a small in-code bank plus simple revision questions

This means the prototype is fully usable offline once dependencies are installed.

## Adaptive learning logic

- Quiz difficulty follows a simple reusable rule:
  - above 80% accuracy: `hard`
  - 50% to 80% accuracy: `medium`
  - below 50% accuracy: `easy`
- One non-weak submitted attempt is treated as thin evidence and stays on the baseline `medium`; at least two reliable attempts are required before a topic can move to `hard`. A single below-50% attempt can still use `easy` because it meets the documented recovery threshold.
- Recent attempts are also considered so the next quiz reflects how the student is doing now, not only lifetime averages.
- Weak topics are detected from a mix of:
  - low overall accuracy
  - repeated weak areas in recent quiz reviews
  - multiple recent failed attempts
- Revision recommendations use lightweight spaced intervals:
  - 1 day for weak or newly studied topics
  - 3 days for medium-stability topics
  - 7 days for stronger topics that still need retention checks
- The Progress page surfaces weak topics, strong topics, revision recommendations, and the best next topic to study.
- Legacy lesson-export aliases remain accepted. Export metadata preserves the exact requested alias while `export_target` and response headers expose the canonical format used for entitlement checks, filenames, and media types.

## Reliability Notes

- The backend logs validation errors, handled HTTP errors, and unexpected exceptions with clear route details.
- If the AI provider fails or returns incomplete JSON, the tutor services fall back to safe mock responses instead of crashing.
- If a quiz is requested for an unknown topic, the API returns a clean error listing available topics.
- The frontend shows friendly error messages for network failures, empty responses, and malformed API payloads.

## AI service design

- `backend/services/ai_service.py` owns prompt construction, provider selection, response validation, and mock fallback.
- `backend/ai_client.py` contains the low-level Gemini client, shared OpenAI-compatible provider client, provider router, and request-local provider metadata helpers.
- `POST /api/tutor/explain` and `POST /api/tutor/doubt` both use retrieved context when present and still respond when context is absent.
- If a live provider call fails or returns incomplete JSON, the backend logs the error and returns the existing mock response shape instead of breaking the endpoint.

## Validation

Canonical checks for the current stabilization pass:

- `python -m pytest`
- `npm run build`
- `npm run typecheck`
- backend boot with `uvicorn backend.main:app`
- frontend boot with `npm run start`
- full API smoke flow for topics, tutor, quiz, submit, summary, and history
- adaptive flow smoke:
  - quiz difficulty follows stored topic performance
  - weak topics surface in progress
  - revision recommendations appear in progress
  - next-topic recommendations update from recent performance
- AI service validated in both modes:
  - missing live provider credentials fall back to explicit mock mode
  - configured Gemini, Groq, Mistral testing, and OpenAI-compatible provider paths can be exercised with mocked provider responses in tests

## App flow

1. Open `http://localhost:3000`.
2. Let the frontend load available topics dynamically from the knowledge base.
3. Go to the Tutor page and explain a topic like `Fundamental Rights`.
4. Ask a follow-up doubt in the chat box.
5. Go to the Test page and generate a 5 or 10 question MCQ quiz.
6. Submit answers and review explanations.
7. Open the Progress page to see recent quizzes, topic accuracy, weak topics, and the next recommendation.

## Notes and extension points

- Retrieval is intentionally simple and file-based. It scans markdown files recursively and ranks matches by topic name, filename, question keywords, and partial content overlap.
- Difficulty adapts from stored topic accuracy:
  - above 80%: hard
  - 50% to 80%: medium
  - below 50%: easy with revision recommendation
- The backend is easy to extend with more subjects, more knowledge files, or a richer AI client.

## Version 5 coach layer

Version 5 keeps the Tutor, Test, and Progress flows intact and adds a lightweight study-coach layer on top of the existing adaptive logic.

New additive endpoints:

- `GET /api/plan/today`: returns a focus topic, revision topics, one practice action, one quiz action, and a short next-step guide for the current day.
- `GET /api/revision/due`: groups revision work into `overdue`, `due_now`, and `due_soon` buckets.
- `GET /api/coach/summary`: returns what to study today, what to revise, weak areas, the current trend status, the next action, and short constructive warnings.
- `GET /api/performance/trends`: returns overall and topic-level trend labels from recent quiz history.

The Progress page now uses those endpoints to show:

- Todayâ€™s Plan
- revision-due buckets
- coach summary
- coaching warnings when they are justified
- overall and topic-level trend signals

The coaching layer is intentionally heuristic-based. It does not use notifications, background jobs, or calendar integrations.

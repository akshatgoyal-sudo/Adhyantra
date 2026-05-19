# Adhyantra

Adhyantra is a deliberately small local full-stack MVP for UPSC-style study. It currently ships with UPSC Polity content plus a small History starter slice, and the app now has a basic subject layer so quizzes, progress, revision, and coaching data are all scoped by subject. It teaches a topic, answers follow-up doubts with a hybrid AI flow, generates MCQ quizzes, evaluates answers, stores quiz history in SQLite, and adapts revision and next-step recommendations based on student performance.

## What is included

- FastAPI backend with SQLite storage and modular services
- Next.js frontend with Tutor, Test, and Progress pages
- Local markdown knowledge base with dynamically discovered subject-scoped topics (currently Polity plus a small History starter slice)
- Gemini-first AI provider abstraction with Groq fallback, Mistral QA/testing support, and explicit mock fallback
- Configurable AI provider settings through environment variables
- Adaptive quiz difficulty, weak-topic detection, and lightweight revision planning
- Basic backend tests for topics, tutor fallbacks, quiz flow, and adaptive logic

## Project structure

```text
project-root/
  backend/
  frontend/
  .env.example
  README.md
```

## Environment variables

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
- `EMAIL_TRANSPORT`: real-email transport selector. `smtp` is implemented now; `EMAIL_PROVIDER` is accepted as a compatibility alias, and future provider-backed transports should be added behind this setting instead of branching auth code.
- `AUTH_DEV_RETURN_OTP`: defaults to `false`. Set it to `true` only with `EMAIL_DELIVERY_MODE=console` when you intentionally want the local auth response to expose the development OTP in the browser. It is ignored for real email delivery and suppressed in staging/production.
- `EMAIL_OTP_MAX_VERIFY_ATTEMPTS_PER_HOUR_PER_EMAIL`: caps verification attempts for one email in a rolling hour.
- `EMAIL_OTP_MAX_VERIFY_ATTEMPTS_PER_HOUR_PER_IP`: caps verification attempts from one connection in a rolling hour.
- `EMAIL_FROM_NAME`, `EMAIL_FROM_ADDRESS`, `EMAIL_REPLY_TO_ADDRESS`: sender and reply-to identity for real email delivery.
- `SMTP_HOST`, `SMTP_PORT`, `SMTP_USERNAME`, `SMTP_PASSWORD`, `SMTP_USE_TLS`, `SMTP_USE_SSL`, `SMTP_TIMEOUT_SECONDS`: SMTP transport settings used when real email delivery is enabled. `SMTP_USE_TLS=true` uses STARTTLS; `SMTP_USE_SSL=true` uses implicit TLS and skips STARTTLS.
- `ALLOW_MOCK_AI_IN_PRODUCTION`: defaults to `false`. Set to `true` only when intentionally deploying without live AI.
- `ALLOW_SQLITE_IN_PRODUCTION`: defaults to `false`. Set to `true` only for an intentional small SQLite deployment.
- `STAGING_BACKEND_URL`, `STAGING_FRONTEND_URL`, `STAGING_SMOKE_EMAIL`, `STAGING_SMOKE_SCENARIO`, `STAGING_SMOKE_TIMEOUT_SECONDS`: smoke-check inputs used by `npm run smoke:staging` and `npm run smoke:scenario`. Keep `STAGING_SMOKE_EMAIL` as a dedicated deployed verification mailbox; local deterministic demo accounts intentionally use the separate `@adhyantra.test` domain.

Example `.env` for local real OTP email delivery:

```text
EMAIL_DELIVERY_MODE=email
EMAIL_TRANSPORT=smtp
AUTH_DEV_RETURN_OTP=false
EMAIL_FROM_ADDRESS=hello@your-domain.example
SMTP_HOST=smtp.your-provider.example
SMTP_PORT=587
SMTP_USERNAME=your_smtp_username
SMTP_PASSWORD=your_smtp_password
SMTP_USE_TLS=true
SMTP_USE_SSL=false
```

Deployment config validation runs at backend startup when `APP_ENV=staging` or `APP_ENV=production`. The backend now resolves `APP_ENV` through one environment policy layer, so cookies, CORS, email delivery, dev OTP visibility, AI strictness, SQLite strictness, and default log level are controlled in one place. Staging and production fail fast for unsafe deployed defaults such as console email delivery, unsupported real-email transports, localhost CORS origins, or non-HTTPS deployed origins. Production additionally blocks mock AI and local SQLite unless explicitly allowed. Staging emits warnings for mock AI and SQLite so a staging box can boot intentionally while still making production gaps visible.

Internal compatibility note: a few env var names, cookie names, and local database files intentionally still use `EXAM_GURU_*` or `exam_guru` identifiers. They are runtime compatibility surfaces, not user-facing branding, and should only be renamed in a coordinated migration.

If `AI_PROVIDER=gemini` and `AI_PROVIDER_CHAIN` is left empty, the backend uses the default live route `gemini,groq,mock`. If Gemini fails and Groq is configured, the response is generated by Groq and labeled with Groq provider metadata. If all configured live providers are unavailable, the app gracefully falls back to explicit mock mode so local development still works.

Example `.env` for the normal live provider chain:

```text
AI_PROVIDER=gemini
AI_PROVIDER_CHAIN=gemini,groq,mock
GEMINI_API_KEY=your_gemini_key_here
GROQ_API_KEY=your_groq_key_here
GEMINI_MODEL=gemini-1.5-flash
GROQ_MODEL=llama-3.1-8b-instant
```

Example `.env` for local Mistral QA/testing only:

```text
APP_ENV=development
AI_PROVIDER=mistral
AI_PROVIDER_CHAIN=mistral,mock
MISTRAL_API_KEY=your_mistral_key_here
MISTRAL_MODEL=mistral-small-latest
```

Example `.env` for local mock mode:

```text
AI_PROVIDER=mock
AI_PROVIDER_CHAIN=mock
```

## Backend setup

```powershell
python -m pip install -r requirements.txt
pytest backend/tests
uvicorn backend.main:app --reload
```

If you are on Windows PowerShell and `npm` or `pytest` resolves differently on your machine, use `npm.cmd` and `python -m pytest`.

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
npm install
npm run build
npm run start
```

The frontend runs at `http://localhost:3000`.

If you want hot reload and your environment supports the Next.js dev worker process, you can also run:

```powershell
npm run dev
```

## Staging deployment checks

- Use `.env.staging.example` as the staging environment contract. Values should be supplied through the staging platform secret manager or process environment, not committed with real secrets.
- Use `npm run ops:preflight -- --env-file .env.staging` before launch to reuse the current API config, worker config, media storage, and readiness expectations in one place.
- Staging must use HTTPS `FRONTEND_ORIGIN`, HTTPS `BACKEND_PUBLIC_URL`, explicit `CORS_ALLOWED_ORIGINS`, explicit CORS methods/headers, `TRUSTED_HOSTS` or `BACKEND_PUBLIC_URL` for Host checks, real `EMAIL_DELIVERY_MODE=email`, `EMAIL_TRANSPORT=smtp` with valid SMTP settings, and `SECURE_SESSION_COOKIES=true`.
- If `MEDIA_RENDER_WORKER_MODE=external`, use an absolute shared `MEDIA_RENDER_OUTPUT_DIR` that both API and worker processes can read and write. A Linux deployment might use a mounted path like `/var/lib/adhyantra/media-renders`; the staging template uses a Windows-safe absolute example so local preflight commands stay readable too.
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
- The current schema strategy is lightweight: SQLAlchemy creates missing tables and the backend applies compatibility updates for older SQLite development databases. No external migration framework is installed yet.
- `db:reset` and demo seeding are intentionally local-only and are blocked when `APP_ENV=staging` or `APP_ENV=production`.
- Local reset creates a timestamped SQLite backup first unless `--skip-backup` is passed.
- For managed staging/production databases, use provider-native backups and run `db:preflight` / `db:apply-schema`; do not use local reset or demo seed tooling.
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

These checks passed during the current stabilization pass:

- `pytest backend/tests`
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

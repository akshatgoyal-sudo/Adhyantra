# Adhyantra Staging Runbook

This runbook is provider-neutral. It assumes a staging host or process manager can run one backend process and one frontend process, with HTTPS handled by a reverse proxy or platform edge.

## 1. Prepare Environment

Create a real staging env file or secret set from the template:

```powershell
Copy-Item .env.staging.example .env.staging
```

The example is a contract, not a deployable configuration. Its blank `EXAM_GURU_DB_URL` deliberately fails preflight until a staging database is selected; provider secrets must remain in the platform secret store or untracked staging file.

Fill real values for the database, selected AI providers, one supported email transport, public URLs, CORS, and trusted hosts. Do not commit `.env.staging`.

Minimum staging expectations:

- `APP_ENV=staging`
- HTTPS `FRONTEND_ORIGIN` and `BACKEND_PUBLIC_URL`
- explicit `CORS_ALLOWED_ORIGINS`
- `TRUSTED_HOSTS` containing the backend public host
- `EMAIL_DELIVERY_MODE=email` and either `EMAIL_TRANSPORT=smtp` or `EMAIL_TRANSPORT=resend`
- SMTP requires the documented `SMTP_*` settings; Resend requires `RESEND_API_KEY`
- `SECURE_SESSION_COOKIES=true`
- `AUTH_DEV_RETURN_OTP=false`

If the backend is reached directly during a dry run, include that direct host in `TRUSTED_HOSTS`. For real staging, route traffic through HTTPS/reverse proxy.

This runbook is platform-neutral. The repository does not contain Vercel or Render service configuration, and following these steps does not establish that either platform is currently deployed or healthy.

## 2. Deployment Preflight

Run the combined deployment preflight first:

```powershell
npm run ops:preflight -- --env-file .env.staging
```

This reuses the current API config, worker config, media storage, and readiness expectations in one place before you start any long-running process.

The preflight prints:

- whether the API config is safe enough for staging
- whether a separate worker is expected
- whether the media storage path is usable
- the health/readiness URLs to check after launch
- the recommended backend, worker, frontend, DB, and smoke commands

## 3. Preflight Config

Run config validation before launching:

```powershell
npm run staging:config -- --env-file .env.staging
```

This checks the same staging/prod safety rules the backend enforces at startup. Errors should block launch. Warnings should be reviewed before exposing staging to users.

## 4. Preflight DB And Schema

Inspect DB readiness before launching:

```powershell
npm run db:preflight -- --env-file .env.staging
```

Apply the current lightweight schema path:

```powershell
npm run db:apply-schema -- --env-file .env.staging
```

Current schema discipline:

- SQLAlchemy creates missing tables from backend models.
- SQLite development DBs also receive compatibility updates for older local schemas.
- No destructive schema migration runs automatically.
- Managed staging/production databases should use provider-native backups before schema-related deploys.
- `npm run db:reset` and demo seeding are local-only and blocked under deployed `APP_ENV` values.

## 5. Launch Backend

Start the backend with reverse-proxy-aware uvicorn flags:

```powershell
npm run staging:backend -- --env-file .env.staging
```

Equivalent direct command:

```powershell
python scripts/run_staging_backend.py --env-file .env.staging --host 0.0.0.0 --port 8000
```

The script enables uvicorn proxy headers by default and passes `UVICORN_FORWARDED_ALLOW_IPS`, which should be scoped to trusted proxy IPs in production-like deployments.

## 6. Launch Worker

If `MEDIA_RENDER_WORKER_MODE=external`, start the media worker as a separate long-running process:

```powershell
npm run staging:worker -- --env-file .env.staging
```

Equivalent direct command:

```powershell
python scripts/run_staging_worker.py --env-file .env.staging
```

The worker wrapper:

- reuses the same env-file loading path as the backend/frontend helpers
- validates worker-role config before launch
- refuses to start in non-`external` worker mode by default, which helps avoid duplicate queue processors
- checks that the configured media storage path is usable before the worker begins polling

If `MEDIA_RENDER_WORKER_MODE=embedded`, do not run this separate worker process. The API process already owns queue execution in that mode.

## 7. Launch Frontend

Build and run the frontend with staging API config:

```powershell
npm run staging:frontend -- --env-file .env.staging --build
```

Equivalent direct command:

```powershell
python scripts/run_staging_frontend.py --env-file .env.staging --build --host 0.0.0.0 --port 3000
```

The script sets `NEXT_PUBLIC_API_BASE_URL` from staging env values before building/starting.

## 8. Media Storage Expectations

When API and worker run as separate processes:

- use `MEDIA_RENDER_WORKER_MODE=external`
- set `MEDIA_RENDER_OUTPUT_DIR` to an absolute shared path or mounted volume
- avoid project-local output directories for long-running deployed workloads
- make sure both API and worker can read completed artifacts and write new output safely
- on Linux hosts, a mounted path like `/var/lib/adhyantra/media-renders` is a good fit; the template uses a Windows-safe absolute example so local preflight checks stay usable too

The deployment preflight and worker wrapper both surface storage problems before a learner sees them through failed media jobs.

## 9. Reverse Proxy Assumptions

The reverse proxy or platform edge should:

- terminate HTTPS before traffic reaches the app processes
- forward the public backend host expected by `TRUSTED_HOSTS`
- preserve or set `X-Forwarded-For` and `X-Forwarded-Proto`
- route frontend traffic to the Next.js process
- route backend API and health traffic to the FastAPI process
- keep backend and frontend origins aligned with `CORS_ALLOWED_ORIGINS`

## 10. Smoke Checks

After both processes are reachable:

```powershell
$env:STAGING_BACKEND_URL="https://api-staging.example.com"
$env:STAGING_FRONTEND_URL="https://staging.example.com"
npm run smoke:staging
```

To include OTP delivery without printing the code:

```powershell
$env:STAGING_SMOKE_EMAIL="staging-smoke@example.com"
npm run smoke:staging
```

To run the full authenticated pre-rollout smoke, use a dedicated staging smoke account and enter the OTP from the delivered email:

```powershell
$env:STAGING_SMOKE_EMAIL="staging-smoke@example.com"
npm run smoke:staging -- --interactive-otp --require-auth-flow
```

The full smoke verifies:

- `GET /health/live`
- `GET /health/ready`
- unauthenticated `/api/auth/me` rejection
- OTP request and OTP verification
- authenticated `/api/auth/me`
- settings persistence
- profile persistence
- tutor explanation for the configured smoke topic
- quiz generation without answer leakage
- quiz submission
- progress summary after the smoke quiz
- Today's Plan, revision due, and coach summary for the same exam/subject
- logout and post-logout `/api/auth/me` rejection

Use `STAGING_SMOKE_EXAM`, `STAGING_SMOKE_SUBJECT`, and `STAGING_SMOKE_TOPIC` to adjust the product slice without editing the script.
Run authenticated smoke checks against the public HTTPS backend URL when staging/prod secure cookies are enabled; direct HTTP backend URLs cannot round-trip `Secure` session cookies.

Health endpoints:

- `GET /health/live`: lightweight process check
- `GET /health/ready`: deployment gate with boot, DB, config, email, session/CORS, worker, and media-pipeline summary

## 11. Rollback And Data Notes

- Keep database backups outside the app process manager until a migration tool is added.
- For SQLite staging only, run `npm run db:backup` before schema-related deploys. Do not reset or demo-seed staging data.
- Prefer a managed Postgres-compatible database for real staging and production.
- For managed databases, take a provider snapshot before `db:apply-schema` or any schema-related deploy.

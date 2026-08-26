# Render Free and durable media deployment

The first-launch topology is one Render Free web service running one Uvicorn process and Adhyantra's embedded media dispatcher. Supabase supplies PostgreSQL through its session pooler and a separately created private Storage bucket. Vercel hosts the frontend. Do not add a Render worker, disk, database, Redis, cron service, or pre-deploy command for this topology.

## Why durable storage is required

Render Free filesystems are ephemeral. `MEDIA_RENDER_OUTPUT_DIR=/tmp/adhyantra-media` is working space only: a restart, redeploy, or service replacement can discard it. With `MEDIA_STORAGE_BACKEND=supabase`, completed audio and scene/narration ZIP packages are uploaded before a job is marked complete. The API authorizes the user and proxies the private object back with the existing filename, content type, and render metadata. This retains the existing client contract but consumes Render outbound bandwidth.

Create the Storage bucket manually in Supabase and keep it private. The application validates access but never creates, publicizes, or deletes the bucket. Never put `SUPABASE_SERVICE_ROLE_KEY` in Vercel, a `NEXT_PUBLIC_*` variable, source control, logs, or API responses.

## Render environment

`render.yaml` defines exactly one free Python web service in Singapore, matching a Supabase `ap-southeast-1` deployment. Confirm the region in the Render dashboard before creation. Enter every `sync: false` value in Render's secret/configuration UI.

Required values are `APP_ENV=production`, `EXAM_GURU_DB_URL` (the Supabase session-pooler URL), `FRONTEND_ORIGIN`, `BACKEND_PUBLIC_URL`, `CORS_ALLOWED_ORIGINS`, `TRUSTED_HOSTS`, `SECURE_SESSION_COOKIES=true`, `SESSION_COOKIE_SAMESITE=none`, `MEDIA_RENDER_WORKER_MODE=embedded`, `MEDIA_STORAGE_BACKEND=supabase`, `MEDIA_RENDER_OUTPUT_DIR`, `SUPABASE_URL`, `SUPABASE_SERVICE_ROLE_KEY`, `SUPABASE_MEDIA_BUCKET`, `MEDIA_STORAGE_REQUEST_TIMEOUT_SECONDS`, `MEDIA_STORAGE_MAX_OBJECT_BYTES`, `MEDIA_SIGNED_URL_TTL_SECONDS`, `DB_POOL_SIZE`, `DB_MAX_OVERFLOW`, `DB_POOL_TIMEOUT_SECONDS`, `DB_POOL_RECYCLE_SECONDS`, and `DB_POOL_PRE_PING`.

Launch also requires a real email transport (`EMAIL_DELIVERY_MODE`, `EMAIL_TRANSPORT`, `EMAIL_FROM_ADDRESS`, plus `RESEND_API_KEY` or SMTP variables), at least one real TTS configuration (`TTS_PROVIDER` and its provider key), and the selected AI provider keys (`AI_PROVIDER`, `AI_PROVIDER_CHAIN`, `GEMINI_API_KEY`, `GROQ_API_KEY`). Billing variables remain optional until billing is enabled.

The default media limit is 49,000,000 bytes, deliberately below Supabase Free's 50 MB per-object ceiling. Oversized products fail without a partial upload or success quota. Supabase Free includes 1 GB storage and limited bandwidth; monitor both. Temporary files are removed after handled upload success or failure. Deterministic environment/user/job object keys make retries safe and prevent cross-bucket or traversal access.

The conservative single-process database pool is size 2, overflow 1, timeout 15 seconds, recycle 300 seconds, and pre-ping enabled. If the web process count changes or a separate worker is introduced later, recalculate the combined connection budget before scaling.

## Migrations and process behavior

Render Free web services do not provide the paid pre-deploy command used by some service types. Do not put Alembic in the build command, `render.yaml`, API startup, or worker startup. For a new empty database, an explicitly authorized operator runs `alembic upgrade head` before starting the service. For the already verified compatible Supabase schema, the authorized one-time baseline operation is `alembic stamp 20260823_0001`; stamping records history and does not create tables. Startup remains read-only and fails closed unless PostgreSQL is at the source head.

The embedded dispatcher recovers queued database jobs after process restart. Render Free services spin down after inactivity, so no media processing occurs while spun down. Normal frontend polling or user traffic wakes the service; cold starts can delay responses. Do not add artificial keep-alive traffic.

## Vercel handoff

Do not reactivate Vercel until the Render URL exists. Then set `NEXT_PUBLIC_API_BASE_URL` in the Vercel production environment to that URL and redeploy. Set Render's exact `FRONTEND_ORIGIN` and `CORS_ALLOWED_ORIGINS` to the final Vercel origin. Different Vercel and Render sites require HTTPS secure cookies with `SameSite=None`; validate browser policy for the chosen custom domains. Confirm anonymous `/admin/ops` navigation redirects to authentication and then verify the email OTP/session flow with explicitly authorized test delivery.

Media products remain audio files and `application/zip` scene/narration packages with `cinematic_video=false`; they are not encoded MP4 video.

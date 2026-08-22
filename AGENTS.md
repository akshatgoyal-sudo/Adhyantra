# Project: Adhyantra

## Current scope

- Adhyantra is a full-stack study application, not the original unauthenticated MVP.
- The frontend uses Next.js 16.2.1, React 18.3.1, TypeScript, and the Pages Router.
- The backend uses FastAPI, SQLAlchemy, SQLite for local development/testing, and PostgreSQL for deployed environments.
- Existing product scope includes email-OTP authentication, DB-backed sessions, adaptive study flows, billing and premium entitlements, role-based admin tools, lesson exports, and local media workers.
- UPSC has the strongest native corpus. SSC and Banking have limited native material and intentionally fall back to shared corpus content where marked.
- Video-style rendering produces scene/narration ZIP packages; it does not encode MP4 video.

## Engineering rules

- Prefer simple, targeted implementations and avoid unnecessary dependencies.
- Preserve API compatibility and centralized authentication, entitlement, billing, and configuration rules.
- Keep AI, email, payment, TTS, media storage, and database providers configurable through environment variables.
- Use mock AI, console email, disabled payments/TTS, isolated SQLite, and temporary media paths for deterministic tests.
- Never commit secrets, local databases, generated media, test artifacts, or real environment files.
- Update README and example configuration when setup or product behavior changes.

## Validation

- Backend must import and boot with safe local configuration.
- Canonical backend suite: `python -m pytest`.
- Frontend clean install: `npm ci` from the repository root.
- Frontend checks: `npm run typecheck` and `npm run build`.
- Deployment configuration and public deployment health are separate concerns; do not claim a platform deployment is verified from local configuration alone.

## Preferred commands

- Backend environment: `python -m venv .venv`
- Backend install: `python -m pip install -r requirements.txt`
- Backend run: `python -m uvicorn backend.main:app --reload`
- Frontend install: `npm ci`
- Frontend run: `npm run dev`

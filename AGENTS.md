# Project: Adhyantra

## Rules

- Keep the scope to MVP only
- Prefer simple implementations over clever ones
- Do not add unnecessary dependencies
- Use SQLite, FastAPI, Next.js
- Keep AI provider configurable with env vars
- If API key is absent, use mock mode
- Do not add auth, payments, or deployment config
- Update README when behavior changes

## Validation

- Backend must boot without errors
- Frontend must boot without errors
- Basic backend test must pass

## Preferred commands

- Backend install: `pip install -r requirements.txt`
- Backend run: `uvicorn backend.main:app --reload`
- Frontend install: `npm install`
- Frontend run: `npm run dev`

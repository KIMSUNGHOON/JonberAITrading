# Repository Guidelines

## Project Structure & Module Organization
This repository contains a FastAPI backend and a React frontend.
- `backend/app`: API entry point and routes (`app/main.py`, `app/api/routes/`).
- `backend/agents`: LangGraph workflows, subagents, and LLM provider integration.
- `backend/services` and `backend/models`: business logic and data models.
- `backend/tests`: pytest suite (see `backend/pytest.ini` for discovery rules).
- `frontend/src`: React components, Zustand store, and API clients.
- `docs/setup`: OS-specific setup guides; `docs/FEATURE_SPEC_*.md` for specs.
- `data/mock`: mock market data used when live data is unavailable.

## Build, Test, and Development Commands
Backend (conda preferred):
```bash
conda env create -f environment.yml
conda activate agentic-trading
cd backend
uvicorn app.main:app --reload --port 8000
```
Frontend:
```bash
cd frontend
npm install
npm run dev
```
Other useful commands:
- `npm run build`: type-checks and builds the frontend.
- `npm run lint` / `npm run format`: ESLint and Prettier for UI code.
- `docker-compose up --build`: run full stack in Docker (optional).

## Coding Style & Naming Conventions
- Python: 4-space indentation, type hints, and async/await where relevant.
- TypeScript/React: functional components, hooks, and existing ESLint rules.
- Keep names descriptive and consistent with existing modules (e.g., `*_provider.py`, `Test*` classes).

## Testing Guidelines
- Framework: pytest (backend). Tests live in `backend/tests`.
- Naming: `test_*.py`, `Test*` classes, `test_*` functions.
- Run: `cd backend && pytest -v`.
- Frontend tests are not defined in this repository; add commands here if a UI test runner is introduced.

## Commit & Pull Request Guidelines
- Commits follow an imperative, sentence-case style (e.g., “Fix WebSocket subscription thrashing...”).
- PRs should include a short summary, testing notes, and linked issues when applicable.
- For UI changes, include screenshots or a short screen recording.

## Configuration & Security Tips
- Environment variables are expected via `.env` (see `README.md` and `CLAUDE.md`).
- LLM providers run locally (Ollama or vLLM); avoid committing secrets or model keys.

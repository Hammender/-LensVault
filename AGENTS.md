# Repository Guidelines

## Project Structure & Module Organization
`backend/` contains the FastAPI service. Main API routes live in `backend/app/main.py`, configuration in `backend/app/core/config.py`, database setup in `backend/app/db.py`, and domain logic in `backend/app/services/`. `frontend/` contains the Vite + React client, with app entry points in `frontend/src/main.tsx` and `frontend/src/App.tsx`. Shared frontend request and type definitions live in `frontend/src/api.ts` and `frontend/src/types.ts`. Runtime data is stored under `data/`; treat `data/app.db` as local state, not source.

## Build, Test, and Development Commands
Use the Windows helper script for normal local work:

```powershell
.\start-dev.ps1
```

This launches the backend on `http://127.0.0.1:8000` and the frontend on `http://127.0.0.1:5173`.

Key manual commands:

```powershell
python -m uvicorn app.main:app --reload --app-dir backend
cmd /c npm.cmd install
cmd /c npm.cmd run dev
cmd /c npm.cmd run build
```

Run `npm.cmd run build` before submitting frontend changes; it also runs the TypeScript project build. MinIO must be running, and `.env` should match `.env.example`.

## Coding Style & Naming Conventions
Follow the existing style: 4-space indentation in Python, 2-space indentation in TypeScript/TSX, and double quotes in frontend files. Keep Python modules and service files `snake_case`; use `PascalCase` for React components and Pydantic/SQLAlchemy models. Prefer small helper functions over deeply nested route handlers. Keep user-facing frontend copy in Chinese unless the surrounding UI is already English.

## Testing Guidelines
No automated test suite is checked in yet. For backend changes, do a quick API smoke test against `/api/health` and the affected endpoints. For frontend changes, run `cmd /c npm.cmd run build` and manually verify the changed flow in the browser. If you add tests, place frontend tests under `frontend/src/` next to the feature and backend tests under `backend/tests/`.

## Commit & Pull Request Guidelines
This repository currently has no commit history, so use clear imperative commit subjects such as `Add cluster reassignment validation`. Keep commits focused by feature or fix. Pull requests should include a short summary, setup or migration notes if `.env` or MinIO behavior changed, and screenshots for visible frontend updates.

## Configuration & Data Notes
Do not commit real secrets in `.env`. Keep `.env.example` updated when adding settings. Avoid committing generated data, model downloads, or local database changes from `data/`.

## 约束
1.你在运行过程中绝对不能主动启动前端或后端程序，除非得到用户的授权，否则启动程序只能让用户自己手动启动。
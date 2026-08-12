# Repository Guidelines

## Project Structure & Module Organization
`backend/` contains the FastAPI service. Main API routes live in `backend/app/main.py`, configuration in `backend/app/core/config.py`, database setup in `backend/app/db.py`, and domain logic in `backend/app/services/`. `frontend/` contains the Vite + React client, with app entry points in `frontend/src/main.tsx` and `frontend/src/App.tsx`. Shared frontend request and type definitions live in `frontend/src/api.ts` and `frontend/src/types.ts`. Runtime data is stored under `data/`; treat `data/app.db` as local state, not source.

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

配置变更必须优先维护本地 `.env` 的完整字段和值，程序运行时只读取 `.env`（不得读取 `.env.example`），而 `.env.example` 仅保留完整字段名及不泄露隐私的示例默认值。

## 约束
1.你在运行过程中绝对不能主动启动前端或后端程序，除非得到用户的授权，否则启动程序只能让用户自己手动启动。
2.写文档时用中文，请勿用英文。
3.未经允许不可以执行git提交、合并等具有修改性的git操作。

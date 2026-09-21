# Ark Cloud Agent Notes

## Layout and boundaries

- `apps/api` is the Python 3.14 FastAPI service; `apps/web` is the Node 22 React/Vite client. The browser calls same-origin `/api/*`; Vite removes `/api` and proxies to the API, so do not put container hostnames or API URLs in browser code.
- Compose is the supported integrated environment. PostgreSQL and the API have no host ports; use `http://127.0.0.1:5173/api/...` to exercise the running API.
- Keep `ARK_BIND_ADDRESS=127.0.0.1`. Remote development access is through Tailscale Serve, not `0.0.0.0` or a direct Tailscale-IP bind.
- Metrics intentionally describe the unprivileged API runtime view. Do not add host mounts, Docker socket access, privileged namespaces, or claim exact host/cgroup telemetry.
- Keep Tailscale credentials server-side and normalized. The adapter must not return raw upstream payloads or expose the API key to the browser.
- Google Drive is the designated user-content storage provider, while PostgreSQL stores only Ark Cloud control-plane state. The current Drive integration remains metadata-only: keep OAuth client secrets and encrypted refresh tokens server-side, and do not add file browsing, upload/download proxies, or raw upstream responses outside an explicitly scoped roadmap phase.

## Run and verify

- Initial stack setup: `cp .env.example .env`, then change the password in both `POSTGRES_PASSWORD` and `ARK_DATABASE_URL` before `./scripts/ark up`.
- API unit checks run without PostgreSQL: `docker compose run --rm --no-deps -e ARK_DATABASE_URL=sqlite:// api pytest`, `ruff check .`, and `ruff format --check .` (each as the final command in the same `docker compose run` form). A focused backend test is `docker compose run --rm --no-deps -e ARK_DATABASE_URL=sqlite:// api pytest tests/test_health.py::test_name`.
- Frontend commands run from `apps/web`: `npm test`, `npm run lint`, `npm run format:check`, and `npm run build`. Use `npm test -- src/App.test.tsx` for the focused test file. CI uses `npm ci`, while `npm install` is for host setup and can update the lockfile.
- `./scripts/ark up` runs Alembic migrations before starting Uvicorn. Rebuild after dependency-manifest changes (`pyproject.toml`, `package.json`, or `package-lock.json`).
- Prefer `./scripts/ark up` for development: it validates `.env`, forces loopback binding, rebuilds/recreates every service, removes orphans, waits for health checks, and preserves volumes. Use `./scripts/ark restart` for a full fresh restart and `./scripts/ark down` for safe teardown.

## Database changes

- Add an Alembic revision only for schema changes. Generate it with `docker compose run --rm --no-deps --user root api sh -c 'alembic revision -m "describe the change" && chown --reference=alembic/env.py alembic/versions/*.py'`, review it, then apply it with `docker compose exec api alembic upgrade head`.
- `docker compose down --volumes` permanently deletes the local PostgreSQL volume; do not use it for routine teardown.

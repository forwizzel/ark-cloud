# Ark Cloud Agent Notes

## Layout and boundaries

- `apps/api` is the Python 3.14 FastAPI service; `apps/web` is the Node 22 React/Vite client. The browser calls same-origin `/api/*`; Vite removes `/api` and proxies to the API, so do not put container hostnames or API URLs in browser code.
- Compose is the supported integrated environment. PostgreSQL and the API have no host ports; use `http://127.0.0.1:5173/api/...` to exercise the running API.
- Keep `ARK_BIND_ADDRESS=127.0.0.1`. Remote development access is through Tailscale Serve, not `0.0.0.0` or a direct Tailscale-IP bind.
- Metrics intentionally describe the unprivileged API runtime view. Do not add host mounts for telemetry, Docker socket access, privileged namespaces, or claim exact host/cgroup telemetry. Local content mounts are explicitly owner-provisioned through `scripts/storage.py`; never mount host root or silently relabel existing directories.
- Keep Tailscale credentials server-side and normalized. The adapter must not return raw upstream payloads or expose the API key to the browser.
- Local host storage is the content provider; the host-owned manifest assigns mounted roots and immutable user IDs isolate private folders. PostgreSQL holds control-plane state, never file bodies. Local operations must use descriptor-relative Linux confinement and never follow symlinks or cross nested mounts.
- UI storage administration uses the owner-enrolled `scripts/storage_manager.py`, typed API jobs and host-approved directory areas; provisioning reuses `scripts/storage.py`. Keep the API unprivileged. Status reads must not create account folders, and per-user starting-folder preferences are distinct from the managed host base.
- System connection and configuration live in Administration → System. The deployment-prepared host manager runs typed System lifecycle jobs through `scripts/system_provision.py`; its separate agent handles telemetry, PTYs and host operations. Routine enrollment is a UI action, not an instruction to run scripts. Shell/service choices must come from host-reported installed/permitted inventory; the browser cannot choose another account or arbitrary executable.

## Run and verify

- Initial stack setup: `cp .env.example .env`, then change the password in both `POSTGRES_PASSWORD` and `ARK_DATABASE_URL` before `./scripts/ark up`.
- API unit checks run without PostgreSQL: `docker compose run --rm --no-deps -e ARK_DATABASE_URL=sqlite:// api pytest`, `ruff check .`, and `ruff format --check .` (each as the final command in the same `docker compose run` form). A focused backend test is `docker compose run --rm --no-deps -e ARK_DATABASE_URL=sqlite:// api pytest tests/test_health.py::test_name`.
- Frontend commands run from `apps/web`: `npm test`, `npm run lint`, `npm run format:check`, and `npm run build`. Use `npm test -- src/App.test.tsx` for the focused test file. CI uses `npm ci`, while `npm install` is for host setup and can update the lockfile.
- Host storage checks use disposable trees without Docker: `python3 -m unittest discover -s scripts -p 'test_storage*.py'`.
- `./scripts/ark up` runs Alembic migrations before starting Uvicorn. Rebuild after dependency-manifest changes (`pyproject.toml`, `package.json`, or `package-lock.json`).
- Prefer `./scripts/ark up` for development: it validates `.env`, forces loopback binding, rebuilds/recreates every service, removes orphans, waits for health checks, and preserves volumes. Use `./scripts/ark restart` for a full fresh restart and `./scripts/ark down` for safe teardown.
- `./scripts/ark storage init` provisions a new local-files directory and generates ignored `compose.storage.yaml` plus `.ark-storage/`. Lifecycle helpers include this override; plain `docker compose` intentionally excludes live content mounts for unit tests. Use `./scripts/ark storage check` to verify the running API's mounts and permissions. See `docs/local-storage.md` for Fedora SELinux, rootless UID mappings, existing-root assignments, and recovery.

## Database changes

- Add an Alembic revision only for schema changes. Generate it with `docker compose run --rm --no-deps --user root api sh -c 'alembic revision -m "describe the change" && chown --reference=alembic/env.py alembic/versions/*.py'`, review it, then apply it with `docker compose exec api alembic upgrade head`.
- `docker compose down --volumes` permanently deletes the local PostgreSQL volume; do not use it for routine teardown.

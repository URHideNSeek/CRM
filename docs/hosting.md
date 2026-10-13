# Deploying on the existing hosting account

Target preference: the existing hosting account. Provider/plan compatibility is not yet verified; no hosting changes or purchases have been made. Determine the exact plan name and available service controls first.

## Requirements to confirm with the provider

- Python 3.11 or newer, pip/virtualenv, and compiled wheels for psycopg.
- PostgreSQL with a currently supported release (the deployment/tests use PostgreSQL 17).
- Persistent processes for Streamlit and the FastAPI service; background worker or scheduled cron.
- HTTPS reverse proxy with WebSocket upgrade support for Streamlit and bearer header forwarding for API.
- Private database connectivity, secret environment variables, storage for OIDC secrets, and backup/restore access.
- A restart mechanism after crashes/reboots (Docker Compose, systemd, or provider-managed services).

A cPanel Python/WSGI application launcher alone does not establish support for the Streamlit WebSocket server or FastAPI ASGI service. Obtain provider confirmation before adapting deployment to a shared plan. Docker is a convenience, not required; a supervised virtualenv deployment is also possible if the provider supports the above processes.

Suggested support inquiry (not sent):

> I want to host a private company CRM on my existing plan. It uses Streamlit, a FastAPI integration service, Python 3.11+, and PostgreSQL 17. It needs HTTPS with WebSockets, persistent Python processes, and a reminder worker (or a once-per-minute cron job). Can my exact plan support this? What Python/PostgreSQL versions and process/reverse-proxy controls are available? If Docker is not supported, can you supervise the services and proxy to them? Please confirm compatibility before suggesting an upgrade.

## If the account supports Docker

Use the repository's `compose.yaml`; the app/API ports bind to localhost and PostgreSQL has no published port. On an existing server, first confirm ports 8501/8000 are unused and that no existing workload conflicts.

1. Check out the private repository on the server with a read-only deploy credential.
2. Populate `.env` with a strong DB password, `AUTH_MODE=oidc`, exact `ALLOWED_EMAILS`, and the API token hashes. Keep this file private.
3. Register the Google OIDC client for the chosen CRM hostname and create the real `.streamlit/secrets.toml`.
4. Add a read-only secrets mount for the app service:
   ```yaml
   services:
     app:
       volumes:
         - ./.streamlit/secrets.toml:/app/.streamlit/secrets.toml:ro
   ```
   Use an override file and ensure container UID 10001 can read it.
5. Have the host's reverse proxy route the chosen CRM hostname to localhost:8501 with WebSocket support, and the chosen API hostname to localhost:8000. Configure TLS, disable sensitive query-string logs, set request limits, and keep direct ports private.
6. Run `docker compose up --build -d`. Compose applies migrations before starting services.
7. Verify OIDC allow/deny behavior, `/health`, authenticated `/ready`, and the UI. Check that an unauthenticated API request returns 401.
8. Import/reconcile existing CSVs, test one follow-up/reminder, and verify backup recovery before cutover.

Hostnames are deliberately not hardcoded because DNS and hosting controls have not been confirmed. Do not alter existing website/email DNS records to host the CRM.

## Without Docker

Install into a virtualenv and run `alembic upgrade head`. Configure a supervisor for:

```bash
streamlit run app.py --server.address=127.0.0.1 --server.port=8501
uvicorn crm.api:app --host 127.0.0.1 --port 8000 --no-access-log
python -m crm.reminders --loop
```

Use an absolute executable path from the virtualenv in supervisor jobs, with the repository as working directory and secrets injected privately. Alternatively, cron can invoke `python -m crm.reminders` once per minute; this command is retry-safe and generates durable inbox records. Proxy/TLS/OIDC/database/backup requirements are the same as Docker.

## Not yet complete

Plan compatibility, host access, actual DNS/TLS/OIDC configuration, live PostgreSQL, data import, chat connector installation, and external reminder delivery remain deployment steps. The application and integration interface can be tested before any of those account changes.

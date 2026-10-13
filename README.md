# Unseen Robotics CRM

A shared Streamlit relationship workspace backed by PostgreSQL. It turns contacts and conversations into owned next actions, preserves customer feedback, and generates durable follow-up reminders.

## What is included

- **Overview:** overdue/today actions, pipeline stages, contacts without an open next action.
- **Contacts:** organization, professional details, relationship type, interests, priority, owner, status, source, history and linked opportunities/tasks.
- **Channel provenance:** one `captured_channel` and any number of `used_channels` per contact. For example, a vendor captured by UR Partners can also be used by UR Private BD. Both are independently filterable. Channels are metadata; they do not restrict access.
- **Organizations:** shared normalized organizations; OSU/Ohio State aliases resolve to The Ohio State University.
- **Interactions:** append-only history with date, channel, evidence/source, event/opportunity links, promises and next steps. Logging an interaction can create its follow-up in the same transaction.
- **Opportunities:** funder/customer/government/partner pursuits, stage, fit, value, deadline, primary contact, owner and next action.
- **Customer insights:** needs, positive signals, objections, requirements and product/pursuit implications with provenance.
- **Events:** event context linked to conversations.
- **Follow-ups:** contact/opportunity links, owning channel, owner, priority, due date, complete/cancel/reopen and reschedule.
- **Reminder inbox:** daily reminders for overdue/today tasks and those due in the next two days; acknowledge for today or complete the task.
- **Import/export:** transactional CSV import with repeat-ID skipping, original fields/IDs preserved, duplicate review report, and full JSON reference export.

## Start locally (Docker Desktop)

```bash
cp .env.example .env
# Edit .env: replace POSTGRES_PASSWORD with a strong random alphanumeric password.
docker compose up --build -d
```

Open http://localhost:8501. The app binds to localhost and the database has no published port. Compose starts PostgreSQL, applies Alembic migrations, starts Streamlit, and starts the reminder worker. Data lives in the `crm_data` volume. `docker compose down` preserves data; `down -v` deletes it.

Local mode is only for a trusted local computer. No actual contacts or credentials are bundled in this repo. Import current CRM data after startup.

## Running without Docker

Use Python 3.11+ and a running PostgreSQL instance:

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e '.[dev]'
export DATABASE_URL='postgresql+psycopg://crm:YOUR_PASSWORD@localhost:5432/crm'
export AUTH_MODE=local
alembic upgrade head
streamlit run app.py --server.address=127.0.0.1
# In a separate terminal with the same environment:
python -m crm.reminders --loop
```

On Windows, activate with `.venv\Scripts\Activate.ps1` and set environment variables with `$env:DATABASE_URL=...` in PowerShell.

## Follow-up reminders

The worker checks every minute and persists one reminder per task/day/due-date. Overdue tasks return each day until completed, cancelled or rescheduled. Acknowledgment only hides today's reminder. Changing the due date invalidates old reminders. Completed/cancelled tasks do not generate or display reminders. All business dates use America/New_York; audit timestamps use UTC. Undated tasks stay in the Unscheduled filter and receive no reminders.

The inbox also generates reminders when opened, so it works if the worker briefly stops. The worker retries transient failures and logs counts/error types without contact content or credentials.

**This version generates in-app reminders. It does not send email, Slack, ChatGPT notifications or messages to contacts.** Owner labels organize tasks; all approved users can view the shared inbox. An external notification adapter can later consume the task/reminder data once delivery destination and authorization are specified.

## Existing UR company memory / cutover

Current shared record used by UR channels: `URHideNSeek/UR-Company-Memory/CRM`. This repository holds the app and schema; PostgreSQL holds app data.

In **Import & export**, upload current `organizations.csv`, `people.csv`, `events.csv`, `opportunities.csv`, `interactions.csv`, `tasks.csv`, and `sources.csv` together. Or run:

```bash
python -m crm.import_export /path/to/UR-Company-Memory/CRM
```

- Original IDs, provenance and complete original rows are retained in `legacy_data`.
- Reimporting an existing legacy ID skips it; it never replaces later edits in the app. This is an initial migration, not ongoing synchronization.
- An exact known source-channel name becomes the capture/interaction/task channel. Unknown/composite descriptions remain Unassigned. Contact usage channels must be explicitly assigned; relationship type does not establish channel usage.
- Email/profile identity conflicts are skipped and reported for review; ambiguous names are not silently merged.
- Original unresolved relationship names stay in `legacy_data`; interactions/tasks may be imported without a contact link.
- Unknown task statuses become Open and are reported for review. Blank due dates remain blank.
- `suppliers.csv` is a specialist register and is not imported by this initial migration; use contact/organization records for shared vendor relationships.
- Download and reconcile any review report before treating the migration as complete. Keep an import source copy and database backup.

**No automatic sync or canonical-store switch occurs.** Until a cutover is agreed, UR channels continue using the company-memory CSVs. For cutover, reconcile imports and unresolved links, back up PostgreSQL, choose the integration method for channel writes, then update UR Common CRM skill instructions. Avoid independently editing both stores after cutover.

## Shared hosting and authentication

The app defaults to OIDC unless `AUTH_MODE=local` is explicitly supplied. Shared hosting requires HTTPS, OIDC, and an explicit verified-email allowlist. Streamlit handles authentication; this app checks the allowlist before connecting to the database. All approved users share CRM access.

1. Register an OIDC client (Google Workspace is supported) with the callback `https://YOUR_CRM_HOST/oauth2callback`.
2. Copy `.streamlit/secrets.toml.example` to `.streamlit/secrets.toml`; set client/cookie secrets and callback. Never commit this file.
3. Set `AUTH_MODE=oidc` and `ALLOWED_EMAILS` to the exact approved email addresses.
4. For Docker, mount the real secrets file read-only at `/app/.streamlit/secrets.toml`; make it readable by container UID 10001. Put HTTPS and access controls in front of Streamlit. Do not expose the local unauthenticated mode.
5. Use a private database network, a dedicated DB account, encrypted backups, and managed secret injection. Use separate migration credentials if your deployment separates schema privileges from app privileges.

Contact/task/opportunity edits use version checks to prevent lost updates. The database enforces unique emails, profile URLs and reminder keys. No contact deletion or interaction-edit UI is provided; history stays intact.

Keep credentials, candidate resumes/sensitive PII, banking/tax identifiers, privileged legal content, classified data, CUI and export-controlled technical data outside this general CRM.

## Backups and restore

```bash
mkdir -p backups
docker compose exec -T db pg_dump -U crm -d crm -Fc > backups/crm.dump
# Verify recovery into a separate empty database (never overwrite the live one to test):
docker compose exec -T db createdb -U crm crm_restore_test
docker compose exec -T db pg_restore -U crm -d crm_restore_test < backups/crm.dump
```

Verify record counts and representative relationship links in the restored database. Keep encrypted off-host copies and test recovery regularly. JSON export is for portability/reference; use pg_dump/pg_restore for full recovery. Database migrations are versioned; back up before migration and restore a backup for rollback if needed. Future schema changes need a new revision, not changes to `schema_v1.py`.

## Tests

```bash
pip install -e '.[dev]'
ruff check .
pytest -q
# Use an isolated PostgreSQL TEST database for integration tests:
TEST_DATABASE_URL='postgresql+psycopg://...' pytest -q
```

GitHub Actions runs migrations and the full suite on PostgreSQL 17. Local tests use SQLite only as a fast test harness when TEST_DATABASE_URL is absent; the app itself requires PostgreSQL. Tests cover shared channel filters, identity dedupe, transactional history/follow-ups, stale edits, reminder idempotency/rescheduling/completion, repeat-safe imports and Streamlit screens.

## Reference documentation

- [Streamlit OIDC authentication](https://docs.streamlit.io/develop/concepts/connections/authentication)
- [SQLAlchemy PostgreSQL dialect](https://docs.sqlalchemy.org/en/20/dialects/postgresql.html)

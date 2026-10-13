# Neon persistence and ChatGPT integration

1. Create a Neon project and copy its pooled PostgreSQL connection string from Connect.
2. In Streamlit app Settings > Secrets, keep APP_PASSWORD and add:

```toml
DATABASE_URL = "postgresql://USER:PASSWORD@HOST/DATABASE?sslmode=require"
```

Do not paste credentials into chats or GitHub. The app creates a dedicated
ur_simple_crm_state table, loads current data on each rerun, and saves each edit
transactionally. Concurrent stale writes are rejected, not silently overwritten.
Use Refresh CRM data to see updates made by other clients. Existing data in a
session should be backed up before enabling the database, then imported once.
This implementation uses a versioned JSON snapshot for a small CRM; it is separate
from the normalized tables used by crm.api and the full app.

3. Deploy a separate HTTPS API service from this repo (for example on Render).
Build: pip install -r requirements.txt
Start: uvicorn crm.simple_api:app --host 0.0.0.0 --port $PORT
Set DATABASE_URL to the same Neon database. Configure CRM_API_TOKENS_JSON using
crm.api_credentials (store only token SHA256 hashes on the server).
The APP_PASSWORD is not an API token. Restrict database credentials to this app.

4. Connect a custom GPT Action with bearer API-key authentication to the API.
Retrieve the authenticated /openapi.json schema with your token, then import it
into the Action and set its server URL to the deployed HTTPS API origin.
Add the token through the Action authentication UI, never through instructions.
A ChatGPT MCP plugin is an alternative, but is not configured by this deployment.

GPT workflow instructions:
- Before correspondence, GET /contacts?q=NAME_OR_ORGANIZATION, resolve identity,
  then GET /contacts/{id}/context. Check interactions, commitments and open tasks.
- After confirmed changes, PUT /records/contacts/{id} with version, record and
  source. For new conversations use /records/interactions/{new-stable-id}; for
  follow-ups use /records/tasks/{id}. Interactions are append-only.
- Preserve fields not changed. Re-read on 409 and merge; never overwrite blindly.
- An email draft is not an email sent. Record sent only after user confirmation.
- On database failure, report unavailable context rather than inventing history.

Code alone does not give this conversation access to the API. The hosted API and
Action/plugin must be connected. Existing UR Common CRM skills currently read the
private GitHub CRM; migrate/reconcile records and update their data-source workflow
before treating Neon as the sole canonical source. Avoid dual independent writers.
No actual contact data or credentials are included in this repository.

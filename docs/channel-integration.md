# UR channel integration

The API connects channels to the same PostgreSQL database used by Streamlit. It is implemented and tested, but a reachable HTTPS endpoint and installed client/connector must be configured before chats can call it. No existing UR chat has been redirected automatically. Company-memory CSVs remain canonical until cutover is explicitly completed.

## Credentials and provenance

Run on the deployment administrator's trusted computer:

```bash
python -m crm.api_credentials
```

The output file is private, excluded from git, and created with restrictive POSIX permissions. Do not put it in Library, a chat, a ticket, or source control. Keep the full file in your secret manager. It contains a random credential per channel and a separate `server_config` list of token hashes.

Set `CRM_API_TOKENS_JSON` on the API server to the JSON-serialized `server_config` list. Only hashes, channel and integration name are required on the server. Supply each integration only its own raw token. Integration names must be unique and stable, because they scope retry receipts; rotate tokens by replacing their hash while retaining name/channel. Remove a hash to revoke access. Configure Windows file permissions explicitly if generating credentials on Windows.

All endpoints except `/health` require `Authorization: Bearer TOKEN`. There is no unauthenticated local bypass on the API. Missing/invalid credentials return 401. Invalid server auth configuration returns 503. Channel identity comes from the credential, not a client-supplied capture field. Contacts preserve their original capture channel on update; usage channels remain explicitly editable. Channel identity records attribution, not an access restriction: all authenticated channels can read and use every contact.

Serve through HTTPS with proxy rate limits and payload limits. Keep raw API ports private and disable access logs that could expose contact search strings. Use distinct credentials for each workstream rather than one shared token.

## Endpoints

| Endpoint | Purpose |
|---|---|
| GET `/ready` | Authenticated database readiness check |
| GET `/v1/openapi.json` | Authenticated connector schema |
| GET `/v1/channels` | Available channel names and credential attribution |
| GET `/v1/contacts` | Search/filter contacts by `search`, `captured`, `used`, `kind`, `owner` |
| GET `/v1/contacts/{id}` | Read contact and edit version |
| POST `/v1/contacts` | Create a contact with server-stamped capture channel |
| PUT `/v1/contacts/{id}` | Replace editable contact fields with `expected_version` |
| GET `/v1/contacts/{id}/interactions` | Append-only relationship history |
| POST `/v1/interactions` | Log conversation and optionally create its follow-up atomically |
| GET `/v1/tasks` | List tasks by owner/channel/status |
| POST `/v1/tasks` | Create an owned follow-up |
| PATCH `/v1/tasks/{id}` | Complete/cancel/reopen/reschedule with `expected_version` |
| GET `/v1/followups/digest` | Reminder feed for delivery adapters, filtered by owner/channel |

List endpoints accept `limit` (1–200) and `offset`. Read until a page contains fewer than `limit` items; concurrent changes can shift offset pages. The digest includes overdue/today actions and up to `days` ahead (default 2, maximum 30), uses Eastern dates, and excludes completed/cancelled/undated tasks. It does not acknowledge reminders, complete tasks or send messages. It reports `has_more` conservatively when a page is full; fetch the next page.

Each write **requires `Idempotency-Key`**. Use a persistent unique key for the logical operation (such as the source interaction ID). Reuse it for retries of the exact same request. Successful identical retries return the original result without adding a second interaction/task/contact. Changing payload or route under the same key returns 409. Failed writes roll back both the record and receipt, allowing a corrected retry. Receipt claims and domain writes share one transaction, with the database unique key serializing concurrent requests. A retried successful result is the original response; refetch the record to get subsequent edits.

The PUT contact endpoint is full replacement of editable fields: read the contact first, retain fields you want to keep, supply `expected_version`, and omit response-only fields (`id`, `organization_id`, `captured_channel`, `last_contact`, `version`). If another user edited it, a version conflict returns 409. Unknown foreign record IDs return 404. Invalid request shape returns 422. Database outages return 503. Conflicts never silently merge people.

## Example: vendor conversation to follow-up

Supply credentials from your local secret manager, not a literal checked-in token:

```python
import os
import uuid
import httpx

base = os.environ["CRM_API_URL"].rstrip("/")  # HTTPS in deployed use
headers = {"Authorization": "Bearer " + os.environ["CRM_API_TOKEN"]}
with httpx.Client(base_url=base, headers=headers, timeout=20) as client:
    response = client.get("/v1/contacts", params={"search": "vendor@example.com"})
    response.raise_for_status()
    records = response.json()["items"]
    # Review identity before using an ambiguous search result.
    if len(records) != 1:
        raise RuntimeError("Review contact identity first")
    contact = records[0]
    # Persist this operation key so a later retry uses the same key.
    operation_key = str(uuid.uuid4())
    response = client.post(
        "/v1/interactions",
        headers={"Idempotency-Key": operation_key},
        json={
            "contact_id": contact["id"],
            "occurred_on": "2026-10-13",
            "kind": "Email",
            "summary": "Vendor requested a capability brief.",
            "next_step": "Send the public capability brief.",
            "followup_due": "2026-10-16",
            "owner": "JJ",
            "provenance": "UR Partners / source email reference",
        },
    )
    response.raise_for_status()
```

A UR Partners credential stamps the interaction and task as UR Partners. A UR Private BD credential can still retrieve and use the same contact. No outbound email to the vendor is sent by this operation.

## Reminder delivery and cutover

Once hosted, a separately configured automation can read `/v1/followups/digest?owner=JJ`, format actions, and deliver a daily reminder to JJ. Delivery destination, schedule, credentials and connector remain to be configured. Do not mark a task complete merely because a notification was delivered. The in-app reminder worker continues independently.

Before redirecting UR channels: import current CSVs; reconcile duplicate/unresolved records; verify counts and links; back up PostgreSQL; deploy the API; provision channel credentials privately; install the connector/client; confirm a read and a retry-safe write; then update the UR Common CRM skill's canonical-store instructions. No automatic bidirectional CSV sync is provided.

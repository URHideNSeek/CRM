import hashlib
import json
from datetime import timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from crm.api import app, database
from crm.models import ApiReceipt, Contact, Interaction, Task
from crm.service import today


@pytest.fixture
def client(db, monkeypatch):
    tokens = [
        {"sha256": hashlib.sha256(token.encode()).hexdigest(), "name": name, "channel": channel}
        for token, name, channel in [
            ("partners-test-token", "partners", "UR Partners"),
            ("private-test-token", "private", "UR Private BD"),
        ]
    ]
    monkeypatch.setenv("CRM_API_TOKENS_JSON", json.dumps(tokens))

    def test_database():
        with db.begin_nested():
            yield db

    app.dependency_overrides[database] = test_database
    with TestClient(app) as client:
        yield client
    app.dependency_overrides.clear()


def headers(key="request-1", token="partners-test-token"):
    return {"Authorization": "Bearer " + token, "Idempotency-Key": key}


def test_auth_closed_by_default(client, monkeypatch):
    assert client.get("/health").status_code == 200
    assert client.get("/v1/contacts").status_code == 401
    assert client.get("/v1/contacts", headers=headers(token="bad")).status_code == 401
    monkeypatch.delenv("CRM_API_TOKENS_JSON")
    assert client.get("/v1/contacts", headers=headers()).status_code == 401
    monkeypatch.setenv("CRM_API_TOKENS_JSON", "not json")
    assert client.get("/v1/contacts", headers=headers()).status_code == 503


def test_capture_usage_shared_access_and_retries(client, db):
    payload = {
        "name": "Vendor",
        "email": "vendor@example.com",
        "organization_name": "Example Inc",
        "relationship_type": "Vendor",
        "used_channels": ["UR Partners", "UR Private BD"],
    }
    first = client.post("/v1/contacts", json=payload, headers=headers())
    assert first.status_code == 201, first.text
    assert first.json()["captured_channel"] == "UR Partners"
    repeat = client.post("/v1/contacts", json=payload, headers=headers())
    assert repeat.json() == first.json()
    assert db.scalar(select(func.count()).select_from(Contact)) == 1
    conflict = client.post("/v1/contacts", json={**payload, "name": "Different"}, headers=headers())
    assert conflict.status_code == 409
    response = client.get("/v1/contacts?used=UR+Private+BD", headers=headers(token="private-test-token"))
    assert len(response.json()["items"]) == 1
    assert client.get("/v1/contacts?captured=UR+Private+BD", headers=headers()).json()["items"] == []
    assert client.get("/v1/contacts?limit=0", headers=headers()).status_code == 422
    assert client.get("/v1/openapi.json", headers=headers()).status_code == 200


def test_contact_replacement_version_and_provenance(client):
    payload = {"name": "Person", "email": "p@example.com", "used_channels": ["UR Partners"]}
    first = client.post("/v1/contacts", json=payload, headers=headers()).json()
    replacement = {
        **payload,
        "name": "Updated",
        "expected_version": first["version"],
        "used_channels": ["UR Private BD"],
    }
    update = client.put(
        f"/v1/contacts/{first['id']}", json=replacement, headers=headers("edit", "private-test-token")
    )
    assert update.status_code == 200
    assert update.json()["captured_channel"] == "UR Partners"
    assert update.json()["used_channels"] == ["UR Private BD"]
    stale = client.put(f"/v1/contacts/{first['id']}", json=replacement, headers=headers("stale"))
    assert stale.status_code == 409
    assert client.get(f"/v1/contacts/{first['id']}", headers=headers()).json()["name"] == "Updated"


def test_interaction_retry_creates_only_one_task(client, db):
    contact = client.post("/v1/contacts", json={"name": "Contact"}, headers=headers()).json()
    payload = {
        "contact_id": contact["id"],
        "occurred_on": today().isoformat(),
        "summary": "Asked for a brief",
        "next_step": "Send brief",
        "followup_due": today().isoformat(),
    }
    for _ in range(2):
        response = client.post("/v1/interactions", json=payload, headers=headers("conversation"))
        assert response.status_code == 201, response.text
        assert response.json()["recorded_by"] == "partners"
    assert db.scalar(select(func.count()).select_from(Interaction)) == 1
    assert db.scalar(select(func.count()).select_from(Task)) == 1
    history = client.get(f"/v1/contacts/{contact['id']}/interactions", headers=headers()).json()
    assert len(history["items"]) == 1


def test_failed_request_rolls_back_and_key_can_retry(client, db):
    person = client.post("/v1/contacts", json={"name": "Contact"}, headers=headers()).json()
    payload = {
        "contact_id": person["id"],
        "occurred_on": today().isoformat(),
        "summary": "Missing next action",
        "followup_due": today().isoformat(),
    }
    bad = client.post("/v1/interactions", json=payload, headers=headers("retry"))
    assert bad.status_code == 409
    assert db.scalar(select(func.count()).select_from(Interaction)) == 0
    assert db.scalar(select(ApiReceipt).where(ApiReceipt.key == "retry")) is None
    good = client.post("/v1/interactions", json={**payload, "next_step": "Call"}, headers=headers("retry"))
    assert good.status_code == 201


def test_digest_owner_channel_and_task_completion(client):
    due = (today() - timedelta(days=1)).isoformat()
    task = client.post(
        "/v1/tasks", json={"title": "Follow up", "due_date": due, "owner": "JJ"}, headers=headers("task")
    ).json()
    client.post("/v1/tasks", json={"title": "Unscheduled"}, headers=headers("unscheduled"))
    digest = client.get("/v1/followups/digest?owner=JJ", headers=headers(token="private-test-token"))
    assert digest.status_code == 200
    assert digest.json()["items"][0]["timing"] == "Overdue"
    assert len(digest.json()["items"]) == 1
    assert client.get("/v1/followups/digest?channel=UR+Private+BD", headers=headers()).json()["items"] == []
    result = client.patch(
        f"/v1/tasks/{task['id']}",
        json={"expected_version": task["version"], "status": "Completed"},
        headers=headers("complete"),
    )
    assert result.status_code == 200
    assert client.get("/v1/followups/digest", headers=headers()).json()["items"] == []


def test_foreign_record_and_attribution_validation(client):
    assert (
        client.post(
            "/v1/tasks", json={"title": "Bad", "contact_id": "missing"}, headers=headers()
        ).status_code
        == 404
    )
    assert (
        client.post(
            "/v1/contacts", json={"name": "Bad", "captured_channel": "UR Private BD"}, headers=headers()
        ).status_code
        == 422
    )
    assert (
        client.post(
            "/v1/contacts", json={"name": "Bad", "used_channels": ["made-up"]}, headers=headers()
        ).status_code
        == 409
    )
    assert client.post("/v1/tasks", json={"title": "   "}, headers=headers()).status_code == 422

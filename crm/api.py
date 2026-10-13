"""Authenticated channel integration API; shared access with server-side provenance."""

import hashlib
import hmac
import json
import os
from datetime import date, timedelta
from typing import Annotated, Literal

from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select, text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm.exc import StaleDataError

from crm.db import session
from crm.models import ApiReceipt, Contact, Interaction, Opportunity, Task
from crm.service import (
    CHANNELS,
    ValidationError,
    add_interaction,
    contacts,
    organization,
    save_contact,
    task_bucket,
    today,
    update_task,
)

app = FastAPI(
    title="Unseen Robotics CRM integration", version="0.2.0", docs_url=None, redoc_url=None, openapi_url=None
)
bearer = HTTPBearer(auto_error=False)


class Principal(BaseModel):
    name: str
    channel: str


def principal(credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)]):
    try:
        tokens = json.loads(os.getenv("CRM_API_TOKENS_JSON", "[]"))
        if not isinstance(tokens, list):
            raise ValueError
        valid = all(
            isinstance(t, dict)
            and isinstance(t.get("sha256"), str)
            and len(t["sha256"]) == 64
            and t.get("name")
            and t.get("channel") in CHANNELS
            for t in tokens
        )
        if not valid or len({t["name"] for t in tokens}) != len(tokens):
            raise ValueError
    except (ValueError, TypeError):
        raise HTTPException(503, "API authentication configuration is invalid") from None
    if credentials is None:
        raise HTTPException(401, "Bearer token required", headers={"WWW-Authenticate": "Bearer"})
    digest = hashlib.sha256(credentials.credentials.encode()).hexdigest()
    for item in tokens:
        if hmac.compare_digest(digest, item["sha256"]):
            return Principal(name=item["name"], channel=item["channel"])
    raise HTTPException(401, "Invalid bearer token", headers={"WWW-Authenticate": "Bearer"})


def database():
    with session() as db:
        yield db


Actor = Annotated[Principal, Depends(principal)]
DB = Annotated[object, Depends(database, scope="function")]
Key = Annotated[str, Header(alias="Idempotency-Key", min_length=1, max_length=100)]


class Input(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class ContactInput(Input):
    name: str = Field(min_length=1, max_length=250)
    title: str = Field(default="", max_length=250)
    organization_name: str | None = Field(default=None, max_length=250)
    email: str | None = Field(default=None, max_length=320)
    phone: str = Field(default="", max_length=100)
    profile_url: str | None = Field(default=None, max_length=2000)
    relationship_type: str = Field(default="Other", max_length=100)
    used_channels: list[str] = Field(default_factory=list, max_length=30)
    owner: str = Field(default="JJ", min_length=1, max_length=150)
    status: str = Field(default="New", max_length=100)
    priority: Literal["High", "Medium", "Low"] = "Medium"
    interests: str = Field(default="", max_length=10000)
    notes: str = Field(default="", max_length=20000)
    provenance: str = Field(default="", max_length=4000)


class ContactReplacement(ContactInput):
    expected_version: int = Field(ge=1)


class TaskInput(Input):
    title: str = Field(min_length=1, max_length=10000)
    contact_id: str | None = None
    opportunity_id: str | None = None
    owner: str = Field(default="JJ", min_length=1, max_length=150)
    due_date: date | None = None
    priority: Literal["High", "Medium", "Low"] = "Medium"
    provenance: str = Field(default="", max_length=4000)


class TaskUpdate(Input):
    expected_version: int = Field(ge=1)
    status: Literal["Open", "Completed", "Cancelled"] | None = None
    due_date: date | None = None
    reschedule: bool = False


class InteractionInput(Input):
    contact_id: str
    occurred_on: date
    summary: str = Field(min_length=1, max_length=20000)
    kind: str = Field(default="Note", max_length=100)
    next_step: str = Field(default="", max_length=10000)
    followup_due: date | None = None
    owner: str = Field(default="JJ", min_length=1, max_length=150)
    opportunity_id: str | None = None
    provenance: str = Field(default="", max_length=4000)


def contact_json(item):
    return {
        **{
            col: getattr(item, col)
            for col in [
                "id",
                "name",
                "title",
                "organization_id",
                "email",
                "phone",
                "profile_url",
                "relationship_type",
                "captured_channel",
                "owner",
                "status",
                "priority",
                "interests",
                "notes",
                "provenance",
                "last_contact",
                "version",
            ]
        },
        "organization_name": item.organization.name if item.organization else None,
        "used_channels": [c.channel for c in item.used_channels],
    }


def task_json(item):
    return {
        **{
            col: getattr(item, col)
            for col in [
                "id",
                "title",
                "contact_id",
                "opportunity_id",
                "owner",
                "channel",
                "due_date",
                "priority",
                "status",
                "completed_at",
                "version",
                "provenance",
            ]
        },
        "timing": task_bucket(item),
        "contact_name": item.contact.name if item.contact else None,
    }


def existing(db, model, identifier):
    item = db.get(model, identifier)
    if item is None:
        raise HTTPException(404, "Record not found")
    return item


def references(db, payload):
    for field, model in [("contact_id", Contact), ("opportunity_id", Opportunity)]:
        identifier = getattr(payload, field, None)
        if identifier:
            existing(db, model, identifier)


def once(db, actor, key, route, payload, action):
    """Claim the key before mutation; PostgreSQL serializes racing retries at the unique key."""
    fingerprint = hashlib.sha256((route + payload.model_dump_json()).encode()).hexdigest()
    insert = pg_insert if db.bind.dialect.name == "postgresql" else sqlite_insert
    result = db.execute(
        insert(ApiReceipt)
        .values(principal=actor.name, key=key, fingerprint=fingerprint, response={})
        .on_conflict_do_nothing(index_elements=["principal", "key"])
        .returning(ApiReceipt.id)
    ).scalar_one_or_none()
    receipt = db.scalar(select(ApiReceipt).where(ApiReceipt.principal == actor.name, ApiReceipt.key == key))
    if result is None:
        if receipt.fingerprint != fingerprint:
            raise HTTPException(409, "Idempotency key already used for a different request")
        return receipt.response
    response = jsonable_encoder(action())
    receipt.response = response
    db.flush()
    return response


@app.exception_handler(ValidationError)
async def validation_error(request: Request, exc: ValidationError):
    return JSONResponse(status_code=409, content={"detail": str(exc)})


@app.exception_handler(IntegrityError)
@app.exception_handler(StaleDataError)
async def conflict_error(request: Request, exc: Exception):
    return JSONResponse(
        status_code=409, content={"detail": "Conflicting record or concurrent update; refetch and review"}
    )


@app.exception_handler(SQLAlchemyError)
@app.exception_handler(RuntimeError)
async def database_error(request: Request, exc: Exception):
    return JSONResponse(status_code=503, content={"detail": "Database unavailable"})


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/ready")
def ready(actor: Actor, db: DB):
    db.execute(text("SELECT 1"))
    return {"status": "ready"}


@app.get("/v1/openapi.json")
def schema(actor: Actor):
    return app.openapi()


@app.get("/v1/channels")
def channels(actor: Actor):
    return {"channels": CHANNELS, "integration": actor.model_dump(), "shared_access": True}


@app.get("/v1/contacts")
def list_contacts(
    actor: Actor,
    db: DB,
    search: str = "",
    captured: str | None = None,
    used: str | None = None,
    kind: str | None = None,
    owner: str | None = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
):
    return {
        "items": [
            contact_json(c)
            for c in contacts(db, search, captured, used, kind, owner, limit=limit, offset=offset)
        ],
        "limit": limit,
        "offset": offset,
    }


@app.get("/v1/contacts/{contact_id}")
def read_contact(contact_id: str, actor: Actor, db: DB):
    return contact_json(existing(db, Contact, contact_id))


def contact_fields(db, payload):
    fields = payload.model_dump(exclude={"organization_name", "expected_version"})
    if any(c not in CHANNELS for c in payload.used_channels):
        raise ValidationError("Unknown usage channel")
    org = organization(db, payload.organization_name) if payload.organization_name else None
    fields["organization_id"] = org.id if org else None
    return fields


@app.post("/v1/contacts", status_code=201)
def create_contact(payload: ContactInput, actor: Actor, db: DB, idempotency_key: Key):
    return once(
        db,
        actor,
        idempotency_key,
        "create_contact",
        payload,
        lambda: contact_json(save_contact(db, captured_channel=actor.channel, **contact_fields(db, payload))),
    )


@app.put("/v1/contacts/{contact_id}")
def replace_contact(contact_id: str, payload: ContactReplacement, actor: Actor, db: DB, idempotency_key: Key):
    def action():
        existing(db, Contact, contact_id)
        # Capture attribution stays unchanged; cross-channel use is explicitly editable.
        item = save_contact(
            db,
            contact_id=contact_id,
            expected_version=payload.expected_version,
            **contact_fields(db, payload),
        )
        return contact_json(item)

    return once(db, actor, idempotency_key, f"replace_contact:{contact_id}", payload, action)


@app.get("/v1/contacts/{contact_id}/interactions")
def history(
    contact_id: str,
    actor: Actor,
    db: DB,
    limit: Annotated[int, Query(ge=1, le=200)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
):
    existing(db, Contact, contact_id)
    items = db.scalars(
        select(Interaction)
        .where(Interaction.contact_id == contact_id)
        .order_by(Interaction.occurred_on.desc(), Interaction.created_at.desc(), Interaction.id)
        .offset(offset)
        .limit(limit)
    )
    return {
        "items": [{c.name: getattr(i, c.name) for c in Interaction.__table__.columns} for i in items],
        "limit": limit,
        "offset": offset,
    }


@app.post("/v1/interactions", status_code=201)
def create_interaction(payload: InteractionInput, actor: Actor, db: DB, idempotency_key: Key):
    def action():
        references(db, payload)
        item = add_interaction(db, **payload.model_dump(), channel=actor.channel, recorded_by=actor.name)
        return {
            "id": item.id,
            "channel": item.channel,
            "recorded_by": item.recorded_by,
            "followup_created": payload.followup_due is not None,
        }

    return once(db, actor, idempotency_key, "create_interaction", payload, action)


@app.post("/v1/tasks", status_code=201)
def create_task(payload: TaskInput, actor: Actor, db: DB, idempotency_key: Key):
    def action():
        references(db, payload)
        item = Task(**payload.model_dump(), channel=actor.channel)
        db.add(item)
        db.flush()
        return task_json(item)

    return once(db, actor, idempotency_key, "create_task", payload, action)


@app.patch("/v1/tasks/{task_id}")
def change_task(task_id: str, payload: TaskUpdate, actor: Actor, db: DB, idempotency_key: Key):
    return once(
        db,
        actor,
        idempotency_key,
        f"change_task:{task_id}",
        payload,
        lambda: task_json(update_task(db, task_id, **payload.model_dump())),
    )


@app.get("/v1/tasks")
def list_tasks(
    actor: Actor,
    db: DB,
    owner: str | None = None,
    channel: str | None = None,
    status: Literal["Open", "Completed", "Cancelled"] = "Open",
    limit: Annotated[int, Query(ge=1, le=200)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
):
    query = select(Task).where(Task.status == status)
    if owner:
        query = query.where(Task.owner == owner)
    if channel:
        query = query.where(Task.channel == channel)
    items = db.scalars(query.order_by(Task.due_date.asc().nulls_last(), Task.id).offset(offset).limit(limit))
    return {"items": [task_json(t) for t in items], "limit": limit, "offset": offset}


@app.get("/v1/followups/digest")
def digest(
    actor: Actor,
    db: DB,
    owner: str | None = None,
    channel: str | None = None,
    days: Annotated[int, Query(ge=0, le=30)] = 2,
    limit: Annotated[int, Query(ge=1, le=200)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
):
    query = select(Task).where(
        Task.status == "Open", Task.due_date.is_not(None), Task.due_date <= today() + timedelta(days=days)
    )
    if owner:
        query = query.where(Task.owner == owner)
    if channel:
        query = query.where(Task.channel == channel)
    items = list(db.scalars(query.order_by(Task.due_date, Task.id).offset(offset).limit(limit)))
    return {
        "as_of": today(),
        "timezone": "America/New_York",
        "horizon_days": days,
        "owner": owner,
        "channel": channel,
        "items": [task_json(t) for t in items],
        "limit": limit,
        "offset": offset,
        "has_more": len(items) == limit,
    }

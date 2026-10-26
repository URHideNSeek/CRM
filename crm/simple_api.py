"""Authenticated API for the same Neon state used by the simple CRM."""
import os
from datetime import date
from fastapi import FastAPI, Depends, HTTPException
from pydantic import BaseModel, Field
from crm.api import principal, Principal
from crm.simple_store import load, save, ConflictError

app = FastAPI(title='UR Simple CRM', version='1.0', docs_url=None, redoc_url=None, openapi_url=None)


class Change(BaseModel):
    version: int
    record: dict
    source: str = Field(min_length=1, max_length=2000)


def state():
    try:
        url = os.environ['DATABASE_URL']
        version, payload = load(url)
        return url, version, payload
    except Exception:
        raise HTTPException(503, 'Database unavailable') from None


@app.get('/openapi.json')
def schema(actor: Principal = Depends(principal)):
    return app.openapi()


@app.get('/contacts')
def search(q: str = '', actor: Principal = Depends(principal)):
    _, version, payload = state()
    return {'version': version, 'contacts': [c for c in payload['contacts'] if q.casefold() in ' '.join(str(c.get(k, '')) for k in ['name', 'organization', 'email']).casefold()]}


@app.get('/contacts/{contact_id}/context')
def context(contact_id: str, actor: Principal = Depends(principal)):
    _, version, payload = state()
    contact = next((c for c in payload['contacts'] if c['id'] == contact_id), None)
    if not contact:
        raise HTTPException(404, 'Contact not found')
    return {'version': version, 'contact': contact, 'interactions': [r for r in payload['interactions'] if r.get('contact_id') == contact_id], 'tasks': [r for r in payload['tasks'] if r.get('contact_id') == contact_id]}


@app.put('/records/{collection}/{record_id}')
def upsert(collection: str, record_id: str, change: Change, actor: Principal = Depends(principal)):
    if collection not in ['contacts', 'interactions', 'tasks']:
        raise HTTPException(400, 'Unknown collection')
    url, version, payload = state()
    if version != change.version:
        raise HTTPException(409, 'Read the latest context before updating')
    rows = payload[collection]
    existing = next((r for r in rows if r['id'] == record_id), None)
    if collection == 'interactions' and existing:
        if all(existing.get(k) == v for k, v in change.record.items()):
            return {'version': version, 'id': record_id}
        raise HTTPException(409, 'Interactions are append-only; use a new ID')
    changes = dict(change.record)

    # Accept the field names used by common CRM callers while storing one
    # canonical shape in the shared snapshot.
    aliases = {
        'contacts': {
            'organization': ('organization_name',),
            'kind': ('relationship_type', 'type'),
            'used_by': ('used_channels',),
        },
        'interactions': {
            'date': ('occurred_on',),
            'next_action': ('next_step',),
        },
        'tasks': {
            'action': ('title', 'task'),
            'due': ('due_date',),
        },
    }[collection]
    for canonical, alternatives in aliases.items():
        if canonical not in changes:
            for alternative in alternatives:
                if alternative in changes:
                    changes[canonical] = changes[alternative]
                    break
        for alternative in alternatives:
            changes.pop(alternative, None)

    record = {**(existing or {}), **changes, 'id': record_id}
    defaults = {
        'contacts': {
            'organization': '', 'email': '', 'kind': 'Other', 'owner': 'JJ',
            'captured_by': actor.channel, 'used_by': [], 'notes': '', 'status': 'New',
        },
        'interactions': {'channel': actor.channel, 'next_action': ''},
        'tasks': {
            'contact_id': None, 'channel': actor.channel, 'owner': 'JJ', 'due': '',
            'priority': 'Medium', 'status': 'Open',
        },
    }[collection]
    for key, value in defaults.items():
        if key not in record or record[key] is None:
            record[key] = value

    required = {
        'contacts': ['name', 'organization', 'email', 'kind', 'owner', 'captured_by', 'used_by', 'notes'],
        'interactions': ['contact_id', 'date', 'summary', 'next_action'],
        'tasks': ['contact_id', 'action', 'channel', 'owner', 'due', 'priority', 'status'],
    }[collection]
    missing = [key for key in required if key not in record or record[key] is None]
    if missing:
        raise HTTPException(422, f"Missing required field: {', '.join(missing)}")
    if any(not isinstance(record[k], str) for k in required if k not in ['used_by','contact_id']):
        raise HTTPException(422, 'Invalid field type')
    if collection == 'contacts' and (not isinstance(record['used_by'], list) or not all(isinstance(v,str) for v in record['used_by'])):
        raise HTTPException(422, 'Invalid channels')
    if collection != 'contacts' and record['contact_id'] is not None and not any(c['id'] == record['contact_id'] for c in payload['contacts']):
        raise HTTPException(422, 'Unknown contact')
    try:
        if collection == 'interactions':
            date.fromisoformat(record['date'])
        if collection == 'tasks':
            if record['due']:
                date.fromisoformat(record['due'])
            if record['status'] not in ['Open', 'Completed'] or record['priority'] not in ['High', 'Medium', 'Low']:
                raise ValueError()
        if collection == 'contacts':
            if not (record['name'].strip() or record['organization'].strip()):
                raise ValueError()
            if record['kind'] not in ['Vendor','Funder','Customer','Government','University','Partner','Advisor','Other']:
                raise ValueError()
    except (ValueError, TypeError):
        raise HTTPException(422, 'Invalid date, status, or contact category') from None
    record['provenance'] = change.source
    record['updated_by'] = actor.name
    if existing:
        rows[rows.index(existing)] = record
    else:
        rows.append(record)
    try:
        new_version = save(url, version, payload)
    except ConflictError:
        raise HTTPException(409, 'Concurrent update; read and retry') from None
    return {'version': new_version, 'id': record_id}

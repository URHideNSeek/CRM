"""Lightweight conference follow-ups using existing CRM records; no schema migration."""
from datetime import timedelta
from sqlalchemy import select
from crm.models import Contact, Event, Task, Interaction
from crm.service import today

KIND = "pre_event_meeting_request"

def event_tasks(db, event_id):
    return [t for t in db.scalars(select(Task)) if (t.legacy_data or {}).get("event_id") == event_id and (t.legacy_data or {}).get("action_type") == KIND]

def suggest_contacts(db, event):
    """Conservative CRM-only matching; never infer conference attendance."""
    words = {w.casefold() for w in (event.name + " " + event.location + " " + event.notes).split() if len(w) > 4}
    results = []
    for c in db.scalars(select(Contact)):
        haystack = " ".join([c.name, c.title, c.interests, c.notes, c.organization.name if c.organization else ""]).casefold()
        matches = sorted(w for w in words if w in haystack)
        if matches:
            results.append((c, ", ".join(matches[:4])))
    return results

def add_meeting_requests(db, event, contact_ids, *, due=None):
    if not event.event_date or event.event_date < today():
        raise ValueError("Select an upcoming dated event.")
    due = due or max(today(), event.event_date - timedelta(days=10))
    if due > event.event_date:
        raise ValueError("Follow-up date must be on or before the event.")
    existing = {t.contact_id for t in event_tasks(db, event.id)}
    created = 0
    for contact_id in dict.fromkeys(contact_ids):
        if contact_id in existing:
            continue
        contact = db.get(Contact, contact_id)
        if not contact:
            continue
        db.add(Task(
            contact_id=contact.id,
            title=f"Request meeting with {contact.name} at {event.name}",
            due_date=due, owner=contact.owner or "JJ", channel="UR Events",
            priority=contact.priority if contact.priority in {"High","Medium","Low"} else "Medium",
            provenance=f"Event outreach scan: {event.name} ({event.event_date}); attendance not confirmed.",
            legacy_data={"event_id": event.id, "action_type": KIND},
        ))
        created += 1
    db.flush()
    return created

def event_meetings(db, event_id):
    return sorted(
        [i for i in db.scalars(select(Interaction).where(Interaction.event_id == event_id))
         if (i.legacy_data or {}).get("meeting_time")],
        key=lambda i: (i.legacy_data or {}).get("meeting_time", ""),
    )

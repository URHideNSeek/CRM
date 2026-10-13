import re
from datetime import date, datetime
from zoneinfo import ZoneInfo

from sqlalchemy import func, or_, select

from crm.models import Contact, ContactChannel, Interaction, Organization, Task, utcnow

CHANNELS = [
    "UR Partners",
    "UR Private BD",
    "UR Federal BD",
    "UR State BD",
    "UR Events",
    "OSU Partnership Outreach",
    "Market Research Leads",
    "UR HR",
    "UR Legal",
    "UR IP",
    "UR IT",
    "UR Compliance",
    "UR Tax",
    "Pigeon Bot",
    "Pigeon Bot-PR",
    "UR Web & Media",
    "Unassigned",
]
TYPES = ["Vendor", "Funder", "Customer", "Government", "University", "Partner", "Advisor", "Other"]
STAGES = ["Identified", "Qualified", "Conversation", "Proposal", "Negotiation", "Won", "Lost", "On hold"]


class ValidationError(ValueError):
    pass


def today():
    return datetime.now(ZoneInfo("America/New_York")).date()


def required(value, label):
    value = (value or "").strip()
    if not value:
        raise ValidationError(f"{label} is required.")
    return value


def organization(db, name, **fields):
    name = required(name, "Organization name")
    key = " ".join(name.casefold().split())
    aliases = {"osu": "the ohio state university", "ohio state": "the ohio state university"}
    key = aliases.get(key, key)
    item = db.scalar(select(Organization).where(Organization.name_key == key))
    if item:
        return item
    item = Organization(
        name="The Ohio State University" if key == "the ohio state university" else name,
        name_key=key,
        **fields,
    )
    db.add(item)
    db.flush()
    return item


def save_contact(db, *, contact_id=None, expected_version=None, used_channels=None, **fields):
    fields["name"] = required(fields.get("name"), "Contact name")
    email = (fields.get("email") or "").strip().lower() or None
    if email and not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", email):
        raise ValidationError("Enter a valid email address.")
    profile = (fields.get("profile_url") or "").strip().rstrip("/") or None
    if profile and not profile.startswith(("https://", "http://")):
        raise ValidationError("Profile URL must start with https:// or http://.")
    fields.update(email=email, profile_url=profile)
    candidates = []
    if email:
        candidates.append(Contact.email == email)
    if profile:
        candidates.append(Contact.profile_url == profile)
    if candidates:
        query = select(Contact).where(or_(*candidates))
        if contact_id:
            query = query.where(Contact.id != contact_id)
        if db.scalar(query):
            raise ValidationError("A contact with this email or profile already exists. Open that record.")
    item = db.get(Contact, contact_id) if contact_id else Contact()
    if item is None:
        raise ValidationError("Contact no longer exists.")
    if contact_id and expected_version != item.version:
        raise ValidationError("This contact changed in another session. Refresh before editing.")
    # Same name and organization is ambiguous: require review rather than silently merging.
    if not contact_id:
        duplicate = db.scalar(
            select(Contact).where(
                func.lower(Contact.name) == fields["name"].lower(),
                Contact.organization_id == fields.get("organization_id"),
            )
        )
        if duplicate:
            raise ValidationError("Same name and organization already exist. Review identity before adding.")
    for key, value in fields.items():
        setattr(item, key, value)
    if used_channels is not None:
        requested = set(used_channels)
        item.used_channels = [entry for entry in item.used_channels if entry.channel in requested]
        existing = {entry.channel for entry in item.used_channels}
        item.used_channels.extend(ContactChannel(channel=c) for c in sorted(requested - existing))
    db.add(item)
    db.flush()
    return item


def contacts(db, search="", captured=None, used=None, kind=None, owner=None, *, limit=None, offset=0):
    query = select(Contact).order_by(Contact.name, Contact.id)
    if search:
        # Treat search text literally rather than letting % match the entire database.
        term = "%" + search.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
        query = query.outerjoin(Organization).where(
            or_(
                Contact.name.ilike(term, escape="\\"),
                Contact.email.ilike(term, escape="\\"),
                Organization.name.ilike(term, escape="\\"),
                Contact.interests.ilike(term, escape="\\"),
            )
        )
    if captured:
        query = query.where(Contact.captured_channel == captured)
    if used:
        query = query.where(Contact.used_channels.any(ContactChannel.channel == used))
    if kind:
        query = query.where(Contact.relationship_type == kind)
    if owner:
        query = query.where(Contact.owner == owner)
    if limit is not None:
        query = query.offset(offset).limit(limit)
    return list(db.scalars(query))


def add_interaction(
    db,
    *,
    summary,
    occurred_on,
    contact_id=None,
    next_step="",
    followup_due=None,
    owner="JJ",
    channel="Unassigned",
    **fields,
):
    item = Interaction(
        summary=required(summary, "Summary"),
        occurred_on=occurred_on,
        contact_id=contact_id,
        next_step=next_step,
        channel=channel,
        **fields,
    )
    db.add(item)
    if contact_id:
        contact = db.get(Contact, contact_id)
        if contact is None:
            raise ValidationError("Contact does not exist.")
        if contact.last_contact is None or occurred_on > contact.last_contact:
            contact.last_contact = occurred_on
    if followup_due is not None:
        db.add(
            Task(
                title=required(next_step, "Follow-up action"),
                due_date=followup_due,
                contact_id=contact_id,
                opportunity_id=fields.get("opportunity_id"),
                owner=owner,
                channel=channel,
                provenance=fields.get("provenance", ""),
            )
        )
    db.flush()
    return item


def task_bucket(task, as_of=None):
    as_of = as_of or today()
    if task.status != "Open":
        return task.status
    if task.due_date is None:
        return "Unscheduled"
    if task.due_date < as_of:
        return "Overdue"
    if task.due_date == as_of:
        return "Due today"
    return "Upcoming"


def update_task(db, task_id, expected_version, *, status=None, due_date=None, reschedule=False):
    item = db.get(Task, task_id)
    if item is None or item.version != expected_version:
        raise ValidationError("Task changed in another session. Refresh before editing.")
    if status:
        if status not in {"Open", "Completed", "Cancelled"}:
            raise ValidationError("Invalid task status.")
        item.status = status
        item.completed_at = utcnow() if status == "Completed" else None
    if reschedule:
        if item.status != "Open" or not isinstance(due_date, date):
            raise ValidationError("Only open tasks can be rescheduled to a date.")
        item.due_date = due_date
    db.flush()
    return item

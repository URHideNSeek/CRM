"""Explicit, transactional migration from UR-Company-Memory/CRM CSVs."""

import argparse
import csv
import io
import json
from datetime import date
from pathlib import Path

from sqlalchemy import select

from crm.db import session
from crm.models import Contact, Event, Interaction, Opportunity, Organization, Source, Task
from crm.service import CHANNELS, ValidationError, organization, save_contact

MODELS = {
    "organizations": Organization,
    "people": Contact,
    "events": Event,
    "opportunities": Opportunity,
    "interactions": Interaction,
    "tasks": Task,
    "sources": Source,
}


def parsed_date(value):
    try:
        return date.fromisoformat(value.strip()) if value and value.strip() else None
    except ValueError:
        raise ValidationError(f"Invalid date: {value}. Use YYYY-MM-DD.") from None


def match_contact(db, name):
    matches = list(db.scalars(select(Contact).where(Contact.name == name)))
    return matches[0].id if len(matches) == 1 else None


def import_csvs(db, files):
    """Skip previously imported IDs; never overwrite newer app edits."""
    counts = {"imported": 0, "skipped": 0, "review": []}
    for name, model in MODELS.items():
        if name not in files:
            continue
        rows = csv.DictReader(io.StringIO(files[name].lstrip("\ufeff")))
        for row_number, row in enumerate(rows, start=2):
            id_field = {
                "organizations": "org_id",
                "people": "person_id",
                "events": "event_id",
                "opportunities": "opportunity_id",
                "interactions": "interaction_id",
                "tasks": "task_id",
                "sources": "source_id",
            }[name]
            legacy = row.get(id_field, "").strip()
            if not legacy:
                raise ValidationError(f"{name}.csv row {row_number}: missing {id_field}")
            if db.scalar(select(model).where(model.legacy_id == legacy)):
                counts["skipped"] += 1
                continue
            source_channel = row.get("source") if row.get("source") in CHANNELS else "Unassigned"
            common = {
                "legacy_id": legacy,
                "legacy_data": row,
                "provenance": f"UR-Company-Memory/CRM/{name}.csv#{legacy}; {row.get('source', '')}",
            }
            item = None
            if name == "organizations":
                item = organization(
                    db, row["organization"], kind=row.get("type", "Other"), notes=row.get("notes", "")
                )
                if item.legacy_id:
                    counts["review"].append(f"{name}:{legacy}: normalized organization already imported")
                    continue
                for key, value in common.items():
                    setattr(item, key, value)
            elif name == "people":
                org = organization(db, row["organization"]) if row.get("organization") else None
                # Unknown capture provenance stays Unassigned; do not guess channels from relationship type.
                captured = row.get("captured_channel") or (
                    row.get("source") if row.get("source") in CHANNELS else "Unassigned"
                )
                used = [v.strip() for v in row.get("used_channels", "").split("|") if v.strip()]
                try:
                    with db.begin_nested():
                        item = save_contact(
                            db,
                            name=row["name"],
                            title=row.get("title", ""),
                            organization_id=org.id if org else None,
                            email=row.get("email"),
                            relationship_type=row.get("relationship_type", "Other"),
                            captured_channel=captured,
                            used_channels=used,
                            status=row.get("status", "New"),
                            interests=row.get("products_of_interest", ""),
                            last_contact=parsed_date(row.get("last_contact")),
                            **common,
                        )
                except ValidationError as exc:
                    counts["review"].append(f"people:{legacy}: {exc}")
                    continue
            elif name == "events":
                item = Event(
                    name=row["event"],
                    event_date=parsed_date(row.get("date")),
                    location=row.get("location", ""),
                    status=row.get("status", "Planned"),
                    notes=row.get("crm_value", ""),
                    **common,
                )
            elif name == "opportunities":
                org = organization(db, row["agency_or_org"]) if row.get("agency_or_org") else None
                item = Opportunity(
                    name=row["name"],
                    kind=row.get("type", "Other"),
                    organization_id=org.id if org else None,
                    stage=row.get("status", "Identified"),
                    fit=row.get("fit", "Unknown"),
                    next_action=row.get("next_action", ""),
                    **common,
                )
            elif name == "interactions":
                item = Interaction(
                    contact_id=match_contact(db, row.get("person_or_org", "")),
                    occurred_on=parsed_date(row.get("date")),
                    kind=row.get("type", "Note"),
                    summary=row["summary"],
                    next_step=row.get("next_step", ""),
                    channel=source_channel,
                    **common,
                )
                if item.occurred_on is None:
                    raise ValidationError(f"interactions:{legacy}: date is required")
                if item.contact_id is None:
                    counts["review"].append(
                        f"interactions:{legacy}: relationship unresolved; original target preserved"
                    )
            elif name == "tasks":
                raw_status = row.get("status", "open").lower()
                status = {
                    "open": "Open",
                    "pending": "Open",
                    "completed": "Completed",
                    "done": "Completed",
                    "cancelled": "Cancelled",
                    "canceled": "Cancelled",
                }.get(raw_status, "Open")
                if raw_status not in {"open", "pending", "completed", "done", "cancelled", "canceled"}:
                    counts["review"].append(f"tasks:{legacy}: unknown status mapped to Open; review required")
                item = Task(
                    title=row["task"],
                    owner=row.get("owner", "JJ"),
                    contact_id=match_contact(db, row.get("related_person_or_org", "")),
                    due_date=parsed_date(row.get("due_date")),
                    channel=source_channel,
                    priority=row.get("priority", "medium").capitalize(),
                    status=status,
                    **common,
                )
            elif name == "sources":
                item = Source(
                    name=row["name"],
                    kind=row.get("source_type", "chat"),
                    date_range=row.get("date_range", ""),
                    notes=row.get("notes", ""),
                    **common,
                )
            db.add(item)
            db.flush()
            counts["imported"] += 1
    return counts


def export_json(db):
    output = {}
    for table in db.bind.dialect.get_table_names(db.connection()):
        if table not in __import__("crm.models", fromlist=["Base"]).Base.metadata.tables:
            continue
        from crm.models import Base

        output[table] = [dict(row) for row in db.execute(select(Base.metadata.tables[table])).mappings()]
    return json.dumps(output, default=str, indent=2)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("folder", type=Path)
    args = parser.parse_args()
    files = {
        name: (args.folder / f"{name}.csv").read_text(encoding="utf-8-sig")
        for name in MODELS
        if (args.folder / f"{name}.csv").exists()
    }
    if not files:
        parser.error("No supported CRM CSVs in folder")
    with session() as db:
        result = import_csvs(db, files)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()

from datetime import date, timedelta

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session
from sqlalchemy.orm.exc import StaleDataError

from crm.import_export import export_json, import_csvs
from crm.models import Contact, Interaction, Reminder, Task
from crm.reminders import active_reminders, generate
from crm.service import (
    ValidationError,
    add_interaction,
    contacts,
    organization,
    save_contact,
    task_bucket,
    update_task,
)


def test_shared_channels_and_capture_filters(db):
    vendor = save_contact(
        db,
        name="Vendor",
        email="  REP@EXAMPLE.COM ",
        captured_channel="UR Partners",
        relationship_type="Vendor",
        used_channels=["UR Partners", "UR Private BD"],
    )
    assert vendor.email == "rep@example.com"
    assert contacts(db, captured="UR Partners") == [vendor]
    assert contacts(db, used="UR Private BD") == [vendor]
    assert contacts(db, captured="UR Private BD") == []
    assert len(contacts(db)) == 1  # Channel classification never restricts access.
    save_contact(
        db,
        contact_id=vendor.id,
        expected_version=vendor.version,
        name="Vendor",
        email=vendor.email,
        used_channels=["UR Private BD", "UR IT"],
    )
    assert {c.channel for c in vendor.used_channels} == {"UR Private BD", "UR IT"}


def test_identity_validation_and_dedupe(db):
    save_contact(db, name="Person", email="person@example.com", profile_url="https://example.com/person/")
    with pytest.raises(ValidationError):
        save_contact(db, name="Person 2", email="PERSON@example.com")
    with pytest.raises(ValidationError):
        save_contact(db, name="Person 2", profile_url="https://example.com/person")
    with pytest.raises(ValidationError):
        save_contact(db, name="Person", email="different@example.com")
    with pytest.raises(ValidationError):
        save_contact(db, name="Bad", email="invalid")
    assert contacts(db, search="%") == []
    assert organization(db, "OSU").id == organization(db, "The Ohio State University").id


def test_interaction_history_and_atomic_followup(db):
    contact = save_contact(db, name="Contact")
    day = date(2026, 10, 13)
    add_interaction(
        db,
        summary="Promised brief",
        occurred_on=day,
        contact_id=contact.id,
        next_step="Send brief",
        followup_due=day,
        channel="UR Partners",
    )
    add_interaction(db, summary="Earlier note", occurred_on=day - timedelta(days=1), contact_id=contact.id)
    assert contact.last_contact == day
    assert db.scalar(select(func.count()).select_from(Interaction)) == 2
    assert db.scalar(select(Task)).title == "Send brief"
    with pytest.raises(ValidationError), db.begin_nested():
        add_interaction(
            db,
            summary="Will roll back",
            occurred_on=day,
            contact_id=contact.id,
            next_step="",
            followup_due=day,
        )
    assert db.scalar(select(func.count()).select_from(Interaction)) == 2


def test_reminder_idempotency_snooze_and_completion(db):
    day = date(2026, 10, 13)
    overdue = Task(title="Follow up", due_date=day - timedelta(days=1))
    unscheduled = Task(title="Choose date")
    future = Task(title="Later", due_date=day + timedelta(days=5))
    db.add_all([overdue, unscheduled, future])
    db.flush()
    assert task_bucket(overdue, day) == "Overdue"
    assert task_bucket(unscheduled, day) == "Unscheduled"
    assert generate(db, day) == 1
    assert generate(db, day) == 0
    assert len(active_reminders(db, day)) == 1
    update_task(db, overdue.id, overdue.version, reschedule=True, due_date=day + timedelta(days=10))
    assert active_reminders(db, day) == []
    update_task(db, overdue.id, overdue.version, reschedule=True, due_date=day)
    assert generate(db, day) == 1
    update_task(db, overdue.id, overdue.version, status="Completed")
    assert active_reminders(db, day) == []
    assert generate(db, day) == 0
    assert overdue.completed_at is not None
    assert db.scalar(select(func.count()).select_from(Reminder)) == 2


def test_stale_edits_rejected(db):
    contact = save_contact(db, name="Old")
    old_version = contact.version
    save_contact(db, contact_id=contact.id, expected_version=old_version, name="New")
    with pytest.raises(ValidationError):
        save_contact(db, contact_id=contact.id, expected_version=old_version, name="Stale")


def test_database_rejects_concurrent_contact_edit(db):
    contact = save_contact(db, name="Original")
    with Session(db.bind, join_transaction_mode="create_savepoint") as other:
        stale = other.get(Contact, contact.id)
        contact.name = "First"
        db.flush()
        stale.name = "Second"
        with pytest.raises(StaleDataError):
            other.flush()
        other.rollback()


def test_legacy_import_repeat_preserves_edits_and_provenance(db):
    files = {
        "people": "person_id,name,organization,email,last_contact,source\nP1,Person,OSU,p@example.com,2026-10-10,UR Partners\n",
        "tasks": "task_id,owner,related_person_or_org,due_date,priority,task,status,source\nT1,JJ,Person,,high,Call,open,UR Partners\n",
        "interactions": "interaction_id,date,person_or_org,type,summary,source,next_step\nI1,2026-10-10,Person,email,Hello,UR Partners,Call\n",
    }
    assert import_csvs(db, files)["imported"] == 3
    contact = db.scalar(select(Contact))
    contact.notes = "Updated in app"
    db.flush()
    result = import_csvs(db, files)
    assert result["skipped"] == 3
    assert contact.notes == "Updated in app"
    assert contact.captured_channel == "UR Partners"
    assert contact.legacy_data["source"] == "UR Partners"
    task = db.scalar(select(Task))
    assert task.due_date is None and task.contact_id == contact.id
    assert "Updated in app" in export_json(db)


def test_ambiguous_import_requires_review(db):
    save_contact(db, name="Person", email="p@example.com")
    result = import_csvs(db, {"people": "person_id,name,email\nP1,New name,p@example.com\n"})
    assert result["imported"] == 0 and result["review"]
    assert db.scalar(select(func.count()).select_from(Contact)) == 1

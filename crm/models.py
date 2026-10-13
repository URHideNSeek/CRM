from datetime import UTC, date, datetime
from uuid import uuid4

from sqlalchemy import (
    JSON,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def uid():
    return str(uuid4())


def utcnow():
    return datetime.now(UTC)


class Base(DeclarativeBase):
    pass


class Record:
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    legacy_id: Mapped[str | None] = mapped_column(String(100), unique=True)
    provenance: Mapped[str] = mapped_column(Text, default="")
    legacy_data: Mapped[dict] = mapped_column(JSON, default=dict)


class Organization(Record, Base):
    __tablename__ = "organizations"
    name: Mapped[str] = mapped_column(String(250))
    name_key: Mapped[str] = mapped_column(String(250), unique=True)
    kind: Mapped[str] = mapped_column(String(100), default="Other")
    website: Mapped[str] = mapped_column(Text, default="")
    notes: Mapped[str] = mapped_column(Text, default="")


class ContactChannel(Base):
    __tablename__ = "contact_channels"
    contact_id: Mapped[str] = mapped_column(ForeignKey("contacts.id"), primary_key=True)
    channel: Mapped[str] = mapped_column(String(100), primary_key=True)


class Contact(Record, Base):
    __tablename__ = "contacts"
    name: Mapped[str] = mapped_column(String(250))
    title: Mapped[str] = mapped_column(String(250), default="")
    organization_id: Mapped[str | None] = mapped_column(ForeignKey("organizations.id"), index=True)
    organization: Mapped[Organization | None] = relationship()
    email: Mapped[str | None] = mapped_column(String(320), unique=True)
    phone: Mapped[str] = mapped_column(String(100), default="")
    profile_url: Mapped[str | None] = mapped_column(Text, unique=True)
    relationship_type: Mapped[str] = mapped_column(String(100), default="Other", index=True)
    captured_channel: Mapped[str] = mapped_column(String(100), default="Unassigned", index=True)
    used_channels: Mapped[list[ContactChannel]] = relationship(cascade="all, delete-orphan", lazy="selectin")
    owner: Mapped[str] = mapped_column(String(150), default="JJ")
    status: Mapped[str] = mapped_column(String(100), default="New")
    priority: Mapped[str] = mapped_column(String(20), default="Medium")
    interests: Mapped[str] = mapped_column(Text, default="")
    notes: Mapped[str] = mapped_column(Text, default="")
    last_contact: Mapped[date | None] = mapped_column(Date)
    version: Mapped[int] = mapped_column(Integer, default=1)
    __mapper_args__ = {"version_id_col": version}


class Event(Record, Base):
    __tablename__ = "events"
    name: Mapped[str] = mapped_column(String(250))
    event_date: Mapped[date | None] = mapped_column(Date)
    location: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(100), default="Planned")
    notes: Mapped[str] = mapped_column(Text, default="")


class Opportunity(Record, Base):
    __tablename__ = "opportunities"
    name: Mapped[str] = mapped_column(String(250))
    organization_id: Mapped[str | None] = mapped_column(ForeignKey("organizations.id"))
    organization: Mapped[Organization | None] = relationship()
    contact_id: Mapped[str | None] = mapped_column(ForeignKey("contacts.id"))
    contact: Mapped[Contact | None] = relationship()
    channel: Mapped[str] = mapped_column(String(100), default="Unassigned", index=True)
    kind: Mapped[str] = mapped_column(String(100), default="Commercial")
    stage: Mapped[str] = mapped_column(String(100), default="Identified", index=True)
    fit: Mapped[str] = mapped_column(String(100), default="Unknown")
    value: Mapped[int | None] = mapped_column(Integer)
    deadline: Mapped[date | None] = mapped_column(Date)
    next_action: Mapped[str] = mapped_column(Text, default="")
    owner: Mapped[str] = mapped_column(String(150), default="JJ")
    notes: Mapped[str] = mapped_column(Text, default="")
    version: Mapped[int] = mapped_column(Integer, default=1)
    __mapper_args__ = {"version_id_col": version}


class Interaction(Record, Base):
    __tablename__ = "interactions"
    contact_id: Mapped[str | None] = mapped_column(ForeignKey("contacts.id"), index=True)
    organization_id: Mapped[str | None] = mapped_column(ForeignKey("organizations.id"))
    opportunity_id: Mapped[str | None] = mapped_column(ForeignKey("opportunities.id"))
    event_id: Mapped[str | None] = mapped_column(ForeignKey("events.id"))
    occurred_on: Mapped[date] = mapped_column(Date, index=True)
    kind: Mapped[str] = mapped_column(String(100), default="Note")
    channel: Mapped[str] = mapped_column(String(100), default="Unassigned")
    summary: Mapped[str] = mapped_column(Text)
    next_step: Mapped[str] = mapped_column(Text, default="")
    recorded_by: Mapped[str] = mapped_column(String(320), default="")


class Insight(Record, Base):
    __tablename__ = "insights"
    contact_id: Mapped[str | None] = mapped_column(ForeignKey("contacts.id"))
    contact: Mapped[Contact | None] = relationship()
    opportunity_id: Mapped[str | None] = mapped_column(ForeignKey("opportunities.id"))
    channel: Mapped[str] = mapped_column(String(100), default="Unassigned", index=True)
    kind: Mapped[str] = mapped_column(String(100), default="Customer need")
    summary: Mapped[str] = mapped_column(Text)
    implication: Mapped[str] = mapped_column(Text, default="")


class Task(Record, Base):
    __tablename__ = "tasks"
    contact_id: Mapped[str | None] = mapped_column(ForeignKey("contacts.id"), index=True)
    contact: Mapped[Contact | None] = relationship()
    opportunity_id: Mapped[str | None] = mapped_column(ForeignKey("opportunities.id"))
    opportunity: Mapped[Opportunity | None] = relationship()
    channel: Mapped[str] = mapped_column(String(100), default="Unassigned", index=True)
    owner: Mapped[str] = mapped_column(String(150), default="JJ")
    title: Mapped[str] = mapped_column(Text)
    due_date: Mapped[date | None] = mapped_column(Date)
    priority: Mapped[str] = mapped_column(String(20), default="Medium")
    status: Mapped[str] = mapped_column(String(20), default="Open")
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    version: Mapped[int] = mapped_column(Integer, default=1)
    __mapper_args__ = {"version_id_col": version}
    __table_args__ = (
        CheckConstraint("status IN ('Open', 'Completed', 'Cancelled')"),
        CheckConstraint("priority IN ('High', 'Medium', 'Low')"),
        Index("ix_tasks_due_status", "status", "due_date"),
    )


class Reminder(Base):
    __tablename__ = "reminders"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    task_id: Mapped[str] = mapped_column(ForeignKey("tasks.id"), index=True)
    task: Mapped[Task] = relationship()
    day: Mapped[date] = mapped_column(Date)
    due_snapshot: Mapped[date] = mapped_column(Date)
    acknowledged_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    __table_args__ = (UniqueConstraint("task_id", "day", "due_snapshot", name="uq_reminder_day"),)


class Source(Record, Base):
    __tablename__ = "sources"
    name: Mapped[str] = mapped_column(String(250))
    kind: Mapped[str] = mapped_column(String(100), default="chat")
    date_range: Mapped[str] = mapped_column(Text, default="")
    notes: Mapped[str] = mapped_column(Text, default="")


class ApiReceipt(Base):
    __tablename__ = "api_receipts"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    principal: Mapped[str] = mapped_column(String(150))
    key: Mapped[str] = mapped_column(String(100))
    fingerprint: Mapped[str] = mapped_column(String(64))
    response: Mapped[dict] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    __table_args__ = (UniqueConstraint("principal", "key", name="uq_api_receipt"),)

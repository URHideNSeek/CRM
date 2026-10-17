from datetime import date, timedelta
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from crm.models import Base, Contact, Event, Task, Interaction
from crm.event_outreach import add_meeting_requests, event_tasks, event_meetings, suggest_contacts
from crm.service import today

def test_event_scan_reuses_followups_and_deduplicates():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        c = Contact(name="Example", interests="Springfield UAS testing", owner="JJ")
        e = Event(name="Springfield UAS Conference", event_date=today() + timedelta(days=15), location="Ohio")
        db.add_all([c,e]); db.flush()
        assert suggest_contacts(db,e)
        assert add_meeting_requests(db,e,[c.id,c.id]) == 1
        assert add_meeting_requests(db,e,[c.id]) == 0
        assert len(event_tasks(db,e.id)) == 1
        task = event_tasks(db,e.id)[0]
        assert task.channel == "UR Events" and task.contact_id == c.id
        assert task.status == "Open"
        db.add(Interaction(event_id=e.id, occurred_on=today(), summary="Testing",
            legacy_data={"meeting_time":"2026-10-27 10:00","meeting_with":"Example"}))
        db.flush()
        assert len(event_meetings(db,e.id)) == 1

"""Durable in-app reminders; no external messages are sent."""

import argparse
import logging
import time
from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from crm.db import session
from crm.models import Reminder, Task
from crm.service import today


def generate(db, as_of=None, horizon=2):
    as_of = as_of or today()
    tasks = db.scalars(
        select(Task).where(
            Task.status == "Open",
            Task.due_date.is_not(None),
            Task.due_date <= as_of + timedelta(days=horizon),
        )
    )
    insert = pg_insert if db.bind.dialect.name == "postgresql" else sqlite_insert
    count = 0
    for task in tasks:
        result = db.execute(
            insert(Reminder)
            .values(task_id=task.id, day=as_of, due_snapshot=task.due_date)
            .on_conflict_do_nothing(index_elements=["task_id", "day", "due_snapshot"])
        )
        count += result.rowcount
    return count


def active_reminders(db, as_of=None):
    as_of = as_of or today()
    return list(
        db.scalars(
            select(Reminder)
            .join(Task)
            .where(
                Task.status == "Open",
                Reminder.day == as_of,
                Reminder.due_snapshot == Task.due_date,
                Reminder.acknowledged_at.is_(None),
            )
            .order_by(Task.due_date, Task.priority)
        )
    )


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--loop", action="store_true")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO)
    while True:
        try:
            with session() as db:
                count = generate(db)
            logging.info("Generated %s reminder records", count)
        except Exception as exc:
            # Keep the worker alive through transient database failures without logging credentials.
            logging.error("Reminder generation failed (%s)", type(exc).__name__)
            if not args.loop:
                raise SystemExit(1) from None
        if not args.loop:
            break
        time.sleep(60)


if __name__ == "__main__":
    main()

import json
from collections import Counter
from datetime import timedelta

import streamlit as st
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm.exc import StaleDataError

from crm.auth import require_user
from crm.db import session
from crm.import_export import export_json, import_csvs
from crm.models import Contact, Event, Insight, Interaction, Opportunity, Organization, Task, utcnow
from crm.reminders import active_reminders, generate
from crm.service import (
    CHANNELS,
    STAGES,
    TYPES,
    ValidationError,
    add_interaction,
    contacts,
    organization,
    required,
    save_contact,
    task_bucket,
    today,
    update_task,
)
from crm.ui import chips, contact_profile, header, navigate, pipeline, style, task_cards

st.set_page_config(page_title="Unseen Robotics CRM", page_icon="🧭", layout="wide")
style()
actor = require_user()
st.sidebar.title("UR / CRM")
st.sidebar.caption("RELATIONSHIPS → NEXT ACTIONS")
page = st.sidebar.radio(
    "Workspace",
    [
        "Overview",
        "Contacts",
        "Organizations",
        "Opportunities",
        "Customer insights",
        "Events",
        "Follow-ups",
        "Reminder inbox",
        "Import & export",
    ],
    key="workspace_page",
)
st.sidebar.caption("Channels classify relationships. All approved users share access.")
if st.sidebar.button("Refresh"):
    for key in list(st.session_state):
        if key.startswith("expected_"):
            del st.session_state[key]
    st.rerun()


def options(items, label):
    return {item.id: label(item) for item in items}


def choose(label, labels, key=None):
    return st.selectbox(label, [None, *labels], format_func=lambda x: labels.get(x, "None"), key=key)


def select_existing(label, values, current, key=None):
    choices = list(dict.fromkeys([*values, current]))
    return st.selectbox(label, choices, index=choices.index(current), key=key)


def show_table(rows):
    if rows:
        st.dataframe(rows, hide_index=True, width="stretch")
    else:
        st.info("No records yet. Add a record or import your existing CRM files.")


def contact_row(c):
    return {
        "Name": c.name,
        "Organization": c.organization.name if c.organization else "",
        "Email": c.email or "",
        "Relationship": c.relationship_type,
        "Captured by": c.captured_channel,
        "Used by": ", ".join(v.channel for v in c.used_channels),
        "Owner": c.owner,
        "Priority": c.priority,
        "Status": c.status,
        "Last contact": c.last_contact,
    }


def task_row(t):
    return {
        "Action": t.title,
        "Contact": t.contact.name if t.contact else t.legacy_data.get("related_person_or_org", ""),
        "Opportunity": t.opportunity.name if t.opportunity else "",
        "Due": t.due_date,
        "Timing": task_bucket(t),
        "Owner": t.owner,
        "Channel": t.channel,
        "Priority": t.priority,
    }


def contact_form(db, item=None):
    orgs = options(list(db.scalars(select(Organization).order_by(Organization.name))), lambda o: o.name)
    identifier = item.id if item else "new"
    version_key = f"expected_contact_{identifier}"
    if item and version_key not in st.session_state:
        st.session_state[version_key] = item.version
    with st.form(f"contact_{identifier}"):
        st.subheader("Edit contact" if item else "Add contact")
        a, b = st.columns(2)
        with a:
            name = st.text_input("Name", value=item.name if item else "")
            title = st.text_input("Title", value=item.title if item else "")
            org_ids = [None, *orgs]
            org_id = st.selectbox(
                "Organization",
                org_ids,
                index=org_ids.index(item.organization_id) if item else 0,
                format_func=lambda x: orgs.get(x, "None"),
            )
            email = st.text_input("Professional email", value=item.email or "" if item else "")
            phone = st.text_input("Business phone", value=item.phone if item else "")
            profile = st.text_input("Profile URL", value=item.profile_url or "" if item else "")
        with b:
            kind = select_existing("Relationship type", TYPES, item.relationship_type if item else "Other")
            capture = select_existing(
                "Captured by channel", CHANNELS, item.captured_channel if item else "Unassigned"
            )
            current_used = [v.channel for v in item.used_channels] if item else []
            used = st.multiselect(
                "Used by channels", list(dict.fromkeys(CHANNELS + current_used)), default=current_used
            )
            owner = st.text_input("Relationship owner", value=item.owner if item else "JJ")
            priority = select_existing(
                "Priority", ["High", "Medium", "Low"], item.priority if item else "Medium"
            )
            status = select_existing(
                "Status",
                ["New", "Active", "Nurture", "Inactive", "Needs review"],
                item.status if item else "New",
            )
        interests = st.text_input("Interests / capabilities", value=item.interests if item else "")
        notes = st.text_area("Context / introductions / relationship notes", value=item.notes if item else "")
        provenance = st.text_input("Source / provenance", value=item.provenance if item else "")
        if st.form_submit_button("Save contact", type="primary"):
            save_contact(
                db,
                contact_id=item.id if item else None,
                expected_version=st.session_state.get(version_key),
                name=name,
                title=title,
                organization_id=org_id,
                email=email,
                phone=phone,
                profile_url=profile,
                relationship_type=kind,
                captured_channel=capture,
                used_channels=used,
                owner=required(owner, "Owner"),
                priority=priority,
                status=status,
                interests=interests,
                notes=notes,
                provenance=provenance,
            )
            db.commit()
            st.session_state.pop(version_key, None)
            st.success("Contact saved.")
            st.rerun()


def run(db):
    header(page)
    all_contacts = contacts(db)
    all_tasks = list(db.scalars(select(Task).order_by(Task.due_date.asc().nulls_last())))
    all_opps = list(db.scalars(select(Opportunity).order_by(Opportunity.name)))
    all_events = list(db.scalars(select(Event).order_by(Event.event_date.desc().nulls_last())))
    contact_labels = options(
        all_contacts, lambda c: f"{c.name} · {c.organization.name if c.organization else 'No organization'}"
    )
    opp_labels = options(all_opps, lambda o: o.name)
    event_labels = options(all_events, lambda e: e.name)
    if page == "Overview":
        a, b, c, d = st.columns(4)
        a.metric("Contacts", len(all_contacts))
        b.metric("Overdue", sum(task_bucket(t) == "Overdue" for t in all_tasks))
        c.metric("Due today", sum(task_bucket(t) == "Due today" for t in all_tasks))
        d.metric("Active opportunities", sum(o.stage not in {"Won", "Lost"} for o in all_opps))
        st.divider()
        owner = st.selectbox(
            "Focus on owner",
            [None, *sorted({t.owner for t in all_tasks})],
            format_func=lambda x: x or "Everyone",
        )
        scoped = [t for t in all_tasks if not owner or t.owner == owner]
        focus, context = st.columns([1.4, 1])
        with focus:
            st.subheader("Your next moves")
            tab_due, tab_week, tab_unscheduled = st.tabs(["Needs attention", "Next 7 days", "Needs a date"])
            with tab_due:
                task_cards(
                    db, [t for t in scoped if task_bucket(t) in {"Overdue", "Due today"}], prefix="due"
                )
            with tab_week:
                task_cards(
                    db,
                    [
                        t
                        for t in scoped
                        if t.status == "Open"
                        and t.due_date
                        and today() < t.due_date <= today() + timedelta(days=7)
                    ],
                    prefix="week",
                )
            with tab_unscheduled:
                task_cards(db, [t for t in scoped if task_bucket(t) == "Unscheduled"], prefix="undated")
            st.button("Open all follow-ups", on_click=navigate, args=("Follow-ups",))
        with context:
            st.subheader("Opportunity progress")
            counts = Counter(o.stage for o in all_opps)
            if counts:
                st.bar_chart(
                    [{"Stage": k, "Count": v} for k, v in counts.items()],
                    x="Stage",
                    y="Count",
                    color="#00857c",
                )
            else:
                st.info("Add an opportunity to start tracking your pipeline.")
            st.subheader("Channels using contacts")
            usage = Counter(v.channel for c in all_contacts for v in c.used_channels)
            if usage:
                st.bar_chart(
                    [{"Channel": k, "Contacts": v} for k, v in usage.items()],
                    x="Channel",
                    y="Contacts",
                    color="#3d6688",
                )
            else:
                st.caption("Assign usage channels on contact records to see cross-company relationships.")
            st.subheader("Recent conversations")
            recent = list(
                db.scalars(
                    select(Interaction)
                    .order_by(Interaction.occurred_on.desc(), Interaction.created_at.desc())
                    .limit(4)
                )
            )
            for interaction in recent:
                with st.container(border=True):
                    st.caption(f"{interaction.occurred_on} · {interaction.channel} · {interaction.kind}")
                    st.write(interaction.summary)
            if not recent:
                st.caption("Log your first conversation from a contact record.")
        st.divider()
        st.subheader("Relationships needing follow-through")
        active_contacts = {t.contact_id for t in all_tasks if t.status == "Open"}
        show_table(
            [contact_row(c) for c in all_contacts if c.id not in active_contacts and c.status != "Inactive"]
        )
        st.caption("Contacts without an open next action; review whether a follow-up is needed.")
    elif page == "Contacts":
        a, b, c, d = st.columns(4)
        search = a.text_input("Search name, organization, email, interests")
        captured = b.selectbox("Captured by", [None, *CHANNELS], format_func=lambda x: x or "All")
        used = c.selectbox("Used by", [None, *CHANNELS], format_func=lambda x: x or "All")
        kind_values = sorted({*TYPES, *(c.relationship_type for c in all_contacts)})
        kind = d.selectbox("Relationship", [None, *kind_values], format_func=lambda x: x or "All")
        owners = sorted({c.owner for c in all_contacts})
        owner_col, status_col = st.columns(2)
        owner = owner_col.selectbox("Contact owner", [None, *owners], format_func=lambda x: x or "All")
        status = status_col.selectbox(
            "Contact status",
            [None, *sorted({c.status for c in all_contacts})],
            format_func=lambda x: x or "All",
        )
        filtered = contacts(db, search, captured, used, kind, owner)
        if status:
            filtered = [c for c in filtered if c.status == status]
        st.caption(f"{len(filtered)} of {len(all_contacts)} contacts · filters do not restrict access")
        show_table([contact_row(c) for c in filtered])
        selected = choose("Open contact", options(filtered, lambda c: contact_labels[c.id]))
        with st.expander("Add contact", expanded=not all_contacts):
            contact_form(db)
        if selected:
            item = db.get(Contact, selected)
            contact_profile(item, all_tasks, all_opps)
            with st.expander("Edit contact details"):
                contact_form(db, item)
            if item.legacy_data:
                with st.expander("Original imported record"):
                    st.json(item.legacy_data)
            st.subheader("Conversation history")
            history = list(
                db.scalars(
                    select(Interaction)
                    .where(Interaction.contact_id == selected)
                    .order_by(Interaction.occurred_on.desc(), Interaction.created_at.desc())
                )
            )
            show_table(
                [
                    {
                        "Date": i.occurred_on,
                        "Type": i.kind,
                        "Channel": i.channel,
                        "Summary": i.summary,
                        "Next step": i.next_step,
                        "Source": i.provenance,
                    }
                    for i in history
                ]
            )
            with st.form("interaction"):
                st.subheader("Log conversation")
                day = st.date_input("Conversation date", today())
                interaction_kind = st.selectbox("Type", ["Email", "Call", "Meeting", "Introduction", "Note"])
                channel = st.selectbox("Channel", CHANNELS)
                event = choose("Related event", event_labels)
                opp = choose("Related opportunity", opp_labels)
                summary = st.text_area("What happened / commitments")
                source = st.text_input("Evidence / source")
                next_step = st.text_input("Next action")
                schedule = st.checkbox("Create follow-up task")
                due = st.date_input("Follow-up due", today() + timedelta(days=3))
                if st.form_submit_button("Log interaction"):
                    add_interaction(
                        db,
                        summary=summary,
                        occurred_on=day,
                        contact_id=selected,
                        kind=interaction_kind,
                        channel=channel,
                        event_id=event,
                        opportunity_id=opp,
                        recorded_by=actor,
                        provenance=source,
                        next_step=next_step,
                        followup_due=due if schedule else None,
                        owner=item.owner,
                    )
                    db.commit()
                    st.rerun()
            st.subheader("Related opportunities and follow-ups")
            show_table(
                [
                    {"Opportunity": o.name, "Stage": o.stage, "Next action": o.next_action}
                    for o in all_opps
                    if o.contact_id == selected
                ]
            )
            show_table([task_row(t) for t in all_tasks if t.contact_id == selected])
    elif page == "Organizations":
        orgs = list(db.scalars(select(Organization).order_by(Organization.name)))
        show_table(
            [{"Organization": o.name, "Type": o.kind, "Website": o.website, "Notes": o.notes} for o in orgs]
        )
        with st.form("org"):
            name = st.text_input("Organization name")
            kind = st.selectbox(
                "Organization type", ["Company", "Government", "University", "Investor", "Other"]
            )
            website = st.text_input("Website")
            notes = st.text_area("Organization context")
            if st.form_submit_button("Add organization"):
                organization(db, name, kind=kind, website=website, notes=notes)
                db.commit()
                st.rerun()
    elif page == "Opportunities":
        filter_channel = st.selectbox("Filter channel", [None, *CHANNELS], format_func=lambda x: x or "All")
        filtered = [o for o in all_opps if not filter_channel or o.channel == filter_channel]
        with st.expander("Pipeline board", expanded=True):
            pipeline(filtered)
        show_table(
            [
                {
                    "Opportunity": o.name,
                    "Organization": o.organization.name if o.organization else "",
                    "Contact": contact_labels.get(o.contact_id, ""),
                    "Stage": o.stage,
                    "Fit": o.fit,
                    "Channel": o.channel,
                    "Value ($)": o.value,
                    "Deadline": o.deadline,
                    "Owner": o.owner,
                    "Next action": o.next_action,
                }
                for o in filtered
            ]
        )
        selected = choose("Edit opportunity (None to add)", options(filtered, lambda o: o.name))
        item = db.get(Opportunity, selected) if selected else None
        orgs = options(list(db.scalars(select(Organization))), lambda o: o.name)
        version_key = f"expected_opp_{selected}"
        if item and version_key not in st.session_state:
            st.session_state[version_key] = item.version
        with st.form(f"opp_{selected}"):
            name = st.text_input("Opportunity name", item.name if item else "")
            ids = [None, *orgs]
            org = st.selectbox(
                "Organization",
                ids,
                index=ids.index(item.organization_id) if item else 0,
                format_func=lambda x: orgs.get(x, "None"),
            )
            cids = [None, *contact_labels]
            contact = st.selectbox(
                "Primary contact",
                cids,
                index=cids.index(item.contact_id) if item else 0,
                format_func=lambda x: contact_labels.get(x, "None"),
            )
            channel = select_existing("Owning channel", CHANNELS, item.channel if item else "Unassigned")
            kind = st.text_input("Opportunity type", item.kind if item else "Commercial")
            stage = select_existing("Stage", STAGES, item.stage if item else "Identified")
            fit = st.text_input("Fit / qualification", item.fit if item else "Unknown")
            known_value = st.checkbox("Value known", value=item is not None and item.value is not None)
            value = st.number_input("Estimated value ($)", min_value=0, value=item.value or 0 if item else 0)
            deadline = st.date_input("Deadline (optional)", value=item.deadline if item else None)
            owner = st.text_input("Owner", item.owner if item else "JJ")
            action = st.text_area("Next action", item.next_action if item else "")
            notes = st.text_area("Notes", item.notes if item else "")
            if st.form_submit_button("Save opportunity"):
                if item and item.version != st.session_state[version_key]:
                    raise ValidationError("Opportunity changed in another session. Refresh before editing.")
                record = item or Opportunity()
                for key, val in dict(
                    name=required(name, "Name"),
                    organization_id=org,
                    contact_id=contact,
                    channel=channel,
                    kind=kind,
                    stage=stage,
                    fit=fit,
                    value=int(value) if known_value else None,
                    deadline=deadline,
                    owner=required(owner, "Owner"),
                    next_action=action,
                    notes=notes,
                ).items():
                    setattr(record, key, val)
                db.add(record)
                db.commit()
                st.session_state.pop(version_key, None)
                st.rerun()
        st.caption(
            "Create a dated task under Follow-ups to turn an opportunity's next action into a reminder."
        )
    elif page == "Customer insights":
        records = list(db.scalars(select(Insight).order_by(Insight.created_at.desc())))
        show_table(
            [
                {
                    "Insight": i.summary,
                    "Type": i.kind,
                    "Implication": i.implication,
                    "Contact": contact_labels.get(i.contact_id, ""),
                    "Channel": i.channel,
                    "Source": i.provenance,
                }
                for i in records
            ]
        )
        with st.form("insight"):
            contact = choose("Contact", contact_labels)
            opp = choose("Opportunity", opp_labels)
            channel = st.selectbox("Channel", CHANNELS)
            kind = st.selectbox(
                "Insight type",
                ["Customer need", "Positive signal", "Objection", "Requirement", "Introduction"],
            )
            summary = st.text_area("Customer feedback / observation")
            implication = st.text_area("What this means for our product or pursuit")
            source = st.text_input("Source / evidence")
            if st.form_submit_button("Capture insight"):
                db.add(
                    Insight(
                        contact_id=contact,
                        opportunity_id=opp,
                        channel=channel,
                        kind=kind,
                        summary=required(summary, "Feedback"),
                        implication=implication,
                        provenance=source,
                    )
                )
                db.commit()
                st.rerun()
    elif page == "Events":
        show_table(
            [
                {
                    "Event": e.name,
                    "Date": e.event_date,
                    "Location": e.location,
                    "Status": e.status,
                    "Context": e.notes,
                }
                for e in all_events
            ]
        )
        with st.form("event"):
            name = st.text_input("Event name")
            day = st.date_input("Event date", value=None)
            location = st.text_input("Location")
            status = st.selectbox("Event status", ["Planned", "Registered", "Attended", "Cancelled"])
            notes = st.text_area("Purpose / preparation / outcomes")
            if st.form_submit_button("Add event"):
                db.add(
                    Event(
                        name=required(name, "Name"),
                        event_date=day,
                        location=location,
                        status=status,
                        notes=notes,
                    )
                )
                db.commit()
                st.rerun()
    elif page == "Follow-ups":
        a, b, c = st.columns(3)
        timing = a.selectbox(
            "Timing",
            ["All open", "Overdue", "Due today", "Upcoming", "Unscheduled", "Completed", "Cancelled"],
        )
        channel = b.selectbox("Filter channel", [None, *CHANNELS], format_func=lambda x: x or "All")
        owner = c.selectbox(
            "Filter owner", [None, *sorted({t.owner for t in all_tasks})], format_func=lambda x: x or "All"
        )
        filtered = [
            t
            for t in all_tasks
            if (t.status == "Open" if timing == "All open" else task_bucket(t) == timing)
            and (not channel or t.channel == channel)
            and (not owner or t.owner == owner)
        ]
        show_table([task_row(t) for t in filtered])
        selected = choose("Manage task", options(filtered, lambda t: f"{t.title} · {t.owner}"))
        if selected:
            task = db.get(Task, selected)
            version_key = f"expected_task_{selected}"
            if version_key not in st.session_state:
                st.session_state[version_key] = task.version
            with st.form(f"manage_{selected}"):
                status = select_existing("Task status", ["Open", "Completed", "Cancelled"], task.status)
                reschedule = st.checkbox("Reschedule / snooze")
                due = st.date_input("New due date", task.due_date or today())
                if st.form_submit_button("Update task"):
                    update_task(
                        db,
                        task.id,
                        st.session_state[version_key],
                        status=status,
                        reschedule=reschedule,
                        due_date=due,
                    )
                    db.commit()
                    st.session_state.pop(version_key, None)
                    st.rerun()
        with st.expander("Add follow-up", expanded=not all_tasks), st.form("task"):
            title = st.text_input("Action")
            contact = choose("Related contact", contact_labels)
            opp = choose("Related opportunity", opp_labels)
            channel = st.selectbox("Responsible channel", CHANNELS)
            owner = st.text_input("Task owner", "JJ")
            priority = st.selectbox("Priority", ["High", "Medium", "Low"], index=1)
            due = st.date_input("Due date (optional)", value=None)
            if st.form_submit_button("Create follow-up"):
                db.add(
                    Task(
                        title=required(title, "Action"),
                        contact_id=contact,
                        opportunity_id=opp,
                        channel=channel,
                        owner=required(owner, "Owner"),
                        priority=priority,
                        due_date=due,
                    )
                )
                db.commit()
                st.rerun()
    elif page == "Reminder inbox":
        generate(db)
        db.flush()
        reminders = active_reminders(db)
        st.caption("Overdue, due today, and due within two days. Reminders regenerate daily in Eastern time.")
        if not reminders:
            st.info("No unacknowledged reminders. Unscheduled tasks remain in Follow-ups.")
        for reminder in reminders:
            task = reminder.task
            with st.container(border=True):
                st.write(f"**{task.title}**")
                chips([task_bucket(task), task.priority, task.channel])
                st.caption(f"Due {task.due_date} · Owner: {task.owner}")
                if task.contact:
                    st.write(task.contact.name)
                a, b = st.columns(2)
                if a.button("Acknowledge for today", key=f"ack_{reminder.id}"):
                    reminder.acknowledged_at = utcnow()
                    db.commit()
                    st.rerun()
                if b.button("Complete follow-up", key=f"done_{reminder.id}"):
                    update_task(db, task.id, task.version, status="Completed")
                    db.commit()
                    st.rerun()
        st.caption("Acknowledging a reminder does not complete the task. No emails or messages are sent.")
    elif page == "Import & export":
        st.write(
            "Upload the existing UR-Company-Memory/CRM CSV files. Import preserves original IDs and fields; repeated IDs are skipped."
        )
        st.info(
            "Until cutover is agreed, the company-memory CSVs remain the shared record used by UR channels. This app does not sync them automatically."
        )
        files = st.file_uploader("CRM CSVs", type="csv", accept_multiple_files=True)
        if st.button("Import selected files", disabled=not files):
            inputs = {f.name.removesuffix(".csv"): f.getvalue().decode("utf-8-sig") for f in files}
            from crm.import_export import MODELS

            unknown = set(inputs) - set(MODELS)
            if unknown:
                raise ValidationError(f"Unsupported files: {', '.join(sorted(unknown))}")
            if len(inputs) != len(files):
                raise ValidationError("Upload each filename only once.")
            result = import_csvs(db, inputs)
            db.commit()
            st.success(f"Imported {result['imported']}; skipped {result['skipped']}.")
            if result["review"]:
                st.warning("Some records need identity or relationship review.")
                st.download_button(
                    "Download review report", json.dumps(result, indent=2), "import-review.json"
                )
        st.download_button(
            "Export full CRM (JSON)", export_json(db), "unseen-robotics-crm.json", "application/json"
        )
        st.caption("Use PostgreSQL backups for database recovery. JSON export is a portable reference copy.")


try:
    with session() as db:
        run(db)
except ValidationError as exc:
    st.error(str(exc))
except (IntegrityError, StaleDataError):
    st.error("This record conflicts with another change. Refresh and review before saving again.")
except (SQLAlchemyError, RuntimeError):
    st.error("Database unavailable or not configured. Check the connection and run the database migrations.")

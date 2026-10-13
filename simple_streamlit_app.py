"""Single-file CRM prototype: Streamlit + standard library, no external services."""

import json
from datetime import date, datetime, timedelta
from uuid import uuid4
from zoneinfo import ZoneInfo

import streamlit as st

st.set_page_config(page_title="Unseen Robotics CRM", page_icon="🧭", layout="wide")
CHANNELS = [
    "UR Partners",
    "UR Private BD",
    "UR Federal BD",
    "UR State BD",
    "UR Events",
    "Market Research Leads",
    "OSU Partnership Outreach",
    "UR HR",
    "UR IT",
    "Other",
]
for collection in ["contacts", "interactions", "tasks"]:
    st.session_state.setdefault(collection, [])
contacts = st.session_state.contacts
interactions = st.session_state.interactions
tasks = st.session_state.tasks
now = datetime.now(ZoneInfo("America/New_York")).date()


def bucket(task):
    if task["status"] != "Open":
        return task["status"]
    if not task["due"]:
        return "Needs a date"
    due = date.fromisoformat(task["due"])
    return "Overdue" if due < now else "Due today" if due == now else "Upcoming"


def labels():
    return {c["id"]: f"{c['name']} · {c['organization']}" for c in contacts}


def show(rows):
    if rows:
        st.dataframe(rows, hide_index=True, use_container_width=True)
    else:
        st.info("No matching records yet.")


st.title("Unseen Robotics CRM")
st.caption("Contacts · Conversations · Next actions")
st.warning(
    "Prototype: records last only for this session. Download a backup before closing or reloading; restore it with Import."
)
a, b, c = st.columns(3)
a.metric("Contacts", len(contacts))
b.metric("Overdue", sum(bucket(t) == "Overdue" for t in tasks))
c.metric("Due today", sum(bucket(t) == "Due today" for t in tasks))
contact_tab, conversation_tab, followup_tab, backup_tab = st.tabs(
    ["Contacts", "Conversations", "Follow-ups", "Backup & restore"]
)

with contact_tab:
    a, b, c = st.columns(3)
    search = a.text_input("Search contacts")
    capture = b.selectbox("Captured by", ["All", *CHANNELS])
    usage = c.selectbox("Used by", ["All", *CHANNELS])
    visible = [
        v
        for v in contacts
        if search.casefold() in (v["name"] + " " + v["organization"] + " " + v["email"]).casefold()
        and (capture == "All" or v["captured_by"] == capture)
        and (usage == "All" or usage in v["used_by"])
    ]
    show(
        [
            {
                "Name": v["name"],
                "Organization": v["organization"],
                "Email": v["email"],
                "Type": v["kind"],
                "Captured by": v["captured_by"],
                "Used by": ", ".join(v["used_by"]),
                "Owner": v["owner"],
                "Notes": v["notes"],
            }
            for v in visible
        ]
    )
    mapping = labels()
    chosen = st.selectbox(
        "Edit contact (None to add)",
        [None, *mapping],
        format_func=lambda x: mapping.get(x, "Add new contact"),
    )
    existing = next((v for v in contacts if v["id"] == chosen), {})
    with st.form(f"contact_{chosen}"):
        a, b = st.columns(2)
        name = a.text_input("Name", existing.get("name", ""))
        organization = b.text_input("Organization", existing.get("organization", ""))
        email = a.text_input("Professional email", existing.get("email", ""))
        owner = b.text_input("Owner", existing.get("owner", "JJ"))
        kinds = ["Vendor", "Funder", "Customer", "Government", "University", "Partner", "Advisor", "Other"]
        kind = a.selectbox("Relationship type", kinds, index=kinds.index(existing.get("kind", "Other")))
        captured = b.selectbox(
            "Captured by channel", CHANNELS, index=CHANNELS.index(existing.get("captured_by", "Other"))
        )
        used = st.multiselect("Used by channels", CHANNELS, default=existing.get("used_by", []))
        notes = st.text_area("Context / interests / introductions", existing.get("notes", ""))
        if st.form_submit_button("Save contact"):
            normalized_email = email.strip().lower()
            duplicate = any(
                v["id"] != chosen
                and (
                    (normalized_email and v["email"] == normalized_email)
                    or (
                        v["name"].casefold() == name.strip().casefold()
                        and v["organization"].casefold() == organization.strip().casefold()
                    )
                )
                for v in contacts
            )
            if not name.strip() or not owner.strip():
                st.error("Name and owner are required.")
            elif duplicate:
                st.error("A matching contact exists. Select it above to edit.")
            else:
                record = {
                    "id": chosen or str(uuid4()),
                    "name": name.strip(),
                    "organization": organization.strip(),
                    "email": normalized_email,
                    "owner": owner.strip(),
                    "kind": kind,
                    "captured_by": captured,
                    "used_by": used,
                    "notes": notes,
                }
                if chosen:
                    contacts[contacts.index(existing)] = record
                else:
                    contacts.append(record)
                st.rerun()

with conversation_tab:
    mapping = labels()
    show(
        [
            {
                "Date": v["date"],
                "Contact": mapping.get(v["contact_id"], ""),
                "Channel": v["channel"],
                "Summary": v["summary"],
                "Next action": v["next_action"],
            }
            for v in reversed(interactions)
        ]
    )
    if not contacts:
        st.info("Add a contact first, then log a conversation.")
    else:
        with st.form("conversation"):
            target = st.selectbox("Contact", list(mapping), format_func=mapping.get)
            channel = st.selectbox("Conversation channel", CHANNELS)
            day = st.date_input("Conversation date", now)
            summary = st.text_area("What happened / customer feedback / commitments")
            next_action = st.text_input("Next action")
            create_task = st.checkbox("Create a follow-up")
            due = st.date_input("Follow-up due", now + timedelta(days=3))
            if st.form_submit_button("Log conversation"):
                if not summary.strip() or (create_task and not next_action.strip()):
                    st.error("Enter a summary and, if scheduling a follow-up, a next action.")
                else:
                    interactions.append(
                        {
                            "id": str(uuid4()),
                            "contact_id": target,
                            "channel": channel,
                            "date": day.isoformat(),
                            "summary": summary,
                            "next_action": next_action,
                        }
                    )
                    if create_task:
                        contact = next(v for v in contacts if v["id"] == target)
                        tasks.append(
                            {
                                "id": str(uuid4()),
                                "contact_id": target,
                                "channel": channel,
                                "owner": contact["owner"],
                                "action": next_action,
                                "due": due.isoformat(),
                                "priority": "Medium",
                                "status": "Open",
                            }
                        )
                    st.rerun()

with followup_tab:
    mapping = labels()
    a, b = st.columns(2)
    timing = a.selectbox(
        "Show", ["All open", "Overdue", "Due today", "Upcoming", "Needs a date", "Completed"]
    )
    channel = b.selectbox("Responsible channel", ["All", *CHANNELS])
    visible = [
        t
        for t in tasks
        if (t["status"] == "Open" if timing == "All open" else bucket(t) == timing)
        and (channel == "All" or channel == t["channel"])
    ]
    for task in sorted(visible, key=lambda v: v["due"] or "9999-12-31"):
        with st.container(border=True):
            st.write(f"**{task['action']}**")
            st.caption(
                f"{mapping.get(task['contact_id'], 'General task')} · {task['owner']} · {task['channel']}"
            )
            st.write(f"{bucket(task)} · Due {task['due'] or 'not set'} · {task['priority']} priority")
            if task.get("original_status"):
                st.caption("Recorded status: " + task["original_status"])
            if task["status"] == "Open":
                a, b = st.columns(2)
                if a.button("Complete", key="done_" + task["id"]):
                    task["status"] = "Completed"
                    st.rerun()
                if b.button("Snooze 3 days", key="snooze_" + task["id"]):
                    task["due"] = (now + timedelta(days=3)).isoformat()
                    st.rerun()
    if not visible:
        st.info("No follow-ups in this view.")
    with st.expander("Add follow-up"), st.form("followup"):
        action = st.text_input("Action")
        target = st.selectbox(
            "Related contact", [None, *mapping], format_func=lambda x: mapping.get(x, "General task")
        )
        owner = st.text_input("Task owner", "JJ")
        channel = st.selectbox("Task channel", CHANNELS)
        due = st.date_input("Due date", now)
        priority = st.selectbox("Priority", ["High", "Medium", "Low"], index=1)
        if st.form_submit_button("Add follow-up"):
            if not action.strip() or not owner.strip():
                st.error("Action and owner are required.")
            else:
                tasks.append(
                    {
                        "id": str(uuid4()),
                        "contact_id": target,
                        "owner": owner,
                        "channel": channel,
                        "action": action,
                        "due": due.isoformat(),
                        "priority": priority,
                        "status": "Open",
                    }
                )
                st.rerun()


def prepare_history(history):
    if history.get("format") != "ur-chat-crm-v1":
        raise ValueError("Choose the supplied chat-history import file.")
    people = history["contacts"]
    ids = {c["id"] for c in people}
    if len(ids) != len(people):
        raise ValueError("Duplicate contact IDs.")
    for c in people:
        for field in ["id", "name", "organization", "email", "kind", "captured_by", "notes"]:
            if not isinstance(c[field], str):
                raise ValueError("Invalid contact field.")
        if c["kind"] not in [
            "Vendor",
            "Funder",
            "Customer",
            "Government",
            "University",
            "Partner",
            "Advisor",
            "Other",
        ]:
            raise ValueError("Invalid contact category.")
        if (
            c["captured_by"] not in CHANNELS
            or not isinstance(c["used_by"], list)
            or any(v not in CHANNELS for v in c["used_by"])
        ):
            raise ValueError("Invalid channel.")
    notes = []
    for source in history["conversations"]:
        if source["contact_id"] is not None and source["contact_id"] not in ids:
            raise ValueError("Missing linked contact.")
        date.fromisoformat(source["date"])
        notes.append({**source, "next_action": source.get("next_action", "")})
    actions = []
    for source in history["followups"]:
        if source["contact_id"] is not None and source["contact_id"] not in ids:
            raise ValueError("Missing linked contact.")
        if source["due"]:
            date.fromisoformat(source["due"])
        actions.append(
            {
                **source,
                "title": source["action"],
                "due": source["due"] or "",
                "original_status": source["status"],
                "status": "Completed" if source["completed"] else "Open",
            }
        )
    return {"contacts": people, "interactions": notes, "tasks": actions}


with backup_tab:
    snapshot = {
        "format": "ur-simple-crm-v1",
        "source_metadata": st.session_state.get("crm_source_metadata", {}),
        "contacts": contacts,
        "interactions": interactions,
        "tasks": tasks,
    }
    st.download_button(
        "Download CRM backup", json.dumps(snapshot, indent=2), "ur-crm-backup.json", "application/json"
    )
    upload = st.file_uploader("Import a CRM backup", type="json")
    confirm = st.checkbox("Replace this session's records with the backup")
    if st.button("Restore backup", disabled=not upload or not confirm):
        try:
            incoming = json.loads(upload.getvalue())
            if incoming.get("format") != "ur-simple-crm-v1":
                raise ValueError("Use a backup from this simple CRM.")
            required_fields = {
                "contacts": {
                    "id",
                    "name",
                    "organization",
                    "email",
                    "kind",
                    "owner",
                    "captured_by",
                    "used_by",
                    "notes",
                },
                "interactions": {"id", "contact_id", "channel", "date", "summary", "next_action"},
                "tasks": {"id", "contact_id", "channel", "owner", "action", "due", "priority", "status"},
            }
            for collection, fields in required_fields.items():
                rows = incoming.get(collection)
                if not isinstance(rows, list) or any(
                    not isinstance(v, dict) or not fields <= v.keys() for v in rows
                ):
                    raise ValueError("Backup records are incomplete.")
                for record in rows:
                    for field in fields - {"used_by", "contact_id"}:
                        if not isinstance(record[field], str):
                            raise ValueError("Invalid field type.")
                    if (
                        "contact_id" in record
                        and record["contact_id"] is not None
                        and not isinstance(record["contact_id"], str)
                    ):
                        raise ValueError("Invalid contact reference.")
                if len({v["id"] for v in rows}) != len(rows):
                    raise ValueError("Backup has duplicate record IDs.")
            for record in incoming["contacts"]:
                if (
                    record["kind"] not in kinds
                    or record["captured_by"] not in CHANNELS
                    or not isinstance(record["used_by"], list)
                ):
                    raise ValueError("Invalid contact categories.")
                if any(v not in CHANNELS for v in record["used_by"]):
                    raise ValueError("Unknown usage channel.")
            ids = {v["id"] for v in incoming["contacts"]}
            for record in incoming["interactions"] + incoming["tasks"]:
                if record["contact_id"] is not None and record["contact_id"] not in ids:
                    raise ValueError("A linked contact is missing.")
                if record["channel"] not in CHANNELS:
                    raise ValueError("Unknown channel.")
            for record in incoming["interactions"]:
                date.fromisoformat(record["date"])
            for record in incoming["tasks"]:
                if record["status"] not in ["Open", "Completed"] or record["priority"] not in [
                    "High",
                    "Medium",
                    "Low",
                ]:
                    raise ValueError("Invalid follow-up status or priority.")
                if record["due"]:
                    date.fromisoformat(record["due"])
            for collection in required_fields:
                st.session_state[collection] = incoming[collection]
            st.session_state["crm_source_metadata"] = incoming.get("source_metadata", {})
            st.rerun()
        except (ValueError, TypeError, KeyError, AttributeError):
            st.error("Invalid backup. Import a JSON backup downloaded from this app.")
    st.caption(
        "Reminders are shown while the app is open. This prototype does not send email or background notifications."
    )

    st.subheader("Populate from UR chat history")
    history_upload = st.file_uploader("CRM chat-history JSON", type="json", key="chat_history_file")
    if st.button("Import chat history", disabled=history_upload is None):
        try:
            history = json.loads(history_upload.getvalue())
            incoming = prepare_history(history)
            # Keep existing records and remap links when the same name/org is already present.
            mapping = {}
            for record in incoming["contacts"]:
                matches = [
                    c
                    for c in contacts
                    if c["id"] == record["id"]
                    or (
                        c["name"].casefold() == record["name"].casefold()
                        and c["organization"].casefold() == record["organization"].casefold()
                    )
                ]
                if len(matches) == 1:
                    mapping[record["id"]] = matches[0]["id"]
                else:
                    mapping[record["id"]] = record["id"]
                    contacts.append(record)
            for collection in ["interactions", "tasks"]:
                existing_ids = {r["id"] for r in st.session_state[collection]}
                for record in incoming[collection]:
                    record["contact_id"] = mapping.get(record["contact_id"], record["contact_id"])
                    if record["id"] not in existing_ids:
                        st.session_state[collection].append(record)
                        existing_ids.add(record["id"])
            st.session_state["crm_source_metadata"] = {
                k: v for k, v in history.items() if k not in ["contacts", "conversations", "followups"]
            }
            st.session_state["history_imported"] = True
            st.rerun()
        except (ValueError, TypeError, KeyError, AttributeError):
            st.error("Invalid history file. Use the supplied UR CRM chat-history JSON.")
    if st.session_state.get("history_imported"):
        st.success("Chat history imported. Open Contacts, Conversations, and Follow-ups.")
        metadata = st.session_state.get("crm_source_metadata", {})
        st.caption(metadata.get("coverage", ""))
        with st.expander("Organizations, suppliers, opportunities, events and review notes"):
            for key in ["opportunities", "events", "organizations", "suppliers", "review"]:
                st.subheader(key.capitalize())
                st.json(metadata.get(key, []), expanded=False)

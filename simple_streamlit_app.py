"""Single-file CRM prototype: Streamlit + standard library, no external services."""

import json
import hashlib
import hmac
from datetime import date, datetime, timedelta
from uuid import uuid4
from zoneinfo import ZoneInfo

import streamlit as st

st.set_page_config(page_title="Unseen Robotics CRM", page_icon="🧭", layout="wide")
# Authenticate before initializing or rendering any CRM records.
try:
    app_password = st.secrets["APP_PASSWORD"]
except (KeyError, FileNotFoundError):
    app_password = ""
if not isinstance(app_password, str) or len(app_password) < 16:
    st.error("Configure APP_PASSWORD in app secrets with at least 16 characters.")
    st.stop()
password_version = hashlib.sha256(app_password.encode()).hexdigest()
if st.session_state.get("authenticated_password_version") != password_version:
    # Discard records if the configured password changes during a session.
    for key in ("contacts", "interactions", "tasks", "source_metadata", "authenticated_password_version"):
        st.session_state.pop(key, None)
    st.title("Unseen Robotics CRM")
    with st.form("sign_in"):
        st.text_input("Password", type="password", key="login_password")
        submitted = st.form_submit_button("Sign in")
    if submitted:
        entered = st.session_state.pop("login_password", "")
        if hmac.compare_digest(entered.encode(), app_password.encode()):
            st.session_state.authenticated_password_version = password_version
            st.rerun()
        st.error("Incorrect password.")
    st.stop()
if st.sidebar.button("Sign out"):
    for key in list(st.session_state):
        del st.session_state[key]
    st.rerun()
st.sidebar.caption("CRM access")

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
from crm.simple_store import load, save, ConflictError
try:
    database_url = st.secrets.get("DATABASE_URL", "")
except FileNotFoundError:
    database_url = ""
if database_url:
    try:
        db_version, db_payload = load(database_url)
        for collection in ["contacts", "interactions", "tasks"]:
            st.session_state[collection] = db_payload.get(collection, [])
        st.session_state["crm_source_metadata"] = db_payload.get("source_metadata", {})
    except Exception:
        st.error("Unable to connect to the CRM database. Check the database configuration.")
        st.stop()


def persist_and_rerun():
    if database_url:
        try:
            save(database_url, db_version, {
                **{key: st.session_state[key] for key in ["contacts", "interactions", "tasks"]},
                "source_metadata": st.session_state.get("crm_source_metadata", {}),
            })
        except ConflictError:
            st.error("Someone updated the CRM first. Reload and apply your change again.")
            st.stop()
        except Exception:
            st.error("Could not save to the database. Your change has not been saved.")
            st.stop()
    st.rerun()

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
if database_url:
    st.caption("Connected to PostgreSQL • changes save automatically")
    if st.button("Refresh CRM data"):
        st.rerun()
else:
    st.warning("Session-only mode: configure DATABASE_URL for permanent storage. Download a backup before closing.")
a, b, c = st.columns(3)
a.metric("Contacts", len(contacts))
b.metric("Overdue", sum(bucket(t) == "Overdue" for t in tasks))
c.metric("Due today", sum(bucket(t) == "Due today" for t in tasks))
contact_tab, conversation_tab, followup_tab, backup_tab = st.tabs(
    ["Contacts", "Conversations", "Follow-ups", "Backup & restore"]
)

with contact_tab:
    from st_aggrid import AgGrid, JsCode
    import pandas as pd

    # Imported organization records have no named individual.
    for contact in contacts:
        if contact.get("record_type") == "organization":
            contact["name"] = ""
    rows = [{"Name": v["name"], "Organization": v["organization"],
             "Relationship type": v["kind"], "id": v["id"]} for v in contacts]
    grid = AgGrid(
        pd.DataFrame(rows, columns=["Name", "Organization", "Relationship type", "id"]),
        gridOptions={
            "columnDefs": [
                {"field": field, "filter": "agTextColumnFilter", "floatingFilter": True,
                 "filterParams": {"debounceMs": 100}}
                for field in ["Name", "Organization", "Relationship type"]
            ] + [{"field": "id", "hide": True}],
            "defaultColDef": {"sortable": True, "resizable": True, "flex": 1},
            "onRowDoubleClicked": JsCode("function(event) { event.node.setSelected(true, true); }"),
            "rowSelection": {"mode": "singleRow", "enableClickSelection": False,
                             "checkboxes": False},
        },
        update_on=["selectionChanged", "rowDoubleClicked"], key="contact_grid", height=350,
        allow_unsafe_jscode=True,
        enable_enterprise_modules=False,
    )
    st.caption("Double-click a contact row to read its details below.")
    selected = grid.selected_rows
    chosen = selected.iloc[0]["id"] if selected is not None and len(selected) else None
    if st.button("Add new contact", key="new_contact"):
        chosen = None
    existing = next((v for v in contacts if v["id"] == chosen), {})
    st.subheader("Contact details" if existing else "Add a contact")
    if existing:
        st.write(existing.get("notes") or "No relationship notes recorded.")
        history = sorted([v for v in interactions if v["contact_id"] == chosen],
                         key=lambda v: v["date"], reverse=True)
        for entry in history[:3]:
            st.write(f"**{entry['date']}** · {entry['summary']}")
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
            if not (name.strip() or organization.strip()) or not owner.strip():
                st.error("Enter a name or organization, and an owner.")
            elif duplicate:
                st.error("A matching contact exists. Select it above to edit.")
            else:
                record = {
                    **existing,
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
                persist_and_rerun()

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
                    persist_and_rerun()

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
    if visible:
        a, b, c, d = st.columns([2, 2, 1.5, 4])
        for column, heading in zip([a, b, c, d], ["Name", "Company", "Contact type", "Next follow-up"]):
            column.markdown(f"**{heading}**")
    for task in sorted(visible, key=lambda v: v["due"] or "9999-12-31"):
        with st.container(border=True):
            contact = next((v for v in contacts if v["id"] == task["contact_id"]), {})
            words = (task.get("short_summary") or task["action"]).split()
            if len(words) < 5:
                words = ("Complete the next action: " + " ".join(words)).split()
            summary = " ".join(words[:15]) + ("…" if len(words) > 15 else "")
            a, b, c, d = st.columns([2, 2, 1.5, 4])
            a.write(contact.get("name", "") if contact.get("record_type") != "organization" else "")
            b.write(contact.get("organization", ""))
            c.write(contact.get("kind", "General task"))
            d.write(summary)
            with st.expander("Details", expanded=False):
                st.write("**Full next action:** " + task["action"])
                st.caption(f"Owner: {task['owner']} · Channel: {task['channel']}")
                st.write(f"{bucket(task)} · Due {task['due'] or 'not set'} · {task['priority']} priority")
                history = sorted([v for v in interactions if task["contact_id"] and v["contact_id"] == task["contact_id"]],
                                 key=lambda v: v["date"], reverse=True)
                last = history[0] if history else None
                st.write("**Who:** " + (" · ".join(filter(None, [contact.get("name"), contact.get("organization")])) or task.get("target") or "General task"))
                st.write("**Why / relationship context:** " + (task.get("reason") or contact.get("notes") or "No reason recorded; confirm the purpose before reaching out."))
                st.write("**Last contact:** " + (f"{last['date']} — {last['summary']}" if last else "No dated interaction recorded."))
                st.write("**Recommended next step:** " + (task.get("recommendation") or task["action"]))
                method = task.get("method") or ("Email" if contact.get("email") else "Confirm the preferred contact method")
                st.write("**How:** " + method)
                st.caption("Suggested approach: reference the last conversation, state the next action, and ask one clear question. Suggestions are based on recorded context; they are not confirmed commitments.")
                if task.get("original_status"):
                    st.caption("Recorded status: " + task["original_status"])
                if task["status"] == "Open":
                    a, b = st.columns(2)
                    if a.button("Complete", key="done_" + task["id"]):
                        task["status"] = "Completed"
                        persist_and_rerun()
                    if b.button("Snooze 3 days", key="snooze_" + task["id"]):
                        task["due"] = (now + timedelta(days=3)).isoformat()
                        persist_and_rerun()
    if not visible:
        st.info("No follow-ups in this view.")
    with st.expander("Add follow-up"), st.form("followup"):
        action = st.text_input("Action")
        reason = st.text_area("Why follow up / context")
        recommendation = st.text_area("Recommended next step")
        method = st.selectbox("Follow-up method", ["Email", "Phone", "Meeting", "LinkedIn", "Other"])
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
                        "reason": reason,
                        "recommendation": recommendation,
                        "method": method,
                        "due": due.isoformat(),
                        "priority": priority,
                        "status": "Open",
                    }
                )
                persist_and_rerun()


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
            persist_and_rerun()
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
            persist_and_rerun()
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

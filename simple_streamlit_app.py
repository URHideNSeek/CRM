"""Single-file CRM prototype: Streamlit + standard library, no external services."""

import json
from contextlib import nullcontext
import hashlib
import hmac
from datetime import date, datetime, timedelta
from uuid import uuid4
from zoneinfo import ZoneInfo

import streamlit as st
from crm.digital_twin import ensure_twins, build_twin, change_triggers, public_url

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
    ensure_twins(st.session_state.contacts, st.session_state.interactions, st.session_state.tasks)
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
    st.session_state["save_notice"] = "Saved to CRM." if database_url else "Saved for this session."
    st.rerun()

for collection in ["contacts", "interactions", "tasks"]:
    st.session_state.setdefault(collection, [])
contacts = st.session_state.contacts
interactions = st.session_state.interactions
tasks = st.session_state.tasks
ensure_twins(contacts, interactions, tasks)
now = datetime.now(ZoneInfo("America/New_York")).date()


def bucket(task):
    if task["status"] != "Open":
        return task["status"]
    if not task["due"]:
        return "Needs a date"
    due = date.fromisoformat(task["due"])
    return "Overdue" if due < now else "Due today" if due == now else "Upcoming"


def labels():
    return {c["id"]: " · ".join(filter(None, [c.get("name"), c.get("organization")])) or c["id"] for c in contacts}


def show(rows):
    if rows:
        st.dataframe(rows, hide_index=True, use_container_width=True)
    else:
        st.info("No matching records yet.")


st.title("Unseen Robotics CRM")
st.caption("Your relationships and next actions")
if st.session_state.get("save_notice"):
    st.success(st.session_state.pop("save_notice"))
if database_url:
    st.sidebar.caption("Connected · changes save when submitted")
    if st.sidebar.button("Refresh CRM data"):
        st.rerun()
else:
    st.warning("Session-only mode: configure DATABASE_URL for permanent storage. Download a backup before closing.")
kinds = ["Vendor", "Funder", "Customer", "Government", "University", "Partner", "Advisor", "Other"]
page = st.sidebar.radio("Workspace", ["Follow-ups", "Contacts", "Conversations", "Backup & restore"])
contact_tab = nullcontext() if page == "Contacts" else None
conversation_tab = nullcontext() if page == "Conversations" else None
followup_tab = nullcontext() if page == "Follow-ups" else None
backup_tab = nullcontext() if page == "Backup & restore" else None

if contact_tab is not None:
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
                "rowSelection": {"mode": "singleRow", "enableClickSelection": True,
                                 "checkboxes": False},
            },
            update_on=["selectionChanged", "rowDoubleClicked"], key="contact_grid", height=350,
            allow_unsafe_jscode=True,
            enable_enterprise_modules=False,
        )
        st.caption("Click a contact row to open its details, or choose it below.")
        selected = grid.selected_rows
        chosen = selected.iloc[0]["id"] if selected is not None and len(selected) else None
        chosen = st.selectbox("Open contact", [None, *labels()], index=([None, *labels()].index(chosen) if chosen else 0), format_func=lambda cid: labels().get(cid, "Add a new contact"), key="contact_picker")
        if st.button("Add new contact", key="new_contact", on_click=lambda: st.session_state.update(contact_picker=None)):
            chosen = None
        existing = next((v for v in contacts if v["id"] == chosen), {})
        st.subheader("Contact details" if existing else "Add a contact")
        if existing:
            st.write(existing.get("latest_business_summary") or existing.get("background_summary") or "No relationship summary recorded.")
            with st.expander("Full notes and source history"):
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
            kind = a.selectbox("Relationship type", kinds, index=kinds.index(existing.get("kind", "Other")) if existing.get("kind", "Other") in kinds else kinds.index("Other"))
            contact_channels = list(dict.fromkeys([*CHANNELS, existing.get("captured_by", "Other"), *existing.get("used_by", [])]))
            captured = b.selectbox(
                "Captured by channel", contact_channels, index=contact_channels.index(existing.get("captured_by", "Other"))
            )
            used = st.multiselect("Used by channels", contact_channels, default=existing.get("used_by", []))
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
if conversation_tab is not None:
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
if followup_tab is not None:
    with followup_tab:
        st.subheader("Follow-ups")
        a, b, c = st.columns(3)
        a.metric("Overdue", sum(bucket(t) == "Overdue" for t in tasks))
        b.metric("Due today", sum(bucket(t) == "Due today" for t in tasks))
        c.metric("Open tasks", sum(t.get("status") == "Open" for t in tasks))
        st.caption("Start with due tasks. Search by person, company or next action; review public changes below.")
        mapping = labels()
        a, b = st.columns(2)
        timing = a.selectbox(
            "Show", ["Needs attention", "All open", "Overdue", "Due today", "Upcoming", "Needs a date", "Completed"]
        )
        channel = b.selectbox("Responsible channel", ["All", *sorted(set(CHANNELS) | {t.get("channel", "Other") for t in tasks})])
        visible = [
            t
            for t in tasks
            if (bucket(t) in ["Overdue", "Due today"] if timing == "Needs attention" else t["status"] == "Open" if timing == "All open" else bucket(t) == timing)
            and (channel == "All" or channel == t["channel"])
        ]
        query = st.text_input("Search follow-ups", placeholder="Person, company or next action", key="task_search").strip().casefold()
        by_id = {c["id"]: c for c in contacts}
        visible = [t for t in visible if not query or query in " ".join([t.get("action", ""), mapping.get(t.get("contact_id"), ""), t.get("owner", "")]).casefold()]
        visible.sort(key=lambda t: (t.get("due") or "9999-12-31", {"High": 0, "Medium": 1, "Low": 2}.get(t.get("priority"), 1)))
        st.caption(f"{len(visible)} matching follow-ups · select a task below to act")
        if visible:
            st.dataframe([{
                "Who": by_id.get(t.get("contact_id"), {}).get("name") or by_id.get(t.get("contact_id"), {}).get("organization") or "General task",
                "Company": by_id.get(t.get("contact_id"), {}).get("organization", ""),
                "When": t.get("due") or "Needs a date",
                "Status": bucket(t),
                "What to follow up about": t.get("short_summary") or t["action"],
                "Priority": t.get("priority", "Medium"),
            } for t in visible], hide_index=True, use_container_width=True, height=350)
            selected_task = st.selectbox("Task to review", [t["id"] for t in visible], format_func=lambda tid: next((f"{mapping.get(t.get('contact_id'), 'General task')} · {t['action'][:90]}" for t in visible if t["id"] == tid), tid), key="selected_followup")
            task = next(t for t in visible if t["id"] == selected_task)
            contact = by_id.get(task.get("contact_id"), {})
            twin = contact.get("professional_twin", {})
            with st.container(border=True):
                st.write("**Full next action:** " + task["action"])
                st.caption(f"Owner: {task['owner']} · Channel: {task['channel']}")
                st.write(f"{bucket(task)} · Due {task['due'] or 'not set'} · {task['priority']} priority")
                history = sorted([v for v in interactions if task["contact_id"] and v["contact_id"] == task["contact_id"]],
                                 key=lambda v: v["date"], reverse=True)
                last = history[0] if history else None
                st.write("**Who:** " + (" · ".join(filter(None, [contact.get("name"), contact.get("organization")])) or task.get("target") or "General task"))
                st.write("**Why / relationship context:** " + (task.get("reason") or contact.get("latest_business_summary") or contact.get("background_summary") or "No reason recorded; confirm the purpose before reaching out."))
                st.write("**Last contact:** " + (f"{last['date']} — {last['summary']}" if last else "No dated interaction recorded."))
                st.write("**Recommended next step:** " + (task.get("recommendation") or task["action"]))
                method = task.get("method") or ("Email" if contact.get("email") else "Confirm the preferred contact method")
                st.write("**How:** " + method)
                st.caption("Suggested approach: reference the last conversation, state the next action, and ask one clear question. Suggestions are based on recorded context; they are not confirmed commitments.")
                with st.expander("Professional context and monitoring"):
                    st.write("**Professional model:** " + twin.get("role_template", "Unclassified"))
                    st.caption(twin.get("assignment_basis", "") + "; title does not establish decision authority.")
                    st.write("**Information likely to help:** " + "; ".join(twin.get("template_information_needs", [])))
                    st.write("**Company / parent watch:** " + contact.get("organization", "") + " / " + (twin.get("parent_organization", {}).get("name") or "Parent not yet verified"))
                    st.caption(twin.get("timing_basis", ""))
                if task.get("original_status"):
                    st.caption("Recorded status: " + task["original_status"])
                if task["status"] == "Open":
                    a, b = st.columns(2)
                    if a.button("Mark complete", type="primary", key="done_" + task["id"]):
                        task["status"] = "Completed"
                        persist_and_rerun()
                    if b.button("Snooze 3 days", key="snooze_" + task["id"]):
                        task["due"] = (now + timedelta(days=3)).isoformat()
                        persist_and_rerun()
                    with st.form("reschedule_" + task["id"]):
                        updated_due = st.date_input("Set follow-up date", date.fromisoformat(task["due"]) if task.get("due") else now)
                        if st.form_submit_button("Save date"):
                            task["due"] = updated_due.isoformat()
                            persist_and_rerun()
        if not visible:
            st.info("No follow-ups match these filters. Choose All open or clear your search to see other tasks.")
        st.subheader("Communication triggers from verified changes")
        queued = {}
        for person in contacts:
            if person.get("record_type") == "organization":
                continue
            for trigger in change_triggers(person, contacts, now):
                item = queued.setdefault(trigger["id"], {"trigger": trigger, "people": []})
                item["people"].append(person)
        if not queued:
            st.caption("No open verified change triggers. New verified changes will appear here for review.")
        for event_id, item in queued.items():
            trigger = item["trigger"]
            with st.container(border=True):
                st.write("**When:** " + trigger["when"])
                st.write("**What:** " + trigger["what"])
                st.write("**Why this may help:** " + trigger["why"])
                st.write("**Suggested follow-up:** " + trigger["suggestion"])
                st.write("**Relevant contacts:** " + ", ".join(p.get("name", "") for p in item["people"]))
                st.link_button("Public source", trigger["source_url"])
                st.caption(trigger["basis"])
                target = st.selectbox("Choose recipient", [p["id"] for p in item["people"]], format_func=lambda cid: mapping.get(cid, cid), key="trigger_target_" + event_id)
                if st.button("Create follow-up for this trigger", key="trigger_task_" + event_id):
                    stable_id = "T-CHANGE-" + event_id + "-" + target
                    if not any(t["id"] == stable_id for t in tasks):
                        tasks.append({"id": stable_id, "contact_id": target, "channel": "UR Private BD", "owner": "JJ", "action": trigger["suggestion"], "reason": trigger["why"], "due": now.isoformat(), "priority": "Medium", "status": "Open", "change_event_id": event_id, "source_url": trigger["source_url"]})
                    persist_and_rerun()
                if st.button("Dismiss trigger", key="trigger_dismiss_" + event_id):
                    for record in contacts:
                        for event in record.get("monitored_changes", []):
                            if event.get("id") == event_id:
                                event["status"] = "Dismissed"
                    persist_and_rerun()
        with st.expander("Professional twins and monitoring coverage"):
            people = [c for c in contacts if c.get("record_type") != "organization"]
            st.write(f"{len(people)} person models; templates are tailored when evidence changes.")
            st.dataframe([{"Person": c.get("name"), "Company": c.get("organization"), "Template": c["professional_twin"]["role_template"], "Basis": c["professional_twin"]["assignment_basis"], "Parent": c["professional_twin"]["parent_organization"].get("name", "Discovery pending"), "Last public check": c.get("monitoring_last_checked", "Not yet scanned")} for c in people], hide_index=True, use_container_width=True)
            selected = st.selectbox("Inspect professional twin", [c["id"] for c in people], format_func=lambda cid: mapping.get(cid, cid)) if people else None
            if selected:
                st.json(next(c["professional_twin"] for c in people if c["id"] == selected))
        with st.expander("Record a verified public change"), st.form("record_public_change"):
            change_target = st.selectbox("Person or organization changed", [c["id"] for c in contacts], format_func=lambda cid: mapping.get(cid, cid)) if contacts else None
            change_scope = st.selectbox("Change relates to", ["person", "company", "parent"])
            change_kind = st.selectbox("Change type", ["role_change", "leadership_change", "acquisition", "new_program", "funding", "contract_award", "product_update", "other"])
            change_summary = st.text_area("Public business change summary")
            change_reason = st.text_area("Why this could make a communication useful")
            change_action = st.text_area("Suggested communication")
            change_url = st.text_input("Public source URL")
            change_date = st.date_input("Change publication date", now)
            change_verified = st.checkbox("I verified this business fact against the public source")
            new_title = st.text_input("New professional title (only for a verified person role change)")
            if st.form_submit_button("Record public change"):
                if not change_target or not change_verified or not public_url(change_url) or not change_summary.strip() or not change_reason.strip() or change_date > now:
                    st.error("Select an entity, verify the source, and provide a dated business summary, relevance and public URL.")
                else:
                    record = next(c for c in contacts if c["id"] == change_target)
                    key = hashlib.sha256((change_target + change_url + change_kind + change_summary).encode()).hexdigest()[:20]
                    if not any(e["id"] == key for e in record.get("monitored_changes", [])):
                        record.setdefault("monitored_changes", []).append({"id": key, "entity_type": change_scope, "kind": change_kind, "summary": change_summary.strip(), "communication_relevance": change_reason.strip(), "suggested_followup": change_action.strip(), "source_url": change_url, "date": change_date.isoformat(), "verified": True, "status": "Open", "verification_basis": "Operator-confirmed public source"})
                    if change_kind == "role_change" and change_scope == "person" and new_title.strip():
                        record["title"] = new_title.strip()
                    persist_and_rerun()
        with st.expander("Verify a company parent relationship"), st.form("verify_parent"):
            organizations = [c for c in contacts if c.get("record_type") == "organization"]
            parent_target = st.selectbox("Company", [c["id"] for c in organizations], format_func=lambda cid: mapping.get(cid, cid)) if organizations else None
            parent_name = st.text_input("Verified parent organization name")
            parent_source = st.text_input("Parent relationship source URL")
            if st.form_submit_button("Save verified parent"):
                if not parent_target or not parent_name.strip() or not public_url(parent_source):
                    st.error("Choose a company and provide the verified parent name and public source.")
                else:
                    record = next(c for c in organizations if c["id"] == parent_target)
                    record["parent_organization"] = {"name": parent_name.strip(), "source_url": parent_source, "verified_on": now.isoformat(), "basis": "Operator-confirmed public source"}
                    persist_and_rerun()
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


if backup_tab is not None:
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
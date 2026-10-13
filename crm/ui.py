"""Native Streamlit presentation components for the relationship workspace."""

from datetime import timedelta
from html import escape

import streamlit as st

from crm.service import task_bucket, today, update_task

DESCRIPTIONS = {
    "Overview": "Know who needs your attention, what you promised, and what moves forward next.",
    "Contacts": "One shared relationship record, with the channels that captured and use it.",
    "Organizations": "Connect people to the companies, agencies, and institutions behind them.",
    "Opportunities": "Track each relationship from an introduction to a concrete outcome.",
    "Customer insights": "Keep customer needs and feedback connected to product and pursuit decisions.",
    "Events": "Turn event conversations into lasting relationships and next actions.",
    "Follow-ups": "Every commitment has an owner. Give the next action a date and keep it moving.",
    "Reminder inbox": "Your daily queue of approaching deadlines and overdue commitments.",
    "Import & export": "Bring existing relationship records into your shared workspace.",
}


def style():
    st.markdown(
        """<style>
    .stApp {background:#f5f7fb;}
    [data-testid="stSidebar"] {background:#15283d;}
    [data-testid="stSidebar"] *, [data-testid="stSidebar"] label {color:#edf4fa;}
    [data-testid="stSidebar"] button {background:#243c55; border-color:#53677b;}
    [data-testid="stSidebar"] [data-testid="stCaptionContainer"] {color:#b7c8d8;}
    .block-container {padding-top:2rem; max-width:1500px;}
    [data-testid="stMetric"] {background:white; padding:1rem 1.2rem; border:1px solid #dce4ed;
      border-radius:12px; border-top:3px solid #00857c;}
    [data-testid="stForm"] {background:#fff; border-radius:12px;}
    .ur-kicker {font-size:12px; font-weight:700; letter-spacing:.13em; color:#00776f;
      text-transform:uppercase; margin-bottom:.4rem;}
    .ur-title {font-size:2.35rem; font-weight:750; color:#162b40; line-height:1.15; margin:0 0 .6rem;}
    .ur-description {color:#52677b; margin-bottom:1.5rem; max-width:850px;}
    .ur-chip {display:inline-block; padding:4px 10px; border-radius:20px; background:#e5f3f0;
      color:#006d64; font-size:12px; font-weight:600; margin:2px 5px 2px 0;}
    @media (max-width:700px) {.ur-title {font-size:1.7rem;} .block-container {padding-top:1rem;}}
    </style>""",
        unsafe_allow_html=True,
    )


def header(page):
    st.markdown(
        f'<div class="ur-kicker">Unseen Robotics · relationship workspace</div>'
        f'<h1 class="ur-title">{escape(page)}</h1>'
        f'<div class="ur-description">{escape(DESCRIPTIONS[page])}</div>',
        unsafe_allow_html=True,
    )
    st.caption(f"{today().strftime('%A, %B %d, %Y')} · Eastern time · shared company access")


def chips(labels):
    st.markdown(
        "".join(f'<span class="ur-chip">{escape(label)}</span>' for label in labels), unsafe_allow_html=True
    )


def navigate(page):
    st.session_state["workspace_page"] = page


def task_cards(db, tasks, *, prefix="overview", maximum=8):
    rank = {"High": 0, "Medium": 1, "Low": 2}
    ordered = sorted(
        tasks, key=lambda t: (t.due_date or today() + timedelta(days=36500), rank.get(t.priority, 1), t.title)
    )
    if not ordered:
        st.success("You're caught up here. Review upcoming or unscheduled actions in Follow-ups.")
        return
    for task in ordered[:maximum]:
        with st.container(border=True):
            left, right = st.columns([3, 1])
            with left:
                st.write(f"**{task.title}**")
                target = (
                    task.contact.name if task.contact else task.legacy_data.get("related_person_or_org", "")
                )
                if target:
                    st.caption(target)
                chips([task_bucket(task), task.priority, task.channel])
                st.caption(f"Owner: {task.owner} · Due: {task.due_date or 'Choose a date'}")
            with right:
                if st.button("Complete", key=f"{prefix}_done_{task.id}", width="stretch"):
                    update_task(db, task.id, task.version, status="Completed")
                    db.commit()
                    st.rerun()
                if st.button("Snooze 3 days", key=f"{prefix}_snooze_{task.id}", width="stretch"):
                    update_task(
                        db, task.id, task.version, reschedule=True, due_date=today() + timedelta(days=3)
                    )
                    db.commit()
                    st.rerun()
    if len(ordered) > maximum:
        st.caption(f"Showing {maximum} of {len(ordered)} actions. Open Follow-ups for the full queue.")


def contact_profile(item, tasks, opportunities):
    with st.container(border=True):
        st.subheader(item.name)
        st.caption(
            " · ".join(v for v in [item.title, item.organization.name if item.organization else ""] if v)
        )
        chips([item.relationship_type, item.status, item.priority])
        a, b, c = st.columns(3)
        a.write("**Captured by**")
        a.write(item.captured_channel)
        b.write("**Used by**")
        b.write(", ".join(entry.channel for entry in item.used_channels) or "No usage channels assigned")
        c.write("**Relationship owner**")
        c.write(item.owner)
        st.divider()
        a, b, c = st.columns(3)
        a.metric("Open follow-ups", sum(t.contact_id == item.id and t.status == "Open" for t in tasks))
        b.metric("Linked opportunities", sum(o.contact_id == item.id for o in opportunities))
        c.write("**Last conversation**")
        c.write(str(item.last_contact) if item.last_contact else "Not recorded")
        if item.interests:
            st.write("**Interests / capabilities**")
            st.write(item.interests)
        if item.notes:
            st.write("**Relationship context**")
            st.write(item.notes)


def pipeline(opportunities):
    groups = {
        "Explore": {"Identified", "Qualified"},
        "Engage": {"Conversation", "Proposal"},
        "Advance": {"Negotiation", "On hold"},
        "Outcomes": {"Won", "Lost"},
    }
    columns = st.columns(4)
    for column, (name, stages) in zip(columns, groups.items(), strict=True):
        items = [o for o in opportunities if o.stage in stages]
        with column:
            st.subheader(f"{name} · {len(items)}")
            for item in items:
                with st.container(border=True):
                    st.write(f"**{item.name}**")
                    chips([item.stage])
                    st.caption(item.channel + " · " + item.owner)
                    if item.value is not None:
                        st.write(f"${item.value:,.0f}")
                    if item.deadline:
                        st.caption(f"Deadline: {item.deadline}")
                    if item.next_action:
                        st.write(item.next_action)
            if not items:
                st.caption("No opportunities at this stage.")
    other = [o for o in opportunities if not any(o.stage in stages for stages in groups.values())]
    if other:
        st.caption(
            f"{len(other)} imported opportunities use other stage names; review them in the table below."
        )

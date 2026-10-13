from contextlib import contextmanager
from pathlib import Path

from streamlit.testing.v1 import AppTest


def test_empty_workspace_pages_and_contact_creation(db, monkeypatch):
    monkeypatch.setenv("AUTH_MODE", "local")

    @contextmanager
    def test_session():
        yield db

    monkeypatch.setattr("crm.db.session", test_session)
    app = AppTest.from_file(str(Path(__file__).parents[1] / "app.py"), default_timeout=20).run()
    assert not app.exception
    for page in [
        "Contacts",
        "Organizations",
        "Opportunities",
        "Customer insights",
        "Events",
        "Follow-ups",
        "Reminder inbox",
        "Import & export",
        "Overview",
    ]:
        app.sidebar.radio[0].set_value(page).run()
        assert not app.exception and not app.error, page
    app.sidebar.radio[0].set_value("Contacts").run()
    next(w for w in app.text_input if w.label == "Name").set_value("UI contact")
    next(w for w in app.text_input if w.label == "Professional email").set_value("ui@example.com")
    next(b for b in app.button if b.label == "Save contact").click().run()
    assert not app.exception
    from crm.service import contacts

    assert contacts(db, search="ui@example.com")

    # Exercise the populated contact view and create a real follow-up through the UI.
    contact = contacts(db, search="ui@example.com")[0]
    next(w for w in app.selectbox if w.label == "Open contact").set_value(contact.id).run()
    assert not app.exception and not app.error
    [w for w in app.multiselect if w.label == "Used by channels"][-1].set_value(
        ["UR Partners", "UR Private BD"]
    )
    # Two contact forms are visible: edit the existing record, not the blank add form.
    [b for b in app.button if b.label == "Save contact"][-1].click().run()
    assert not app.exception and not app.error
    assert len(contacts(db, used="UR Private BD")) == 1
    app.sidebar.radio[0].set_value("Follow-ups").run()
    next(w for w in app.text_input if w.label == "Action").set_value("Send UI brief")
    next(w for w in app.selectbox if w.label == "Related contact").set_value(contact.id)
    from crm.service import today

    next(w for w in app.date_input if w.label == "Due date (optional)").set_value(today())
    next(b for b in app.button if b.label == "Create follow-up").click().run()
    assert not app.exception and not app.error
    app.sidebar.radio[0].set_value("Reminder inbox").run()
    assert any(b.label == "Complete follow-up" for b in app.button)
    next(b for b in app.button if b.label == "Complete follow-up").click().run()
    assert not app.exception and not app.error
    assert not any(b.label == "Complete follow-up" for b in app.button)

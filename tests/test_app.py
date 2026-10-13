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

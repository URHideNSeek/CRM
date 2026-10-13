from pathlib import Path

from streamlit.testing.v1 import AppTest


def test_simple_contact_conversation_and_followup():
    app = AppTest.from_file(str(Path(__file__).parents[1] / "simple_streamlit_app.py")).run()
    assert not app.exception
    next(v for v in app.text_input if v.label == "Name").set_value("Example Contact")
    next(v for v in app.text_input if v.label == "Organization").set_value("Example Company")
    next(v for v in app.multiselect if v.label == "Used by channels").set_value(
        ["UR Partners", "UR Private BD"]
    )
    next(b for b in app.button if b.label == "Save contact").click().run()
    assert not app.exception
    assert len(app.session_state["contacts"]) == 1
    next(v for v in app.text_area if v.label == "What happened / customer feedback / commitments").set_value(
        "Asked for a brief"
    )
    next(v for v in app.text_input if v.label == "Next action").set_value("Send brief")
    next(v for v in app.checkbox if v.label == "Create a follow-up").check()
    next(b for b in app.button if b.label == "Log conversation").click().run()
    assert not app.exception
    assert len(app.session_state["interactions"]) == 1
    assert len(app.session_state["tasks"]) == 1
    next(b for b in app.button if b.label == "Complete").click().run()
    assert not app.exception
    assert app.session_state["tasks"][0]["status"] == "Completed"
    next(v for v in app.selectbox if v.label == "Used by").set_value("UR Private BD").run()
    assert not app.exception

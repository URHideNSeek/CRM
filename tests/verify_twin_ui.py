"""Exercise Streamlit controls; substitute only the unrelated AgGrid custom component."""
import sys,types
from pathlib import Path
sys.path.insert(0,str(Path(__file__).parents[1]))
from streamlit.testing.v1 import AppTest
stub=types.ModuleType('st_aggrid');stub.JsCode=lambda x:x;stub.AgGrid=lambda *a,**k:types.SimpleNamespace(selected_rows=None);sys.modules['st_aggrid']=stub
store=types.ModuleType('crm.simple_store');store.ConflictError=type('ConflictError',(Exception,),{});store.load=lambda url:(0,{'contacts':[],'interactions':[],'tasks':[]});store.save=lambda url,version,payload:version+1;sys.modules['crm.simple_store']=store
app=AppTest.from_file(str(Path(__file__).parents[1]/'simple_streamlit_app.py'));app.secrets['APP_PASSWORD']='test-password-long-enough';app.run();app.text_input[0].set_value('test-password-long-enough');app.button[0].click().run();assert not app.exception
app.radio[0].set_value('Contacts').run();assert not app.exception
next(x for x in app.text_input if x.label=='Name').set_value('Test Person');next(x for x in app.text_input if x.label=='Organization').set_value('Test Company');next(x for x in app.button if x.label=='Save contact').click().run();assert not app.exception
assert app.session_state['contacts'][0]['professional_twin']['profile_type']=='person'
app.radio[0].set_value('Conversations').run();assert not app.exception
next(x for x in app.text_area if x.label=='What happened / customer feedback / commitments').set_value('Requested a short business overview');next(x for x in app.text_input if x.label=='Next action').set_value('Send the requested business overview');next(x for x in app.checkbox if x.label=='Create a follow-up').check();next(x for x in app.button if x.label=='Log conversation').click().run();assert not app.exception
app.radio[0].set_value('Follow-ups').run();assert not app.exception
next(x for x in app.selectbox if x.label=='Show').set_value('All open').run();assert not app.exception
assert any('What to follow up about' in x.value.columns for x in app.dataframe);assert app.session_state['contacts'][0]['professional_twin']['open_task_ids'];assert any('No open verified change triggers' in x.value for x in app.caption)
print('Streamlit sign-in, person twin, interaction/task update and follow-up screen passed; AgGrid mocked.')
# Check search, scheduling, completion and workspace isolation with synthetic data only.
next(x for x in app.text_input if x.label=='Search follow-ups').set_value('no-such-person').run();assert not app.exception
assert not any(x.label=='Task to review' for x in app.selectbox)
next(x for x in app.text_input if x.label=='Search follow-ups').set_value('').run()
next(x for x in app.button if x.label=='Save date').click().run();assert not app.exception
next(x for x in app.button if x.label=='Mark complete').click().run();assert not app.exception
assert app.session_state['tasks'][0]['status']=='Completed'
app.radio[0].set_value('Contacts').run();assert not app.exception
next(x for x in app.selectbox if x.label=='Open contact').set_value(app.session_state['contacts'][0]['id']).run();assert not app.exception
next(x for x in app.button if x.label=='Add new contact').click().run();assert not app.exception
assert next(x for x in app.text_input if x.label=='Name').value==''
app.radio[0].set_value('Backup & restore').run();assert not app.exception
assert not any(x.label=='Save contact' for x in app.button)
print('Search, date assignment, task completion, new-contact reset and isolated backup workspace passed.')

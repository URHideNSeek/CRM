"""Evidence-backed professional twins and communication triggers. No network or email actions."""
import hashlib,json,re
from datetime import date,datetime,timedelta
from urllib.parse import urlparse
MODEL_VERSION='professional-twin-0.3'
TEMPLATES={
 'investment':('Investment / finance professional',['Prototype and customer evidence','Funding stage and commercial progress'],'Assess fit or route a financing discussion'),
 'program':('Program / startup-support professional',['Company stage and support needs','Program fit and progress on agreed actions'],'Coordinate programs, resources or introductions'),
 'technical':('Engineering / technical supplier professional',['Approved evaluation scope','Readiness and dependencies'],'Assess evaluation fit and route to appropriate engineers'),
 'commercial':('Sales / business development professional',['Specific collaboration or introduction request','Commercial readiness and mutual value'],'Coordinate an appropriate business conversation'),
 'government':('Government / mission-fit professional',['Approved capability and development maturity','Mission need, evaluation objective and acquisition route'],'Assess mission fit or direct an inquiry to the responsible office'),
 'legal':('Legal / contracts / compliance professional',['Agreement status and administrative scope','Business decision and deadlines'],'Route review and administrative next steps through the legal workflow'),
 'research':('University / research professional',['Research question and collaboration scope','Funding opportunity and facilities needs'],'Identify an appropriate research or commercialization discussion'),
 'recruiting':('Recruiting / ordinary professional contact',['Confirmed appointment and role context'],'Coordinate professional scheduling; sensitive recruiting data stays separate'),
 'unknown':('Professional role not established',[],'Clarify responsibilities and the purpose of a conversation'),
 'organization':('Organization profile',['Relevant company developments','Known business relationship and next action'],'Identify which existing relationship could be affected')}
def normalize(value):return re.sub(r'[^a-z0-9]','',str(value).lower())
def title_of(c):
 return c.get('title') or c.get('legacy',{}).get('title') or (re.search(r'^Title:\s*(.+)$',c.get('notes',''),re.M).group(1) if re.search(r'^Title:\s*(.+)$',c.get('notes',''),re.M) else '')
def classify(c):
 if c.get('record_type')=='organization':return 'organization','Organization record'
 title=title_of(c).lower()
 for pattern,role in [(r'attorney|counsel|contract.*manager|compliance','legal'),(r'professor|research|commercialization|tech.*transfer','research'),(r'chief financial|\bcfo\b|investment|fund manager|venture','investment'),(r'contracting officer|acquisition|mission|us government|experiment','government'),(r'engineer|technical|systems|safety','technical'),(r'program|incubat|entrepreneur|capacity building|business coach','program'),(r'sales|business development|marketing','commercial')]:
  if re.search(pattern,title):return role,'Recorded professional title'
 role={'Funder':'investment','Government':'government','University':'research','Vendor':'technical','Partner':'program','Advisor':'commercial'}.get(c.get('kind'),'unknown')
 return role,'Generic contact-category prior; exact job responsibilities unverified'
def public_url(value):
 try:return urlparse(value).scheme in ('https','http') and bool(urlparse(value).hostname)
 except ValueError:return False
def organization_for(c,contacts):
 if c.get('record_type')=='organization':return c
 return next((o for o in contacts if o.get('record_type')=='organization' and (o['id']==c.get('organization_id') or normalize(o.get('organization'))==normalize(c.get('organization')))),{})
def build_twin(c,contacts=(),interactions=(),tasks=()):
 role,basis=classify(c);label,info,purpose=TEMPLATES[role];org=organization_for(c,contacts);parent=org.get('parent_organization') or c.get('parent_organization') or {}
 evidence=[i for i in interactions if i.get('contact_id')==c['id']];open_tasks=[t for t in tasks if t.get('contact_id')==c['id'] and t.get('status')=='Open']
 text=' '.join([c.get('latest_business_summary',''),*(i.get('summary','') for i in evidence)])
 topics={}
 for topic,pattern in [('funding','fund|invest'),('prototype progress','prototype|development'),('introductions','introduc|referr'),('manufacturing','manufactur|supplier'),('research collaboration','research|university|collaborat'),('agreement administration','nda|agreement|contract'),('evaluation','evaluat|test'),('meeting coordination','meeting|schedul')]:
  threads=set()
  for i in evidence:
   if re.search(pattern,i.get('summary',''),re.I):threads.add(next((s.get('thread_id') or s.get('message_id') for s in i.get('source_mail',[]) if s.get('thread_id') or s.get('message_id')),i['id']))
  if threads:topics[topic]={'independent_threads':len(threads),'basis':'Repeated theme' if len(threads)>=2 else 'Single-context interest; persistence unknown'}
 recorded=[{'interaction_id':i['id'],'date':i.get('date'),'source':i.get('source') or i.get('provenance'),'message_ids':[s.get('message_id') for s in i.get('source_mail',[]) if s.get('message_id')]} for i in evidence]
 # Source fingerprint makes changes visible without altering shared templates or inventing traits.
 inputs={'title':title_of(c),'organization':c.get('organization'),'kind':c.get('kind'),'latest_summary':c.get('latest_business_summary'),'notes_digest':hashlib.sha256(c.get('notes','').encode()).hexdigest(),'interactions':[(i['id'],i.get('summary'),i.get('next_action')) for i in evidence],'tasks':[(t['id'],t.get('action'),t.get('due'),t.get('status')) for t in open_tasks],'parent':parent}
 return {'model_version':MODEL_VERSION,'profile_type':'organization' if role=='organization' else 'person','role_template_id':role,'role_template':label,'assignment_basis':basis,'professional_title':title_of(c),'company':c.get('organization',''),'organization_id':org.get('id'),'parent_organization':parent,'template_information_needs':info,'potential_use':purpose,'decision_authority':'Unverified unless separately supported by an explicit source','observed_themes':topics,'timing_basis':'Recorded task dates or specific events; no recurring cadence inferred','evidence':recorded,'open_task_ids':[t['id'] for t in open_tasks],'fingerprint':hashlib.sha256(json.dumps(inputs,sort_keys=True,default=str).encode()).hexdigest(),'watch_entities':{'person':c.get('name','') if role!='organization' else '', 'company':c.get('organization',''),'parent':parent.get('name','')},'parent_discovery_status':'Verified relationship' if parent.get('name') and parent.get('source_url') else 'Parent relationship not verified; discovery pending'}
def ensure_twins(contacts,interactions,tasks):
 for c in contacts:c['professional_twin']=build_twin(c,contacts,interactions,tasks)
def events_for(c,contacts):
 org=organization_for(c,contacts);parent=org.get('parent_organization') or c.get('parent_organization') or {};events=[]
 sources=[c,org] if org and org['id']!=c['id'] else [c]
 for o in contacts:
  if parent.get('name') and normalize(o.get('organization'))==normalize(parent['name']) and o.get('record_type')=='organization':sources.append(o)
 for o in sources:
  for event in o.get('monitored_changes',[]):
   if event.get('id') not in {v.get('id') for v in events}:events.append(event)
 return events
def change_triggers(c,contacts,today=None):
 today=today or date.today();out=[]
 for e in events_for(c,contacts):
  if not e.get('verified') or not public_url(e.get('source_url','')) or e.get('status','Open')!='Open':continue
  try:occurred=date.fromisoformat(e['date'])
  except (ValueError,KeyError):continue
  if not 0<=(today-occurred).days<=30:continue
  if not e.get('communication_relevance'):continue
  out.append({'id':e['id'],'when':'Review now: '+e['date'],'what':e.get('summary',''),'why':e['communication_relevance'],'suggestion':e.get('suggested_followup') or 'Ask whether this change affects the next business discussion or the appropriate contact.','source_url':e['source_url'],'basis':'Verified public change; communication relevance is a recommendation','entity_type':e.get('entity_type','company')})
 return out

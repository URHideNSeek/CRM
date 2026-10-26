import hashlib
import json
from fastapi.testclient import TestClient
from crm.simple_api import app


def test_authenticated_write_context_and_conflict(tmp_path, monkeypatch):
    monkeypatch.setenv('DATABASE_URL', 'sqlite:///' + str(tmp_path / 'api.db'))
    token = 'test-integration-token'
    monkeypatch.setenv('CRM_API_TOKENS_JSON', json.dumps([{'name':'test','channel':'UR Partners','sha256':hashlib.sha256(token.encode()).hexdigest()}]))
    client = TestClient(app)
    assert client.get('/contacts').status_code == 401
    headers = {'Authorization': 'Bearer ' + token}
    assert client.get('/contacts', headers=headers).json()['version'] == 0
    record = dict(name='Example', organization='Example Co', email='', kind='Partner', owner='JJ', captured_by='UR Partners', used_by=['UR Partners'], notes='Test')
    body = dict(version=0, record=record, source='test conversation')
    assert client.put('/records/contacts/example', json=body, headers=headers).status_code == 200
    assert client.put('/records/contacts/example', json=body, headers=headers).status_code == 409
    data = client.get('/contacts/example/context', headers=headers).json()
    assert data['contact']['notes'] == 'Test'
    assert data['version'] == 1


def test_upsert_creates_bridge_rows_from_common_crm_fields(tmp_path, monkeypatch):
    monkeypatch.setenv('DATABASE_URL', 'sqlite:///' + str(tmp_path / 'bridge.db'))
    token = 'test-bridge-token'
    monkeypatch.setenv('CRM_API_TOKENS_JSON', json.dumps([{
        'name': 'test', 'channel': 'UR Partners',
        'sha256': hashlib.sha256(token.encode()).hexdigest(),
    }]))
    client = TestClient(app)
    headers = {'Authorization': 'Bearer ' + token}

    contact = client.put('/records/contacts/P-bridge-new', json={
        'version': 0,
        'source': 'uploaded email dump',
        'record': {
            'name': 'Bridge Contact',
            'organization_name': 'Example Organization',
            'relationship_type': 'Partner',
            'email': '',
            'notes': 'Introduced by email.',
        },
    }, headers=headers)
    assert contact.status_code == 200, contact.text
    assert contact.json()['version'] == 1

    interaction = client.put('/records/interactions/I-bridge-new', json={
        'version': 1,
        'source': 'uploaded email dump',
        'record': {
            'contact_id': 'P-bridge-new',
            'occurred_on': '2026-10-21',
            'summary': 'Introductory exchange recorded.',
            'next_step': 'Schedule a call.',
        },
    }, headers=headers)
    assert interaction.status_code == 200, interaction.text
    assert interaction.json()['version'] == 2

    task = client.put('/records/tasks/T-bridge-new', json={
        'version': 2,
        'source': 'uploaded email dump',
        'record': {
            'contact_id': 'P-bridge-new',
            'title': 'Schedule introductory call',
            'due_date': '2026-10-30',
        },
    }, headers=headers)
    assert task.status_code == 200, task.text
    assert task.json()['version'] == 3

    context = client.get('/contacts/P-bridge-new/context', headers=headers).json()
    assert context['contact']['kind'] == 'Partner'
    assert context['contact']['captured_by'] == 'UR Partners'
    assert context['contact']['used_by'] == []
    assert context['interactions'][0]['channel'] == 'UR Partners'
    assert context['interactions'][0]['next_action'] == 'Schedule a call.'
    assert context['tasks'][0]['action'] == 'Schedule introductory call'
    assert context['tasks'][0]['status'] == 'Open'

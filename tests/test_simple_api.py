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

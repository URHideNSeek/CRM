import pytest
from crm.simple_store import load, save, ConflictError


def test_persistence_and_conflict(tmp_path):
    url = 'sqlite:///' + str(tmp_path / 'crm.db')
    version, data = load(url)
    data['contacts'].append({'id': 'a', 'name': 'Example'})
    assert save(url, version, data) == 1
    assert load(url)[1]['contacts'][0]['name'] == 'Example'
    with pytest.raises(ConflictError):
        save(url, version, {'contacts': []})
    assert len(load(url)[1]['contacts']) == 1

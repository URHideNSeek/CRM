"""NDA coverage is a verified relationship fact, not inferred from an offer."""
from datetime import date

STATUSES = ['Unknown', 'No NDA', 'Pending', 'Executed', 'Expired']

def indicator(contact, today=None):
    if contact.get('record_type') == 'organization':
        return 'Organization record'
    today = today or date.today()
    record = contact.get('nda', {})
    status = record.get('status', 'Unknown')
    if status not in STATUSES: return 'Unknown'
    if status == 'Executed':
        if not record.get('both_parties_signed') or not record.get('coverage_confirmed') or not record.get('evidence_reference'):
            return 'Unknown — execution evidence incomplete'
        try:
            effective = date.fromisoformat(record['effective_date']) if record.get('effective_date') else None
            if effective and effective > today: return 'Pending — effective '+record['effective_date']
            expiry = date.fromisoformat(record['expiration_date']) if record.get('expiration_date') else None
        except (ValueError, TypeError): return 'Unknown — check expiration date'
        if expiry and expiry < today: return 'Expired'
        return 'In place'
    return {'Unknown':'Unknown', 'No NDA':'Not in place', 'Pending':'Pending — not in place', 'Expired':'Expired'}[status]

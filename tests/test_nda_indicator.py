import unittest
from datetime import date
from crm.nda import indicator
class NDA(unittest.TestCase):
 def test_unverified_execution_not_active(self):
  self.assertTrue(indicator({'nda':{'status':'Executed'}}).startswith('Unknown'))
 def test_bilateral_and_expiry(self):
  c={'nda':{'status':'Executed','both_parties_signed':True,'coverage_confirmed':True,'evidence_reference':'agreement1','expiration_date':'2026-10-13'}}
  self.assertEqual(indicator(c,date(2026,10,14)),'Expired')
  c['nda']['expiration_date']='2026-10-14';self.assertEqual(indicator(c,date(2026,10,14)),'In place')
 def test_future_effective(self):
  c={'nda':{'status':'Executed','both_parties_signed':True,'coverage_confirmed':True,'evidence_reference':'agreement1','effective_date':'2026-11-01'}}
  self.assertTrue(indicator(c,date(2026,10,14)).startswith('Pending'))
 def test_pending_unknown_and_no_nda(self):
  for status,expected in [('Pending','Pending — not in place'),('Unknown','Unknown'),('No NDA','Not in place')]:self.assertEqual(indicator({'nda':{'status':status}}),expected)
if __name__=='__main__':unittest.main()

"""User search/profile checks using a disposable database."""
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
import database as db
from services.user_queries import search_users,user_details


class UserSearchTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        env=patch.dict(os.environ,LABAUTH_DB_PATH=str(Path(self.temp.name)/'search.db'))
        env.start();self.addCleanup(env.stop);db.init_db()
        self.a=db.create_user('Aisha Khan',plaksha_id='P001',email='aisha@example.test',phone='123456')
        self.b=db.create_user('Rohan Gupta',plaksha_id='P002',status='inactive')
        self.c=db.create_user('Meera Nair',is_temp=True)
        db.create_ban(self.b.id,reason='Retained ban',banned_by='admin')

    def test_search_all_including_inactive_banned_and_visitors(self):
        self.assertEqual(search_users()['total'],3)
        self.assertEqual(search_users('rohan')['users'][0]['id'],self.b.id)
        self.assertEqual(search_users('P002')['users'][0]['id'],self.b.id)
        self.assertEqual(search_users('Meera')['users'][0]['id'],self.c.id)

    def test_contact_search_and_literal_search(self):
        for value in ('aisha@example.test','123456','KHAN'):
            self.assertEqual(search_users(value)['users'][0]['id'],self.a.id)
        for value in ('%', '_', "' OR 1=1 --"):
            self.assertEqual(search_users(value)['total'],0)

    def test_identity_is_separate_from_presence(self):
        self.assertEqual(search_users('Aisha')['total'],1)
        self.assertIsNone(user_details(self.a.id)['checked_in_at'])
        db.upsert_current_presence(self.a.id)
        self.assertIsNotNone(user_details(self.a.id)['checked_in_at'])

    def test_full_registered_details_and_no_raw_biometric_bytes(self):
        db.set_user_access_areas(self.a.id,['Indoor lab'])
        db.enroll_credential(self.a.id,'fingerprint','template:41',template=b'private-biometric')
        db.enroll_credential(self.a.id,'nfc','card:001')
        user=user_details(self.a.id)
        self.assertEqual(user['email'],'aisha@example.test')
        self.assertEqual(user['phone'],'123456')
        self.assertEqual(user['access'][0]['label'],'Indoor lab')
        self.assertEqual(user['credentials'][0]['template_bytes'],len(b'private-biometric'))
        self.assertNotIn('template',user['credentials'][0])
        self.assertIn(user['created_at'],user['time_labels'])
        self.assertEqual(user_details(self.b.id)['bans'][0]['reason'],'Retained ban')
        self.assertIsNone(user_details(99999))

    def test_pagination_and_lightweight_results(self):
        result=search_users(limit=1,offset=1)
        self.assertEqual(result['total'],3)
        self.assertEqual(len(result['users']),1)
        self.assertEqual(set(result['users'][0]),{'id','name','plaksha_id','photo'})

    def test_invalid_limits_and_long_query(self):
        for options in ({'limit':0},{'limit':101},{'offset':-1},{'query':'a'*201}):
            with self.assertRaises(ValueError):search_users(**options)

if __name__=='__main__':unittest.main()

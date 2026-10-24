"""People mutations, credential uniqueness and retained-history regression tests."""
import os
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
import database as db
from services.people import edit_person, delete_people, MissingPerson
from services.user_queries import search_users, user_details


class PeopleTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.env = patch.dict(os.environ, {'LABAUTH_DB_PATH': str(Path(self.tmp.name) / 'people.db')})
        self.env.start(); db.init_db()
        self.a = db.create_user('Shared Name', plaksha_id='P001')
        self.b = db.create_user('Shared Name', plaksha_id='P002')

    def tearDown(self):
        self.env.stop(); self.tmp.cleanup()

    def test_photo_validation_and_removal(self):
        from services.people import _photo
        import base64
        import io
        from PIL import Image
        output = io.BytesIO()
        Image.new('RGB', (4,4), 'white').save(output, format='PNG')
        value = 'data:image/png;base64,' + base64.b64encode(output.getvalue()).decode()
        path, file = _photo(value)
        self.assertTrue(path.startswith('/static/portraits/portrait_'))
        self.assertIsNotNone(file)
        self.assertEqual(_photo(None), (db.DEFAULT_PHOTO, None))
        for bad in ['https://example.com/photo.png', 'data:image/png;base64,broken', []]:
            with self.assertRaises(ValueError): _photo(bad)
        edit_person(self.a.id, {'photo':None})
        self.assertEqual(db.get_user(self.a.id).photo, db.DEFAULT_PHOTO)

    def test_name_may_repeat_but_id_is_case_insensitive(self):
        self.assertEqual(search_users()['total'], 2)
        with self.assertRaises(sqlite3.IntegrityError):
            db.create_enrolment('Shared Name', plaksha_id=' p001 ')
        self.assertEqual(db.count_users(), 2)
        with self.assertRaises(sqlite3.IntegrityError):
            edit_person(self.b.id, {'plaksha_id': 'p001'})
        self.assertEqual(db.get_user(self.b.id).plaksha_id, 'P002')

    def test_normalized_duplicate_uid_and_template_roll_back_enrolment(self):
        db.enroll_credential(self.a.id, 'nfc', 'aa:bb:cc:dd')
        db.enroll_credential(self.a.id, 'fingerprint', 'template:041')
        for kind, value in [('nfc','AABBCCDD'), ('fingerprint','41')]:
            before = len(db.list_audit_log())
            with self.assertRaises(sqlite3.IntegrityError):
                db.create_enrolment('Another person', credentials=[(kind, value)])
            self.assertEqual(db.count_users(), 2)
            self.assertEqual(len(db.list_audit_log()), before)

    def test_edits_optional_clear_and_audit(self):
        for changes in [{'name':'Updated Name'}, {'email':'user@example.test'}, {'phone':'123'}, {'is_temp':True}, {'plaksha_id':None}]:
            edit_person(self.a.id, changes)
        user = user_details(self.a.id)
        self.assertEqual(user['name'], 'Updated Name')
        self.assertIsNone(user['plaksha_id'])
        self.assertEqual(user['email'], 'user@example.test')
        self.assertEqual(len(db.list_audit_log()), 5)
        for changes in [{'name':''}, {'is_temp':'yes'}, {'status':'bad'}, {'created_at':'yesterday'}, {'email':'broken'}, {'phone':[]}]:
            with self.assertRaises(ValueError): edit_person(self.a.id, changes)

    def test_access_replacement_and_invalid_area_rollback(self):
        area = db.list_access_areas()[0].id
        edit_person(self.a.id, {'access_area_ids':[area]})
        with self.assertRaises(ValueError): edit_person(self.a.id, {'access_area_ids':[99999]})
        self.assertEqual([a.id for a in db.get_user_access_areas(self.a.id)], [area])
        edit_person(self.a.id, {'access_area_ids':[]})
        self.assertEqual(db.get_user_access_areas(self.a.id), [])

    def test_credential_edit_delete_ownership_history_and_reuse(self):
        c = db.enroll_credential(self.a.id, 'nfc', 'AABBCCDD')
        db.log_presence(self.a.id, 'check_in', entry_method='nfc', credential_id=c.id)
        with self.assertRaises(MissingPerson): edit_person(self.b.id, {'credential':{'id':c.id,'delete':True}})
        edit_person(self.a.id, {'credential':{'id':c.id,'identifier':'11:22:33:44','is_active':False}})
        self.assertEqual(db.get_credential(c.id).identifier,'11223344')
        edit_person(self.a.id, {'credential':{'id':c.id,'delete':True}})
        self.assertIsNone(db.get_credential(c.id))
        self.assertEqual(user_details(self.a.id)['credentials'], [])
        self.assertEqual(db.get_presence_entry(1).credential_id, c.id)
        db.enroll_credential(self.b.id, 'nfc', '11223344')
        db.init_db()  # Repeated migrations must allow the retired identifier.

    def test_delete_people_retains_history_and_releases_credentials(self):
        c = db.enroll_credential(self.a.id, 'fingerprint', 'template:41')
        db.log_presence(self.a.id, 'check_in', entry_method='fingerprint', credential_id=c.id)
        db.upsert_current_presence(self.a.id)
        cleaned = []
        delete_people([self.a.id, self.b.id], lambda ids: cleaned.extend(ids))
        self.assertEqual(cleaned, ['template:41'])
        self.assertEqual(search_users()['total'], 0)
        self.assertEqual(len(db.current_occupants()), 0)
        self.assertEqual(len(db.list_presence_log()), 2)
        self.assertIsNone(user_details(self.a.id))
        self.assertIsNone(db.get_user(self.a.id))
        self.assertIsNone(db.update_user(self.a.id, status='active'))
        new = db.create_enrolment('Shared Name', plaksha_id='p001', credentials=[('fingerprint','41')])
        self.assertIsNotNone(new['id'])
        db.init_db()
        self.assertEqual(db.count_users(), 1)

    def test_delete_batch_validation_and_cleanup_failure_are_atomic(self):
        db.enroll_credential(self.a.id, 'fingerprint', 'template:41')
        for ids in [[], [True], [self.a.id,99999]]:
            with self.assertRaises(ValueError): delete_people(ids)
        def failure(ids): raise ValueError('Reader disconnected')
        with self.assertRaisesRegex(ValueError, 'Reader disconnected'):
            delete_people([self.a.id,self.b.id], failure)
        self.assertEqual(search_users()['total'], 2)
        self.assertIsNotNone(db.resolve_user_by_credential('fingerprint','template:41'))
        self.assertEqual(db.list_audit_log(), [])

    def test_deactivate_checks_out_and_ban_edit_lift(self):
        db.upsert_current_presence(self.a.id)
        edit_person(self.a.id, {'status':'inactive'})
        self.assertEqual(len(db.current_occupants()), 0)
        self.assertEqual(db.list_presence_log()[0]['event_type'], 'check_out')
        ban = db.create_ban(self.a.id, reason='Old reason')
        edit_person(self.a.id, {'ban':{'id':ban.id,'reason':'Updated reason','banned_by':'Admin'}})
        edit_person(self.a.id, {'ban':{'id':ban.id,'lift':True}})
        self.assertFalse(db.is_user_banned(self.a.id))
        self.assertEqual(db.get_ban(ban.id).reason,'Updated reason')

if __name__ == '__main__': unittest.main()

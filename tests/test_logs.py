"""Incident-query regression tests against disposable SQLite data."""
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
import database as db
from services.log_queries import query_sql, query_visits, database_schema, date_bounds


class LogsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        env = patch.dict(os.environ, LABAUTH_DB_PATH=str(Path(self.temp.name)/'logs.db'), TZ='Asia/Kolkata')
        env.start(); self.addCleanup(env.stop)
        import time
        time.tzset(); self.addCleanup(time.tzset)
        db.init_db()
        self.a = db.create_user('Aisha Khan', plaksha_id='P001')
        self.b = db.create_user('Rohan Gupta', is_temp=True)
        self.c = db.create_user('Live only')
        self.event(self.a.id,'check_in','2026-10-06T18:00:00Z', 'nfc')
        self.event(self.a.id,'check_out','2026-10-07T04:30:00Z', 'fingerprint')
        self.event(self.a.id,'check_in','2026-10-07T05:00:00Z', 'manual')
        self.event(self.a.id,'check_out','2026-10-07T06:00:00Z', 'manual')
        self.event(self.b.id,'check_in','2026-10-07T05:30:00Z', 'nfc')
        db.upsert_current_presence(self.b.id,'2026-10-07T05:30:00Z')
        db.upsert_current_presence(self.c.id,'2026-10-07T05:00:00Z')

    def event(self, user, kind, at, method='manual'):
        db.log_presence(user,kind,method,occurred_at=at,device_id='reader-1')

    def test_order_live_first_latest_checkout_first(self):
        rows=query_visits({})['rows']
        self.assertEqual([r['state'] for r in rows], ['inside','inside','completed','completed'])
        self.assertEqual([r['check_out'] for r in rows[2:]], ['2026-10-07T06:00:00Z','2026-10-07T04:30:00Z'])
        self.assertEqual(rows[1]['source'],'cache')

    def test_overlap_includes_overnight_and_excludes_cache(self):
        result=query_visits({'from_date':'2026-10-07','from_time':'09:00','until_date':'2026-10-07','until_time':'09:30'})
        self.assertEqual(result['total'],1)
        self.assertEqual(result['rows'][0]['name'],'Aisha Khan')
        self.assertEqual(result['rows'][0]['check_in_local'][:16], '2026-10-06T23:30')

    def test_checkout_exclusive_presence_boundary(self):
        result=query_visits({'from_date':'2026-10-07','from_time':'10:00','until_date':'2026-10-07','until_time':'10:00'})
        self.assertEqual(result['total'],0)

    def test_event_modes_include_end_minute(self):
        filters={'from_date':'2026-10-07','from_time':'10:00','until_date':'2026-10-07','until_time':'10:00','mode':'check_out'}
        self.assertEqual(query_visits(filters)['total'],1)
        filters['mode']='check_in'
        self.assertEqual(query_visits(filters)['total'],0)

    def test_name_id_method_visitor_device_duration(self):
        self.assertEqual(query_visits({'name':'P001','method':'fingerprint','device':'reader-1','min_minutes':'600'})['total'],1)
        self.assertEqual(query_visits({'kind':'visitor'})['total'],1)
        self.assertEqual(query_visits({'name':"' OR 1=1 --"})['total'],0)
        self.assertEqual(query_visits({'name':'%'})['total'],0)
        self.assertEqual(query_visits({'name':'P001','min_minutes':'60'})['total'],2)

    def test_current_permission_filter_and_inactive_history(self):
        area=db.list_access_areas()[0]
        with db.get_db() as conn:
            conn.execute('INSERT INTO user_access_areas VALUES (?,?,?,?)', (self.a.id,area.id,db.utcnow_iso(),'test'))
            conn.execute("UPDATE users SET status='inactive' WHERE id=?",(self.a.id,))
        self.assertEqual(query_visits({'area':str(area.id),'account':'inactive'})['total'],2)

    def test_pagination(self):
        result=query_visits({},limit=1,offset=2)
        self.assertEqual(result['total'],4)
        self.assertEqual(len(result['rows']),1)
        self.assertEqual(result['rows'][0]['check_out'],'2026-10-07T06:00:00Z')

    def test_incomplete_repeated_in_and_orphan_out(self):
        self.event(self.c.id,'check_out','2026-10-05T10:00:00Z')
        self.event(self.c.id,'check_in','2026-10-05T11:00:00Z')
        self.event(self.c.id,'check_in','2026-10-05T12:00:00Z')
        self.event(self.c.id,'check_out','2026-10-05T13:00:00Z')
        rows=query_visits({'state':'incomplete'})['rows']
        self.assertEqual(len(rows),2)
        self.assertTrue(any(r['check_in'] is None for r in rows))
        self.assertTrue(all(r['duration_seconds'] is None for r in rows))
        self.assertTrue(all(r['out_method'] is None for r in rows if r['check_out'] is None))

    def test_invalid_filters(self):
        for filters in ({'mode':'delete'}, {'state':'bad'}, {'min_minutes':'-1'}, {'area':'text'}, {'from_date':'bad'}, {'from_date':'2026-10-08','until_date':'2026-10-07'}):
            with self.subTest(filters=filters), self.assertRaises(ValueError): query_visits(filters)

    def test_sql_read_and_truncation(self):
        self.assertEqual(query_sql('SELECT COUNT(*) AS count FROM presence_log')['rows'],[[5]])
        result=query_sql('WITH RECURSIVE n(x) AS (SELECT 1 UNION ALL SELECT x+1 FROM n WHERE x<250) SELECT x FROM n')
        self.assertTrue(result['truncated'])
        self.assertEqual(len(result['rows']),200)

    def test_sql_cannot_mutate_attach_or_pragma(self):
        for sql in ('DELETE FROM presence_log','UPDATE users SET name=\'bad\'', 'DROP TABLE users', "ATTACH DATABASE ':memory:' AS other", 'PRAGMA query_only=OFF', 'SELECT load_extension(\'anything\')', 'SELECT 1; DELETE FROM users', 'SELECT randomblob(10000000)'):
            with self.subTest(sql=sql), self.assertRaises(ValueError): query_sql(sql)
        self.assertEqual(query_sql('SELECT COUNT(*) FROM presence_log')['rows'],[[5]])

    def test_sql_every_table_and_joins(self):
        tables = database_schema()
        self.assertIn('credentials', [t['name'] for t in tables])
        self.assertIn('settings', [t['name'] for t in tables])
        for table in tables:
            quoted = '"' + table['name'].replace('"', '""') + '"'
            self.assertIn('rows', query_sql(f'SELECT * FROM {quoted} LIMIT 1'))
        result = query_sql('SELECT u.name, p.event_type FROM users u JOIN presence_log p ON p.user_id=u.id')
        self.assertEqual(len(result['rows']), 5)
        self.assertEqual(query_sql('WITH x AS (SELECT 1 AS id) SELECT COUNT(*) FROM x')['rows'], [[1]])
        self.assertEqual(query_sql('SELECT COUNT(*) FROM (SELECT 1)')['rows'], [[1]])
        user = next(t for t in tables if t['name']=='users')
        self.assertEqual(next(c['type'] for c in user['columns'] if c['name']=='name'), 'TEXT')
        presence = next(t for t in tables if t['name']=='presence_log')
        self.assertTrue(any(f['table']=='users' and f['from']=='user_id' for f in presence['foreign_keys']))
        # A backend-added table, including a quote in its name, is discoverable.
        with db.get_db() as connection:
            connection.execute('CREATE TABLE "extra""table" (id INTEGER PRIMARY KEY, note TEXT)')
        self.assertIn('extra"table', [t['name'] for t in database_schema()])
        self.assertEqual(query_sql('SELECT * FROM "extra""table"')['columns'], ['id','note'])

    def test_sql_write_bypass_attempts_leave_database_unchanged(self):
        attacks = [
            '/* SELECT */ DELETE FROM users RETURNING id',
            'WITH x AS (SELECT 1) DELETE FROM presence_log RETURNING id',
            'WITH x AS (SELECT 1) UPDATE users SET name="bad" RETURNING id',
            'INSERT INTO users (name,created_at,updated_at) VALUES ("bad","now","now") RETURNING id',
            'REPLACE INTO settings VALUES ("bad","bad","bad")',
            'CREATE TABLE new_table (id INTEGER)', 'CREATE TEMP TABLE other (id INTEGER)',
            'ALTER TABLE users ADD COLUMN injected TEXT', 'DROP INDEX idx_users_name',
            'CREATE TRIGGER wipe AFTER INSERT ON users BEGIN DELETE FROM presence_log; END',
            'PRAGMA writable_schema=ON', 'PRAGMA user_version=123',
            "SELECT * FROM pragma_table_info('users')",
            "VACUUM INTO '/tmp/labauth-should-not-exist.db'", 'BEGIN', 'SAVEPOINT bypass',
            'SELECT 1; /* comment */ DELETE FROM presence_log',
            'SELECT LOAD_EXTENSION("bad")', 'SELECT writefile("bad","bad")',
        ]
        before = query_sql('SELECT id,name,status FROM users ORDER BY id')['rows']
        for sql in attacks:
            with self.subTest(sql=sql), self.assertRaises(ValueError): query_sql(sql)
        self.assertEqual(query_sql('SELECT id,name,status FROM users ORDER BY id')['rows'], before)
        self.assertEqual(query_sql('SELECT COUNT(*) FROM presence_log')['rows'], [[5]])
        self.assertEqual(query_sql("SELECT 'DELETE FROM users' AS harmless")['rows'], [['DELETE FROM users']])

    def test_future_dates_and_records_excluded(self):
        future = (db.datetime.now().date() + db.timedelta(days=1)).isoformat()
        for key in ('from_date','until_date'):
            with self.assertRaisesRegex(ValueError,'Future dates'): query_visits({key:future})
        self.event(self.a.id, 'check_in', future+'T12:00:00Z')
        self.assertEqual(query_visits({})['total'],4)
        self.assertEqual(date_bounds()['max'],db.datetime.now().date().isoformat())
        with self.assertRaises(ValueError): query_visits({'from_date':'2026-02-30'})

    def test_ban_and_deactivation_retain_user_credentials_and_history(self):
        db.enroll_credential(self.a.id,'nfc','retained-card')
        db.create_ban(self.a.id,reason='Permanent ban',banned_by='admin')
        self.assertTrue(db.deactivate_user(self.a.id))
        self.assertIsNotNone(db.get_user(self.a.id))
        self.assertTrue(db.is_user_banned(self.a.id))
        self.assertEqual(len(db.list_credentials(user_id=self.a.id)),1)
        self.assertEqual(query_visits({'account':'inactive'})['total'],2)
        self.assertEqual(query_sql('SELECT COUNT(*) FROM presence_log')['rows'],[[5]])
        self.assertFalse(hasattr(db,'delete_user'))

if __name__=='__main__': unittest.main()

"""Read-only incident queries over immutable events and the live cache."""
from contextlib import contextmanager
from datetime import datetime, time as clock_time, timedelta, timezone
import sqlite3
import time

import database as db


@contextmanager
def reader():
    connection = sqlite3.connect(db.db_path().resolve().as_uri() + '?mode=ro', uri=True)
    connection.row_factory = sqlite3.Row
    connection.setlimit(sqlite3.SQLITE_LIMIT_LENGTH, 65536)
    connection.setlimit(sqlite3.SQLITE_LIMIT_COLUMN, 100)
    connection.setlimit(sqlite3.SQLITE_LIMIT_SQL_LENGTH, 10000)
    connection.execute('PRAGMA query_only = ON')
    deadline = time.monotonic() + 3
    connection.set_progress_handler(lambda: int(time.monotonic() > deadline), 1000)
    try:
        yield connection
    finally:
        connection.close()


# Pair only adjacent in/out events. Repeated ins and orphan outs remain visible
# as incomplete records; never infer a checkout or bridge an unexplained gap.
VISITS = '''
WITH ordered AS (
 SELECT *, LEAD(event_type) OVER w AS next_type,
 LEAD(occurred_at) OVER w AS next_at, LEAD(id) OVER w AS next_id,
 LEAD(entry_method) OVER w AS next_method, LEAD(device_id) OVER w AS next_device,
 LAG(event_type) OVER w AS previous_type
 FROM presence_log WHERE julianday(occurred_at)<=julianday(:now)
 WINDOW w AS (PARTITION BY user_id ORDER BY julianday(occurred_at), id)
), visits AS (
 SELECT 'log-' || o.id AS visit_id, o.user_id, o.id AS check_in_id,
 CASE WHEN next_type='check_out' THEN next_id END AS check_out_id,
 o.occurred_at AS check_in,
 CASE WHEN next_type='check_out' THEN next_at END AS check_out,
 o.entry_method AS method, o.device_id AS device,
 CASE WHEN next_type='check_out' THEN next_method END AS out_method,
 CASE WHEN next_type='check_out' THEN next_device END AS out_device,
 CASE WHEN next_type='check_out' THEN 'completed'
      WHEN next_type IS NULL AND cp.user_id IS NOT NULL
       AND julianday(cp.checked_in_at)=julianday(o.occurred_at) THEN 'inside'
      ELSE 'incomplete' END AS state,
 next_at AS boundary, 'event' AS source
 FROM ordered o LEFT JOIN current_presence cp ON cp.user_id=o.user_id
 WHERE o.event_type='check_in'
 UNION ALL
 SELECT 'log-' || id, user_id, NULL, id, NULL, occurred_at,
 NULL, NULL, entry_method, device_id, 'incomplete', occurred_at, 'event'
 FROM ordered WHERE event_type='check_out' AND (previous_type IS NULL OR previous_type!='check_in')
 UNION ALL
 SELECT 'live-' || cp.user_id, cp.user_id, NULL, NULL, cp.checked_in_at,
 NULL, NULL, NULL, NULL, NULL, 'inside', NULL, 'cache'
 FROM current_presence cp WHERE julianday(cp.checked_in_at)<=julianday(:now) AND NOT EXISTS (
  SELECT 1 FROM ordered o WHERE o.user_id=cp.user_id AND o.event_type='check_in'
  AND o.next_type IS NULL AND julianday(o.occurred_at)=julianday(cp.checked_in_at)
 )
), enriched AS (
 SELECT v.*, u.name, u.photo, u.plaksha_id, u.is_temp, u.status,
 CASE WHEN check_in IS NOT NULL AND (check_out IS NOT NULL OR state='inside')
 THEN MAX(0, (julianday(COALESCE(check_out, :now))-julianday(check_in))*86400) END AS duration_seconds
 FROM visits v JOIN users u ON u.id=v.user_id
)
'''


def _bound(date_value, time_value, *, end=False):
    if not date_value and not time_value:
        return None
    try:
        day = datetime.strptime(date_value, '%Y-%m-%d').date() if date_value else datetime.now().date()
        if day > datetime.now().date():
            raise ValueError('Future dates are unavailable.')
        value = clock_time.fromisoformat(time_value) if time_value else (clock_time.max if end else clock_time.min)
        local = datetime.combine(day, value).astimezone()
        # Treat an entered end minute as inclusive, down to its final second.
        if end and time_value and len(time_value) == 5:
            local += timedelta(seconds=59, microseconds=999999)
        return local.astimezone(timezone.utc).isoformat()
    except (ValueError, TypeError) as error:
        if str(error) == 'Future dates are unavailable.':
            raise
        raise ValueError('Enter a valid date and time.') from error


def query_visits(filters, *, limit=50, offset=0):
    mode = filters.get('mode', 'present')
    if mode not in ('present', 'check_in', 'check_out'):
        raise ValueError('Choose a valid time filter.')
    start = _bound(filters.get('from_date', ''), filters.get('from_time', ''))
    end = _bound(filters.get('until_date', ''), filters.get('until_time', ''), end=True)
    if start and end and datetime.fromisoformat(start) > datetime.fromisoformat(end):
        raise ValueError('The end must follow the start.')
    params = {'now': db.utcnow_iso(), 'limit': limit, 'offset': offset}
    where = []
    if start or end:
        # Cache-only demo presence is current state, not historical evidence.
        where.append("source='event'")
    if mode == 'present':
        if start:
            where.append('julianday(COALESCE(check_out, boundary, :now)) > julianday(:start)')
        if end:
            where.append('julianday(COALESCE(check_in, check_out)) <= julianday(:end)')
    else:
        where.append(f'{mode} IS NOT NULL')
        if start:
            where.append(f'julianday({mode}) >= julianday(:start)')
        if end:
            where.append(f'julianday({mode}) <= julianday(:end)')
    params.update(start=start, end=end)
    search = filters.get('name', '').strip()
    if len(search) > 200:
        raise ValueError('Keep the search under 200 characters.')
    if search:
        where.append("(name LIKE :name ESCAPE '\\' OR plaksha_id LIKE :name ESCAPE '\\')")
        params['name'] = '%' + search.replace('\\', '\\\\').replace('%', '\\%').replace('_', '\\_') + '%'
    for key, column, choices in (
        ('state', 'state', ('inside', 'completed', 'incomplete')),
        ('method', 'method', ('nfc', 'fingerprint', 'manual')),
        ('account', 'status', ('active', 'inactive')),
    ):
        value = filters.get(key, '')
        if value:
            if value not in choices:
                raise ValueError(f'Choose a valid {key}.')
            # Either endpoint may have used the selected method.
            where.append('(method=:method OR out_method=:method)' if key == 'method' else f'{column}=:{key}')
            params[key] = value
    kind = filters.get('kind', '')
    if kind:
        if kind not in ('member', 'visitor'):
            raise ValueError('Choose a valid user type.')
        where.append('is_temp=:temp')
        params['temp'] = int(kind == 'visitor')
    area = filters.get('area', '')
    if area:
        where.append('EXISTS (SELECT 1 FROM user_access_areas a WHERE a.user_id=enriched.user_id AND a.area_id=:area)')
        try:
            params['area'] = int(area)
        except ValueError as error:
            raise ValueError('Choose a valid access area.') from error
    device = filters.get('device', '').strip()
    if device:
        where.append('(device=:device OR out_device=:device)')
        params['device'] = device
    minimum = filters.get('min_minutes', '')
    if minimum:
        try:
            minutes = int(minimum)
            if not 0 <= minutes <= 525600:
                raise ValueError()
        except ValueError as error:
            raise ValueError('Enter a duration from 0 to 525600 minutes.') from error
        where.append('duration_seconds + 0.001 >= :seconds')
        params['seconds'] = minutes * 60
    predicate = ' WHERE ' + ' AND '.join(where) if where else ''
    with reader() as connection:
        # Keep count and page in the same snapshot.
        connection.execute('BEGIN')
        total = connection.execute(VISITS + 'SELECT COUNT(*) FROM enriched' + predicate, params).fetchone()[0]
        rows = connection.execute(VISITS + 'SELECT * FROM enriched' + predicate + '''
         ORDER BY (state='inside') DESC, julianday(check_out) DESC,
         julianday(check_in) DESC, visit_id DESC LIMIT :limit OFFSET :offset''', params).fetchall()
    result = [dict(row) for row in rows]
    for row in result:
        for key in ('check_in', 'check_out'):
            row[key + '_local'] = datetime.fromisoformat(row[key].replace('Z', '+00:00')).astimezone().isoformat() if row[key] else None
    return {'rows': result, 'total': total, 'limit': limit, 'offset': offset, 'date_bounds': date_bounds()}


def date_bounds():
    with reader() as connection:
        earliest = connection.execute("SELECT MIN(julianday(occurred_at)) FROM presence_log WHERE julianday(occurred_at)<=julianday(?)", (db.utcnow_iso(),)).fetchone()[0]
    today = datetime.now().date().isoformat()
    first = datetime.fromtimestamp((earliest - 2440587.5) * 86400, timezone.utc).astimezone().date().isoformat() if earliest is not None else today
    return {'min': first, 'max': today}


def database_schema():
    """Discover every persistent table/view from SQLite, including later additions."""
    with reader() as connection:
        tables = connection.execute("SELECT name, type FROM sqlite_schema WHERE type IN ('table', 'view') ORDER BY name").fetchall()
        result = []
        for table in tables:
            name = table['name']
            # Identifiers come from SQLite, but still quote them correctly.
            quoted = '"' + name.replace('"', '""') + '"'
            columns = [dict(row) for row in connection.execute(f'PRAGMA table_xinfo({quoted})')]
            links = [dict(row) for row in connection.execute(f'PRAGMA foreign_key_list({quoted})')]
            result.append({'name': name, 'type': table['type'], 'columns': columns, 'foreign_keys': links})
    return result


def query_sql(sql):
    if not isinstance(sql, str) or not sql.strip() or len(sql) > 10000:
        raise ValueError('Enter a query under 10000 characters.')
    with reader() as connection:
        # Only built-in SQLite functions; no extension or application callbacks.
        functions = {row[0].lower() for row in connection.execute('PRAGMA function_list') if row[1]}
    def authorize(action, arg1, arg2, database, _trigger):
        if action == sqlite3.SQLITE_READ:
            # None also represents computed CTE/subquery results and COUNT reads.
            # This fresh connection has only main; ATTACH and temp DDL are denied.
            return sqlite3.SQLITE_OK if database in ('main', None) else sqlite3.SQLITE_DENY
        if action in (sqlite3.SQLITE_SELECT, sqlite3.SQLITE_RECURSIVE):
            return sqlite3.SQLITE_OK
        if action == sqlite3.SQLITE_FUNCTION:
            name = (arg2 or '').lower()
            return sqlite3.SQLITE_OK if name in functions and name not in ('load_extension', 'readfile', 'writefile') else sqlite3.SQLITE_DENY
        return sqlite3.SQLITE_DENY
    with reader() as connection:
        connection.set_authorizer(authorize)
        try:
            cursor = connection.execute(sql)
            if cursor.description is None:
                raise ValueError('Only read-only queries are allowed.')
            columns = [item[0] for item in cursor.description]
            raw = cursor.fetchmany(201)
        except sqlite3.Error as error:
            raise ValueError(f'Query failed: {error}') from error
    def cell(value):
        if isinstance(value, bytes):
            return '[binary]'
        return value[:4096] + '…' if isinstance(value, str) and len(value) > 4096 else value
    rows = [[cell(value) for value in row] for row in raw[:200]]
    if sum(len(str(value)) for row in rows for value in row) > 2_000_000:
        raise ValueError('Result too large. Select fewer columns or rows.')
    return {'columns': columns, 'rows': rows, 'truncated': len(raw) > 200}

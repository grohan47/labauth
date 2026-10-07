"""Read-only user search and registered profiles, including retained accounts."""
from services.log_queries import reader
from datetime import datetime


def search_users(query='', *, limit=50, offset=0):
    if not isinstance(query, str) or len(query) > 200:
        raise ValueError('Keep the search under 200 characters.')
    if not 1 <= limit <= 100 or offset < 0:
        raise ValueError('Choose a valid page.')
    term = query.strip().replace('\\', '\\\\').replace('%', '\\%').replace('_', '\\_')
    predicate = " WHERE name LIKE :q ESCAPE '\\' OR plaksha_id LIKE :q ESCAPE '\\' OR email LIKE :q ESCAPE '\\' OR phone LIKE :q ESCAPE '\\'" if term else ''
    params = {'q': '%' + term + '%', 'limit': limit, 'offset': offset}
    with reader() as connection:
        connection.execute('BEGIN')
        total = connection.execute('SELECT COUNT(*) FROM users' + predicate, params).fetchone()[0]
        rows = connection.execute('SELECT id,name,photo,plaksha_id FROM users' + predicate +
                                  ' ORDER BY name COLLATE NOCASE,id LIMIT :limit OFFSET :offset', params).fetchall()
    return {'users': [dict(row) for row in rows], 'total': total, 'offset': offset, 'limit': limit}


def user_details(user_id):
    with reader() as connection:
        connection.execute('BEGIN')
        row = connection.execute('SELECT * FROM users WHERE id=?', (user_id,)).fetchone()
        if row is None:
            return None
        user = dict(row)
        user['access'] = [dict(r) for r in connection.execute('''
            SELECT a.id,a.code,a.label,g.granted_at,g.granted_by FROM user_access_areas g
            JOIN access_areas a ON a.id=g.area_id WHERE g.user_id=?
            ORDER BY a.sort_order,a.label,a.id''', (user_id,))]
        # Credentials are shown as registrations, never raw biometric bytes.
        user['credentials'] = [dict(r) for r in connection.execute('''
            SELECT id,credential_type,identifier,is_active,enrolled_at,
            LENGTH(template) AS template_bytes FROM credentials WHERE user_id=?
            ORDER BY enrolled_at,id''', (user_id,))]
        user['bans'] = [dict(r) for r in connection.execute('SELECT * FROM bans WHERE user_id=? ORDER BY banned_at DESC,id DESC', (user_id,))]
        current = connection.execute('SELECT checked_in_at FROM current_presence WHERE user_id=?', (user_id,)).fetchone()
        user['checked_in_at'] = current[0] if current else None
    values = [user['created_at'], user['updated_at'], user['checked_in_at']]
    values += [a['granted_at'] for a in user['access']]
    values += [c['enrolled_at'] for c in user['credentials']]
    values += [value for ban in user['bans'] for value in (ban['banned_at'], ban['unbanned_at'])]
    user['time_labels'] = {}
    for value in values:
        if value:
            try:
                user['time_labels'][value] = datetime.fromisoformat(value.replace('Z', '+00:00')).astimezone().strftime('%d %b %Y · %H:%M:%S %Z')
            except (ValueError, TypeError):
                user['time_labels'][value] = value
    return user

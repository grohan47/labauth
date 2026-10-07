"""Swiss presence history: filters, visits and progressively disclosed SQL."""
from nicegui import ui
import database as db
from ui.admin_display import ADMIN_ICONS_JS
from services.log_queries import date_bounds, database_schema
from ui.lyne import asset_url, button, container, element, form_field, lyne_assets, select


def choice(label, key, options, default=''):
    return element('sbb-form-field', element('label', label, for_=f'logs-{key}') + select(
        name=key, html_id=f'logs-{key}', options=tuple(options), value=default,
        data_filter=key), size='s', floating_label=True)


def field(label, key, type_='text', **attrs):
    return form_field(label=label, input_id=f'logs-{key}', size='s', floating_label=True, input_attrs={
        'type': type_, 'data-filter': key, **attrs})


def action(label, key, icon, **attrs):
    return button(variant='transparent', size='m', html_id=f'logs-{key}',
                  icon_name=icon, aria_label=label, sbb_tooltip=label, **attrs)


def build_logs_page():
    from ui.display import _color_scheme
    theme = _color_scheme()
    bounds = date_bounds()
    tables = database_schema()
    ui.add_head_html(f'''
      <link rel="icon" type="image/svg+xml" href="/static/favicon.svg">
      <link rel="stylesheet" href="{asset_url('display.css')}">
      <link rel="stylesheet" href="{asset_url('logs.css')}">
      <script>document.documentElement.dataset.theme='{theme}'; {ADMIN_ICONS_JS}</script>
      {lyne_assets()}
      <script type="module" src="{asset_url('logs.js')}"></script>
    ''')
    header = element('header', element('h1', 'Logs.', css_class='admin-heading') + element('div',
        action('More filters', 'more', 'controls-small', aria_expanded='false', aria_controls='logs-extra')
        + action('Export CSV', 'export', 'document-text-small')
        + button('SQL', variant='transparent', size='m', html_id='logs-sql-open', sbb_tooltip='Read-only SQL')
        + button('Back', variant='secondary', size='m', link=True, href='/admin'),
        css_class='logs-actions'), css_class='admin-header')
    areas = [('', 'All')] + [(str(area.id), area.label) for area in db.list_access_areas()]
    extra = element('div',
        choice('Visit', 'state', [('', 'All'), ('inside', 'Inside now'), ('completed', 'Completed'), ('incomplete', 'Incomplete')])
        + choice('Method', 'method', [('', 'All'), ('nfc', 'NFC'), ('fingerprint', 'Fingerprint'), ('manual', 'Manual')])
        + choice('User type', 'kind', [('', 'All'), ('member', 'Member'), ('visitor', 'Visitor')])
        + choice('Account', 'account', [('', 'All'), ('active', 'Active'), ('inactive', 'Inactive')])
        + choice('Access now', 'area', areas)
        + field('Device', 'device', maxlength=200)
        + field('Min. minutes', 'min_minutes', 'number', min=0, max=525600),
        id='logs-extra', css_class='logs-filter-row logs-extra', hidden=True)
    filters = element('form', extra + element('div',
        field('Name / ID', 'name', 'search', maxlength=200)
        + field('From date', 'from_date', 'date', min=bounds['min'], max=bounds['max'])
        + field('From time', 'from_time', 'time')
        + field('Until date', 'until_date', 'date', min=bounds['min'], max=bounds['max'])
        + field('Until time', 'until_time', 'time')
        + choice('Time filter', 'mode', [('present', 'Present during'), ('check_in', 'Check-in'), ('check_out', 'Checkout')], 'present')
        + action('Clear filters', 'reset', 'cross-small'), css_class='logs-filter-row'),
        id='logs-filters')
    headers = ''.join(element('th', name, scope='col') for name in ('Person', 'Check-in', 'Checkout', 'Duration', ''))
    table = element('sbb-table-wrapper', element('table', element('thead', element('tr', headers))
        + element('tbody', '', id='logs-rows'), css_class='sbb-table sbb-table--unstriped', aria_label='Presence visits'),
        css_class='logs-table', id='logs-table', focusable=True)
    footer = element('footer', element('span', 'Loading…', id='logs-count', role='status', aria_live='polite')
        + element('span', '', id='logs-zone') + element('div',
            button('Previous', variant='transparent', size='s', html_id='logs-prev', disabled=True)
            + button('Next', variant='transparent', size='s', html_id='logs-next', disabled=True),
            css_class='logs-actions'), css_class='logs-footer')
    sql = element('sbb-dialog', element('sbb-dialog-title', 'SQL')
        + element('sbb-dialog-content',
            choice('Table', 'sql_table', [(table['name'], table['name']) for table in tables], 'presence_log')
            + element('div', '', id='logs-schema', aria_label='Table schema')
            + element('sbb-form-field', element('label', 'Read-only query', for_='logs-query')
                + element('textarea', 'SELECT * FROM presence_log ORDER BY occurred_at DESC LIMIT 100;',
                          id='logs-query', rows=5, maxlength=10000), size='m', width='collapse')
            + element('p', '', id='logs-sql-status', role='status', aria_live='polite')
            + element('sbb-table-wrapper', element('table', '', id='logs-sql-table',
                css_class='sbb-table sbb-table-s', aria_label='SQL results')), css_class='logs-sql-content')
        + element('sbb-dialog-actions', button('Close', variant='secondary', html_id='logs-sql-close', size='m')
            + button('Run', html_id='logs-sql-run', size='m')),
        id='logs-sql-dialog', backdrop='translucent', backdrop_action='close')
    detail = element('sbb-dialog', element('sbb-dialog-title', 'Visit')
        + element('sbb-dialog-content', '', id='logs-detail-content')
        + element('sbb-dialog-actions', button('Close', variant='secondary', html_id='logs-detail-close', size='m')),
        id='logs-detail-dialog', backdrop='translucent', backdrop_action='close')
    page = element('main', container(element('div', header + filters
        + element('p', '', id='logs-error', role='alert', hidden=True)
        + table + footer + sql + detail, css_class='logs-layout'), expanded=True, css_class='admin-panel-shell'),
        css_class='admin-panel admin-panel--logs')
    ui.html(page, sanitize=False).classes('w-full admin-panel-host')

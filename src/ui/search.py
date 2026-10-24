"""Lyne People table and editable profiles."""
from nicegui import ui
from ui.admin_display import ADMIN_ICONS_JS
from ui.display import _color_scheme
from ui.lyne import asset_url, button, container, element, form_field, lyne_assets


def build_search_page():
    theme = _color_scheme()
    ui.add_head_html(f'''
      <link rel="icon" type="image/svg+xml" href="/static/favicon.svg">
      <link rel="stylesheet" href="{asset_url('display.css')}">
      <link rel="stylesheet" href="{asset_url('search.css')}">
      <script>document.documentElement.dataset.theme='{theme}'; {ADMIN_ICONS_JS}</script>
      {lyne_assets()}
      <script type="module" src="{asset_url('search.js')}"></script>
    ''')
    nav_tabs = element('div',
        button('People', variant='primary', link=True, href='/people', size='m')
        + button('Credentials', variant='secondary', link=True, href='/credentials', size='m'),
        css_class='admin-nav-tabs')
    header = element('header', element('h1', 'People.', css_class='admin-heading')
        + nav_tabs
        + button('Back', variant='secondary', link=True, href='/admin', size='m'), css_class='admin-header')
    query = element('form', form_field(label='Name / ID / email / phone', input_id='search-user-input',
        size='m', floating_label=True, input_attrs={'type': 'search', 'maxlength': 200, 'autocomplete': 'off'}),
        id='search-form', role='search')
    toolbar = element('div', element('sbb-checkbox', 'Select loaded people', id='search-select-all', size='s')
        + element('span', '', id='search-selected', role='status', aria_live='polite')
        + button('Delete selected', variant='secondary', size='s', icon_name='trash-small', html_id='search-delete', disabled=True),
        css_class='search-toolbar')
    headings = ''.join(element('th', name, scope='col') for name in ('', 'Person', 'Plaksha ID', 'LabAuth ID'))
    results = element('sbb-table-wrapper', element('table', element('thead', element('tr', headings))
        + element('tbody', '', id='search-results-list'), css_class='sbb-table sbb-table--unstriped', aria_label='People'),
        css_class='search-results', focusable=True)
    footer = element('footer', element('span', 'Loading…', id='search-count', role='status', aria_live='polite')
        + button('Load more', variant='secondary', size='s', html_id='search-more', hidden=True), css_class='search-footer')
    dialog = element('sbb-dialog', element('sbb-dialog-title', 'Profile', id='search-profile-title')
        + element('sbb-dialog-content', element('p', '', id='search-profile-error', role='alert', hidden=True)
            + element('div', '', id='search-profile-content'))
        + element('sbb-dialog-actions', button('Delete person', variant='transparent', icon_name='trash-small', size='m', html_id='search-profile-delete')
            + button('Close', variant='secondary', size='m', html_id='search-profile-close')),
        id='search-profile-dialog', backdrop='translucent', backdrop_action='close')
    edit = element('sbb-dialog', element('sbb-dialog-title', 'Edit', id='search-edit-title')
        + element('sbb-dialog-content', element('form', '', id='search-edit-form')
            + element('p', '', id='search-edit-error', role='alert', hidden=True))
        + element('sbb-dialog-actions', button('Cancel', variant='secondary', size='m', html_id='search-edit-cancel')
            + button('Save', size='m', html_id='search-edit-save')),
        id='search-edit-dialog', backdrop='translucent', backdrop_action='none')
    confirm = element('sbb-dialog', element('sbb-dialog-title', 'Delete?', id='search-confirm-title')
        + element('sbb-dialog-content', element('p', '', id='search-confirm-text')
            + element('p', '', id='search-confirm-error', role='alert', hidden=True))
        + element('sbb-dialog-actions', button('Cancel', variant='secondary', size='m', html_id='search-confirm-cancel')
            + button('Delete', size='m', html_id='search-confirm-delete')),
        id='search-confirm-dialog', backdrop='translucent', backdrop_action='none')
    body = header + query + toolbar + element('p', '', id='search-error', role='alert', hidden=True) + results + footer + dialog + edit + confirm
    ui.html(element('main', container(body, expanded=True, css_class='admin-panel-shell'),
        css_class='admin-panel admin-panel--search'), sanitize=False).classes('w-full admin-panel-host')

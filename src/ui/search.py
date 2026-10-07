"""Live user cards and a read-only Lyne profile dialog."""
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
    header = element('header', element('h1', 'Search.', css_class='admin-heading')
        + button('Back', variant='secondary', link=True, href='/admin', size='m'), css_class='admin-header')
    query = element('form', form_field(label='Name / ID / email / phone', input_id='search-user-input',
        size='m', floating_label=True, input_attrs={'type':'search','maxlength':200,'autocomplete':'off'}),
        id='search-form', role='search')
    results = element('div', '', id='search-results-list', css_class='search-results', aria_label='Users')
    footer = element('footer', element('span', 'Loading…', id='search-count', role='status', aria_live='polite')
        + button('Load more', variant='secondary', size='s', html_id='search-more', hidden=True), css_class='search-footer')
    dialog = element('sbb-dialog', element('sbb-dialog-title', 'Profile', id='search-profile-title')
        + element('sbb-dialog-content', '', id='search-profile-content')
        + element('sbb-dialog-actions', button('Close', variant='secondary', size='m', html_id='search-profile-close')),
        id='search-profile-dialog', backdrop='translucent', backdrop_action='close')
    body = header + query + element('p', '', id='search-error', role='alert', hidden=True) + results + footer + dialog
    ui.html(element('main', container(body, expanded=True, css_class='admin-panel-shell'),
        css_class='admin-panel admin-panel--search'), sanitize=False).classes('w-full admin-panel-host')

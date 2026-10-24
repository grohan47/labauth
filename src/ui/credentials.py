"""Lyne Credentials table and template management."""
from nicegui import ui
from ui.admin_display import ADMIN_ICONS_JS
from ui.display import _color_scheme
from ui.lyne import asset_url, button, container, element, form_field, lyne_assets


def build_credentials_page():
    theme = _color_scheme()
    ui.add_head_html(f'''
      <link rel="icon" type="image/svg+xml" href="/static/favicon.svg">
      <link rel="stylesheet" href="{asset_url('display.css')}">
      <link rel="stylesheet" href="{asset_url('search.css')}">
      <script>document.documentElement.dataset.theme='{theme}'; {ADMIN_ICONS_JS}</script>
      {lyne_assets()}
      <script type="module" src="{asset_url('credentials.js')}"></script>
    ''')
    nav_tabs = (
        button('People', variant='secondary', link=True, href='/people', size='m')
        + button('Credentials', variant='primary', link=True, href='/credentials', size='m')
    )
    header = element(
        'header',
        element('h1', 'Credentials.', css_class='admin-heading')
        + element('div', nav_tabs, css_class='admin-nav-tabs')
        + button('Back', variant='secondary', link=True, href='/admin', size='m'),
        css_class='admin-header',
    )
    query = element(
        'form',
        form_field(
            label='Search by template ID / UID / person / plaksha ID',
            input_id='cred-search-input',
            size='m',
            floating_label=True,
            input_attrs={'type': 'search', 'maxlength': 200, 'autocomplete': 'off'},
        ),
        id='cred-search-form',
        role='search',
    )
    toolbar = element(
        'div',
        element(
            'div',
            button('All', variant='primary', size='s', html_id='cred-filter-all')
            + button('Fingerprints', variant='secondary', size='s', html_id='cred-filter-fingerprint')
            + button('NFC Cards', variant='secondary', size='s', html_id='cred-filter-nfc'),
            css_class='cred-filter-buttons',
        )
        + element('span', '', id='cred-count-status', role='status', aria_live='polite')
        + button('Refresh sensor', variant='secondary', size='s', html_id='cred-refresh-btn')
        + button('Add credential', variant='primary', size='s', icon_name='plus-small', html_id='cred-add-btn'),
        css_class='search-toolbar cred-toolbar',
    )
    headings = ''.join(
        element('th', name, scope='col')
        for name in ('Type', 'Identifier / Template ID', 'Assigned Person', 'Status', 'Enrolled', 'Actions')
    )
    results = element(
        'sbb-table-wrapper',
        element(
            'table',
            element('thead', element('tr', headings)) + element('tbody', '', id='cred-results-list'),
            css_class='sbb-table sbb-table--unstriped',
            aria_label='Credentials',
        ),
        css_class='search-results',
        focusable=True,
    )
    footer = element(
        'footer',
        element('span', 'Loading…', id='cred-count', role='status', aria_live='polite')
        + button('Previous', variant='secondary', size='s', html_id='cred-previous')
        + button('Next', variant='secondary', size='s', html_id='cred-next'),
        css_class='search-footer',
    )

    # Add Credential Dialog
    add_dialog = element(
        'sbb-dialog',
        element('sbb-dialog-title', 'Add credential', id='cred-add-title')
        + element(
            'sbb-dialog-content',
            element('form', '', id='cred-add-form')
            + element('p', '', id='cred-add-error', role='alert', hidden=True),
        )
        + element(
            'sbb-dialog-actions',
            button('Cancel', variant='secondary', size='m', html_id='cred-add-cancel')
            + button('Save', size='m', html_id='cred-add-save'),
        ),
        id='cred-add-dialog',
        backdrop='translucent',
        backdrop_action='none',
    )

    # Edit Credential Dialog
    edit_dialog = element(
        'sbb-dialog',
        element('sbb-dialog-title', 'Edit credential', id='cred-edit-title')
        + element(
            'sbb-dialog-content',
            element('form', '', id='cred-edit-form')
            + element('p', '', id='cred-edit-error', role='alert', hidden=True),
        )
        + element(
            'sbb-dialog-actions',
            button('Cancel', variant='secondary', size='m', html_id='cred-edit-cancel')
            + button('Save', size='m', html_id='cred-edit-save'),
        ),
        id='cred-edit-dialog',
        backdrop='translucent',
        backdrop_action='none',
    )

    # Delete Confirmation Dialog
    confirm_dialog = element(
        'sbb-dialog',
        element('sbb-dialog-title', 'Delete credential?', id='cred-confirm-title')
        + element(
            'sbb-dialog-content',
            element('p', '', id='cred-confirm-text')
            + element('p', '', id='cred-confirm-error', role='alert', hidden=True),
        )
        + element(
            'sbb-dialog-actions',
            button('Cancel', variant='secondary', size='m', html_id='cred-confirm-cancel')
            + button('Delete', size='m', html_id='cred-confirm-delete'),
        ),
        id='cred-confirm-dialog',
        backdrop='translucent',
        backdrop_action='none',
    )

    body = header + query + toolbar + element('p', '', id='cred-error', role='alert', hidden=True) + results + footer + add_dialog + edit_dialog + confirm_dialog
    ui.html(
        element('main', container(body, expanded=True, css_class='admin-panel-shell'), css_class='admin-panel admin-panel--search admin-panel--credentials'),
        sanitize=False,
    ).classes('w-full admin-panel-host')

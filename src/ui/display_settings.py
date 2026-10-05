"""Swiss-designed Display Settings interface for LabAuth.

Allows administrators to customize what is visible on /display and /admin-display
using a visual screen blueprint outline, element toggles (clock, date, greeter,
photos, tools), and draggable grid sizing handles adhering to Swiss design principles.
"""

from __future__ import annotations

import json
from nicegui import ui
import database as db
from ui.admin_display import ADMIN_ICONS_JS


def build_display_settings_page() -> None:
    """Render the full Swiss-design Display Settings page under /admin/display-settings."""
    from ui.display import _color_scheme
    current_theme = _color_scheme()

    # Load initial configurations
    display_cfg = db.get_screen_settings("display")
    admin_cfg = db.get_screen_settings("admin-display")

    ui.add_head_html(f"""
        <link rel="icon" type="image/svg+xml" href="/static/favicon.svg">
        <link rel="stylesheet" href="/static/vendor/sbb-variables.css">
        <link rel="stylesheet" href="/static/vendor/standard-theme.css">
        <link rel="stylesheet" href="/static/display.css?v=37">
        <script>
            (function() {{
                const theme = "{current_theme}";
                document.documentElement.setAttribute('data-theme', theme);
                document.documentElement.style.colorScheme = theme;
                window.INITIAL_CONFIGS = {{
                    "display": {json.dumps(display_cfg)},
                    "admin-display": {json.dumps(admin_cfg)}
                }};
            }})();
            {ADMIN_ICONS_JS}
        </script>
        <script type="module" src="/static/vendor/sbb-elements.bundle.js"></script>
    """)

    markup = f"""
        <main class="admin-panel" data-theme="{current_theme}">
            <sbb-container color="transparent" expanded class="admin-panel-shell">
                <!-- Header: Swiss Title & Controls -->
                <header class="admin-header">
                    <h1 class="admin-heading">Display settings.</h1>
                    <div class="admin-header-controls">
                        <sbb-secondary-button href="/admin" size="m" aria-label="Return to administration">
                            Admin
                        </sbb-secondary-button>
                        <div class="admin-clock-wrapper" aria-label="Analogue clock">
                            <sbb-clock></sbb-clock>
                        </div>
                    </div>
                </header>

                <!-- Settings Container -->
                <div class="display-settings-wrapper">
                    
                    <!-- View Selector: Tabs for display vs admin-display -->
                    <div class="settings-top-bar">
                        <div class="settings-tabs" role="tablist" aria-label="Display screen target">
                            <button type="button" id="tab-target-display" class="settings-tab active" role="tab" aria-selected="true">
                                Public display (/display)
                            </button>
                            <button type="button" id="tab-target-admin" class="settings-tab" role="tab" aria-selected="false">
                                Admin display (/admin-display)
                            </button>
                        </div>

                        <div class="settings-actions-bar">
                            <sbb-secondary-button id="btn-reset-settings" size="s">
                                Reset defaults
                            </sbb-secondary-button>
                            <sbb-button id="btn-save-settings" size="s">
                                Apply settings
                            </sbb-button>
                        </div>
                    </div>

                    <!-- Notification Feedback Toast -->
                    <div id="settings-status-banner" class="settings-status-banner" hidden>
                        <span id="settings-status-text">Settings updated successfully.</span>
                    </div>

                    <!-- Master Toggles: Concise Checkboxes above Blueprint Outline -->
                    <div class="settings-toggles-card">
                        <span class="settings-card-legend">Visibility & Information Density</span>
                        <div class="settings-checkboxes-grid">
                            <label class="settings-checkbox-item">
                                <input type="checkbox" id="chk-greeter" class="sbb-native-check" checked>
                                <span>Greeter text</span>
                            </label>
                            <label class="settings-checkbox-item">
                                <input type="checkbox" id="chk-clock" class="sbb-native-check" checked>
                                <span>Analogue clock</span>
                            </label>
                            <label class="settings-checkbox-item">
                                <input type="checkbox" id="chk-date" class="sbb-native-check" checked>
                                <span>Date</span>
                            </label>
                            <label class="settings-checkbox-item">
                                <input type="checkbox" id="chk-photos" class="sbb-native-check" checked>
                                <span>Card profile photos</span>
                            </label>
                            <label class="settings-checkbox-item">
                                <input type="checkbox" id="chk-tools" class="sbb-native-check" checked>
                                <span>Authorised tool areas</span>
                            </label>
                        </div>
                    </div>

                    <!-- Blueprint: Literally Drawn Screen Outline -->
                    <div class="blueprint-canvas-shell">
                        <div class="blueprint-header-bar">
                            <span class="blueprint-tag">[Screen Outline: 16:9 Screen Space]</span>
                            <span class="blueprint-info" id="blueprint-info-text">Ratio: 70% Cards • Max 3 Sections</span>
                        </div>

                        <!-- 16:9 Aspect Frame Outline -->
                        <div id="blueprint-frame" class="blueprint-frame">
                            
                            <!-- Admin Topbar Outline (Only visible on admin-display) -->
                            <div id="outline-admin-bar" class="outline-box outline-admin-bar" hidden>
                                <span class="outline-label">[Admin Titlebar Chrome] LabAuth + SBB Clock + Admin</span>
                            </div>

                            <!-- Header Zone Outline (Greeter + Clock + Date) -->
                            <div id="outline-header-zone" class="outline-header-zone">
                                <!-- Greeter Outline -->
                                <div id="outline-greeter-box" class="outline-box outline-greeter">
                                    <div class="outline-title-red">[Greeter Outline] "Good morning!"</div>
                                    <div class="outline-desc">"Here’s who is in the lab."</div>
                                </div>

                                <!-- Time / Clock Outline -->
                                <div id="outline-time-box" class="outline-box outline-time">
                                    <div id="outline-date-item" class="outline-date">[Date Outline] October 5, 2026</div>
                                    <div id="outline-clock-item" class="outline-clock">
                                        <div class="outline-clock-disc">Clock</div>
                                        <div class="outline-digital-time">18:49</div>
                                    </div>
                                </div>
                            </div>

                            <!-- Draggable Horizontal Handle (Adjusts proportional grid size) -->
                            <div id="outline-resize-handle" class="outline-drag-handle" title="Drag vertically to adjust grid ratio">
                                <div class="handle-line"></div>
                                <div class="handle-grip">
                                    <span class="handle-icon">↕</span>
                                    <span id="handle-status-text">Horizontal Limit: 3 Rows Max (70%)</span>
                                </div>
                                <div class="handle-line"></div>
                            </div>

                            <!-- Presence Cards Grid Outline -->
                            <div id="outline-grid-zone" class="outline-grid-zone">
                                <div class="outline-grid-header">
                                    <span class="outline-label">[Presence Grid Outline]</span>
                                    <span class="outline-sublabel" id="outline-section-label">3 Row Sections</span>
                                </div>

                                <!-- Sample Card Rows -->
                                <div id="outline-cards-stack" class="outline-cards-stack">
                                    
                                    <!-- Row 1 Cards -->
                                    <div id="outline-row-1" class="outline-card-row">
                                        <div class="outline-card">
                                            <div id="outline-photo-1" class="outline-card-photo">Photo</div>
                                            <div class="outline-card-name">Aisha Khan</div>
                                            <div class="outline-card-time">08:42</div>
                                            <div id="outline-tools-1" class="outline-card-tools">
                                                <span class="outline-tool-chip">Indoor lab</span>
                                            </div>
                                        </div>
                                        <div class="outline-card">
                                            <div id="outline-photo-2" class="outline-card-photo">Photo</div>
                                            <div class="outline-card-name">Rohan Gupta</div>
                                            <div class="outline-card-time">09:16</div>
                                            <div id="outline-tools-2" class="outline-card-tools">
                                                <span class="outline-tool-chip">Indoor lab</span>
                                                <span class="outline-tool-chip">Tool area</span>
                                            </div>
                                        </div>
                                        <div class="outline-card">
                                            <div id="outline-photo-3" class="outline-card-photo">Photo</div>
                                            <div class="outline-card-name">David Kim</div>
                                            <div class="outline-card-time">11:00</div>
                                            <div id="outline-tools-3" class="outline-card-tools">
                                                <span class="outline-tool-chip">Laser cutter</span>
                                            </div>
                                        </div>
                                        <div class="outline-card">
                                            <div id="outline-photo-4" class="outline-card-photo">Photo</div>
                                            <div class="outline-card-name">Elena Rossi</div>
                                            <div class="outline-card-time">11:20</div>
                                            <div id="outline-tools-4" class="outline-card-tools">
                                                <span class="outline-tool-chip">3D printers</span>
                                            </div>
                                        </div>
                                    </div>

                                    <!-- Row 2 Cards -->
                                    <div id="outline-row-2" class="outline-card-row">
                                        <div class="outline-card outline-card--sub">Card 5</div>
                                        <div class="outline-card outline-card--sub">Card 6</div>
                                        <div class="outline-card outline-card--sub">Card 7</div>
                                        <div class="outline-card outline-card--sub">Card 8</div>
                                    </div>

                                    <!-- Row 3 Cards -->
                                    <div id="outline-row-3" class="outline-card-row">
                                        <div class="outline-card outline-card--sub">Card 9</div>
                                        <div class="outline-card outline-card--sub">Card 10</div>
                                        <div class="outline-card outline-card--sub">Card 11</div>
                                        <div class="outline-card outline-card--sub">Card 12</div>
                                    </div>

                                </div>
                            </div>

                        </div>
                    </div>

                    <!-- Footer Guidance -->
                    <div class="settings-footer-info">
                        <p>
                            Swiss Design Guideline: Eliminating unnecessary elements reclaims whitespace and allows denser presence layouts without reducing font legibility.
                        </p>
                    </div>

                </div>
            </sbb-container>
        </main>
    """

    script = """
        function initDisplaySettings() {
            let activeTarget = 'display'; // 'display' or 'admin-display'
            let configs = window.INITIAL_CONFIGS || {
                'display': { show_greeter: true, show_clock: true, show_date: true, show_photos: true, show_tools: true, grid_ratio: 70, max_rows: 3 },
                'admin-display': { show_greeter: true, show_clock: true, show_date: true, show_photos: true, show_tools: true, grid_ratio: 70, max_rows: 3 }
            };

            const tabDisplay = document.querySelector('#tab-target-display');
            const tabAdmin = document.querySelector('#tab-target-admin');
            const btnSave = document.querySelector('#btn-save-settings');
            const btnReset = document.querySelector('#btn-reset-settings');
            const banner = document.querySelector('#settings-status-banner');
            const bannerText = document.querySelector('#settings-status-text');

            const chkGreeter = document.querySelector('#chk-greeter');
            const chkClock = document.querySelector('#chk-clock');
            const chkDate = document.querySelector('#chk-date');
            const chkPhotos = document.querySelector('#chk-photos');
            const chkTools = document.querySelector('#chk-tools');

            const adminBarOutline = document.querySelector('#outline-admin-bar');
            const headerZone = document.querySelector('#outline-header-zone');
            const greeterBox = document.querySelector('#outline-greeter-box');
            const timeBox = document.querySelector('#outline-time-box');
            const dateItem = document.querySelector('#outline-date-item');
            const clockItem = document.querySelector('#outline-clock-item');

            const resizeHandle = document.querySelector('#outline-resize-handle');
            const handleText = document.querySelector('#handle-status-text');
            const gridZone = document.querySelector('#outline-grid-zone');
            const row2 = document.querySelector('#outline-row-2');
            const row3 = document.querySelector('#outline-row-3');
            const sectionLabel = document.querySelector('#outline-section-label');
            const infoText = document.querySelector('#blueprint-info-text');

            if (!tabDisplay || !btnSave || !resizeHandle) {
                window.requestAnimationFrame(initDisplaySettings);
                return;
            }

            // Sync controls with current target config
            function renderUIFromConfig() {
                const cfg = configs[activeTarget];
                chkGreeter.checked = Boolean(cfg.show_greeter);
                chkClock.checked = Boolean(cfg.show_clock);
                chkDate.checked = Boolean(cfg.show_date);
                chkPhotos.checked = Boolean(cfg.show_photos);
                chkTools.checked = Boolean(cfg.show_tools);

                // Admin bar outline
                adminBarOutline.hidden = (activeTarget !== 'admin-display');

                // Header zone outlines
                greeterBox.style.display = cfg.show_greeter ? 'flex' : 'none';
                clockItem.style.display = cfg.show_clock ? 'flex' : 'none';
                dateItem.style.display = cfg.show_date ? 'block' : 'none';

                if (!cfg.show_clock && !cfg.show_date) {
                    timeBox.style.display = 'none';
                } else {
                    timeBox.style.display = 'flex';
                }

                if (!cfg.show_greeter && !cfg.show_clock && !cfg.show_date) {
                    headerZone.style.display = 'none';
                } else {
                    headerZone.style.display = 'grid';
                }

                // Photos & Tools on sample cards
                document.querySelectorAll('.outline-card-photo').forEach(el => {
                    el.style.display = cfg.show_photos ? 'flex' : 'none';
                });
                document.querySelectorAll('.outline-card-tools').forEach(el => {
                    el.style.display = cfg.show_tools ? 'flex' : 'none';
                });

                // Row sections & grid ratio
                const maxRows = Math.max(1, Math.min(3, parseInt(cfg.max_rows || 3, 10)));
                const ratio = Math.max(35, Math.min(85, parseInt(cfg.grid_ratio || 70, 10)));

                if (maxRows === 1) {
                    row2.style.display = 'none';
                    row3.style.display = 'none';
                    sectionLabel.textContent = '1 Row Section (Max 4 Cards)';
                } else if (maxRows === 2) {
                    row2.style.display = 'grid';
                    row3.style.display = 'none';
                    sectionLabel.textContent = '2 Row Sections (Max 8 Cards)';
                } else {
                    row2.style.display = 'grid';
                    row3.style.display = 'grid';
                    sectionLabel.textContent = '3 Row Sections (Max 12 Cards)';
                }

                handleText.textContent = `Horizontal Limit: ${maxRows} Rows Max (${ratio}%)`;
                infoText.textContent = `Ratio: ${ratio}% Cards • Max ${maxRows} Sections`;

                // Adjust flex distribution
                gridZone.style.flex = `${ratio}`;
                if (headerZone.style.display !== 'none') {
                    headerZone.style.flex = `${100 - ratio}`;
                }
            }

            // Target switching
            tabDisplay.addEventListener('click', () => {
                activeTarget = 'display';
                tabDisplay.classList.add('active');
                tabDisplay.setAttribute('aria-selected', 'true');
                tabAdmin.classList.remove('active');
                tabAdmin.setAttribute('aria-selected', 'false');
                renderUIFromConfig();
            });

            tabAdmin.addEventListener('click', () => {
                activeTarget = 'admin-display';
                tabAdmin.classList.add('active');
                tabAdmin.setAttribute('aria-selected', 'true');
                tabDisplay.classList.remove('active');
                tabDisplay.setAttribute('aria-selected', 'false');
                renderUIFromConfig();
            });

            // Checkbox changes update active config
            function onCheckboxChange() {
                const cfg = configs[activeTarget];
                cfg.show_greeter = chkGreeter.checked;
                cfg.show_clock = chkClock.checked;
                cfg.show_date = chkDate.checked;
                cfg.show_photos = chkPhotos.checked;
                cfg.show_tools = chkTools.checked;
                renderUIFromConfig();
            }

            chkGreeter.addEventListener('change', onCheckboxChange);
            chkClock.addEventListener('change', onCheckboxChange);
            chkDate.addEventListener('change', onCheckboxChange);
            chkPhotos.addEventListener('change', onCheckboxChange);
            chkTools.addEventListener('change', onCheckboxChange);

            // Draggable continuous resize handle logic
            let isDragging = false;
            let startY = 0;
            let initialRatio = 70;

            resizeHandle.addEventListener('mousedown', (e) => {
                isDragging = true;
                startY = e.clientY;
                initialRatio = configs[activeTarget].grid_ratio || 70;
                resizeHandle.classList.add('is-dragging');
                document.body.style.cursor = 'ns-resize';
                e.preventDefault();
            });

            // Click handle to step rows
            resizeHandle.addEventListener('dblclick', () => {
                const cfg = configs[activeTarget];
                cfg.max_rows = (cfg.max_rows === 3) ? 2 : (cfg.max_rows === 2 ? 1 : 3);
                renderUIFromConfig();
            });

            window.addEventListener('mousemove', (e) => {
                if (!isDragging) return;
                const deltaY = e.clientY - startY;
                // Dragging down reduces card grid ratio, dragging up increases card grid ratio
                const deltaRatio = Math.round(-deltaY / 3);
                let newRatio = Math.max(35, Math.min(85, initialRatio + deltaRatio));
                
                const cfg = configs[activeTarget];
                cfg.grid_ratio = newRatio;
                // Set max_rows dynamically based on continuous ratio
                if (newRatio >= 65) {
                    cfg.max_rows = 3;
                } else if (newRatio >= 50) {
                    cfg.max_rows = 2;
                } else {
                    cfg.max_rows = 1;
                }
                renderUIFromConfig();
            });

            window.addEventListener('mouseup', () => {
                if (isDragging) {
                    isDragging = false;
                    resizeHandle.classList.remove('is-dragging');
                    document.body.style.cursor = '';
                }
            });

            // Touch support for dragging handle
            resizeHandle.addEventListener('touchstart', (e) => {
                if (e.touches.length === 1) {
                    isDragging = true;
                    startY = e.touches[0].clientY;
                    initialRatio = configs[activeTarget].grid_ratio || 70;
                    resizeHandle.classList.add('is-dragging');
                }
            }, { passive: true });

            window.addEventListener('touchmove', (e) => {
                if (!isDragging || e.touches.length !== 1) return;
                const deltaY = e.touches[0].clientY - startY;
                const deltaRatio = Math.round(-deltaY / 3);
                let newRatio = Math.max(35, Math.min(85, initialRatio + deltaRatio));
                const cfg = configs[activeTarget];
                cfg.grid_ratio = newRatio;
                if (newRatio >= 65) {
                    cfg.max_rows = 3;
                } else if (newRatio >= 50) {
                    cfg.max_rows = 2;
                } else {
                    cfg.max_rows = 1;
                }
                renderUIFromConfig();
            }, { passive: true });

            window.addEventListener('touchend', () => {
                if (isDragging) {
                    isDragging = false;
                    resizeHandle.classList.remove('is-dragging');
                }
            });

            // Save Settings via API
            btnSave.addEventListener('click', async () => {
                try {
                    btnSave.loading = true;
                    const res = await fetch(`/api/settings/display/${activeTarget}`, {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify(configs[activeTarget])
                    });
                    if (res.ok) {
                        const saved = await res.json();
                        configs[activeTarget] = saved.settings;
                        showToast(`Settings for ${activeTarget} saved and broadcast successfully.`);
                    } else {
                        showToast('Error saving settings.', true);
                    }
                } catch (err) {
                    console.error('Save settings error', err);
                    showToast('Failed to connect to server.', true);
                } finally {
                    btnSave.loading = false;
                }
            });

            // Reset Defaults
            btnReset.addEventListener('click', () => {
                configs[activeTarget] = {
                    show_greeter: true,
                    show_clock: true,
                    show_date: true,
                    show_photos: true,
                    show_tools: true,
                    grid_ratio: 70,
                    max_rows: 3
                };
                renderUIFromConfig();
                showToast(`Reset ${activeTarget} to Swiss defaults.`);
            });

            function showToast(msg, isError = false) {
                if (!banner || !bannerText) return;
                bannerText.textContent = msg;
                banner.className = isError ? 'settings-status-banner error' : 'settings-status-banner';
                banner.hidden = false;
                setTimeout(() => {
                    banner.hidden = true;
                }, 3500);
            }

            // Initial render
            renderUIFromConfig();
        }

        initDisplaySettings();
    """

    ui.html(markup, sanitize=False).classes("w-full h-full admin-panel-host")
    ui.add_body_html(f"<script>{script}</script>")

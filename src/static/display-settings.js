// Wait for both NiceGUI's Vue markup and Lyne's property accessors. Assigning
// properties before upgrade can shadow the accessors on a first, uncached load.
await Promise.all(['sbb-checkbox', 'sbb-radio-button-group', 'sbb-radio-button', 'sbb-button', 'sbb-secondary-button'].map(tag => customElements.whenDefined(tag)));
while (!document.querySelector('#settings-apply')) await new Promise(requestAnimationFrame);
const settings = structuredClone(window.SCREEN_SETTINGS);
const defaults = window.SCREEN_DEFAULTS;
const outline = document.querySelector('[data-outline]');
const grid = outline.querySelector('[data-grid]');
const target = document.querySelector('[data-target]');
const apply = document.querySelector('#settings-apply');
const status = document.querySelector('#settings-status');
const dirty = new Set();
let screen = 'display';
let saving = false;
function render() {
  const cfg = settings[screen];
  const hasHeader = cfg.show_greeter || cfg.show_date || cfg.show_clock || cfg.show_digital_time;
  const timeUnits = (cfg.show_date ? 1 : 0) + (cfg.show_clock ? 4 : 0) + (cfg.show_digital_time ? 1 : 0);
  outline.dataset.screen = screen;
  outline.classList.toggle('is-dirty', dirty.has(screen));
  outline.querySelector('.outline-clock-stack').hidden = !timeUnits;
  for (const node of outline.querySelectorAll('[data-part]')) {
    node.hidden = node.dataset.part === 'show_admin_bar' ? screen !== 'admin-display' : !cfg[node.dataset.part];
  }
  for (const node of document.querySelectorAll('[data-setting]')) {
    node.checked = cfg[node.dataset.setting];
    node.disabled = saving;
  }
  const minWidth = cfg.show_photos && cfg.show_tools ? 200 : cfg.show_photos || cfg.show_tools ? 176 : 144;
  const columns = Math.floor(1280 / (minWidth + 12));
  const reserved = (cfg.show_greeter ? columns - 1 : 0) + (timeUnits ? 1 : 0);
  const fullHeader = reserved === columns;
  const rows = Math.max(fullHeader ? 2 : 1, Math.ceil((12 + reserved) / columns));
  grid.style.gridTemplateColumns = `repeat(${columns}, minmax(0, 1fr))`;
  grid.querySelector('.outline-greeter-zone').style.gridColumn = `1 / span ${columns - 1}`;
  grid.querySelector('.outline-clock-stack').style.gridColumn = String(columns);
  const headerShare = hasHeader && rows > 1 ? (fullHeader ? 25 : 100 / rows) : 0;
  const tracks = headerShare ? [headerShare, ...Array(rows - 1).fill((100 - headerShare) / (rows - 1))] : Array(rows).fill(100 / rows);
  grid.style.gridTemplateRows = tracks.map(x => `minmax(0, ${x}fr)`).join(' ');
  document.querySelector("#settings-reset").disabled = saving;
  apply.disabled = saving || !dirty.has(screen);
  target.disabled = saving;
}
function changed() { dirty.add(screen); status.textContent = 'Unsaved changes'; render(); }
for (const node of document.querySelectorAll('[data-setting]')) {
  node.addEventListener('change', () => { settings[screen][node.dataset.setting] = node.checked; changed(); });
}
target.addEventListener('change', () => { screen = target.value; status.textContent = dirty.has(screen) ? 'Unsaved changes' : ''; render(); });
document.querySelector('#settings-reset').addEventListener('click', () => { settings[screen] = structuredClone(defaults); changed(); });
apply.addEventListener('click', async () => {
  const savedScreen = screen;
  saving = true; apply.loading = true; status.textContent = 'Saving…'; render();
  try {
    const response = await fetch('/api/settings/display/' + savedScreen, { method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(settings[savedScreen]) });
    if (!response.ok) throw new Error(response.status === 401 ? 'Sign in again to save.' : 'Could not save. Try again.');
    settings[savedScreen] = (await response.json()).settings;
    dirty.delete(savedScreen); status.textContent = 'Saved';
  } catch (error) { status.textContent = error.message || 'Could not save. Try again.'; }
  finally { saving = false; apply.loading = false; render(); }
});
render();

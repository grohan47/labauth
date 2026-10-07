const esc = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const $ = id => document.getElementById(`logs-${id}`);
const dateFormat = new Intl.DateTimeFormat('en-GB', {day:'2-digit', month:'short', year:'numeric', timeZone:'UTC'});
const stamp = value => {
  if (!value) return '—';
  const date = new Date(value.slice(0, 19) + 'Z');
  if (Number.isNaN(date.valueOf())) return '—';
  return `<div class="logs-stamp"><time datetime="${esc(value)}">${esc(value.slice(11,16))}</time><span>${dateFormat.format(date)}</span></div>`;
};
const duration = seconds => {
  if (seconds == null) return '—';
  const minutes = Math.floor((seconds + .01) / 60);
  return minutes < 60 ? `${minutes} min` : `${Math.floor(minutes / 60)} h ${minutes % 60} min`;
};
let offset = 0, total = 0, rows = [], filters = new URLSearchParams(), controller, debounce, schema = [];
function formFilters() {
  const params = new URLSearchParams();
  document.querySelectorAll('#logs-filters [data-filter]').forEach(n => {
    if (n.value) params.set(n.dataset.filter, n.value);
  });
  return params;
}
function error(message='') { $('error').textContent = message; $('error').hidden = !message; }
async function data(response) {
  if (response.status === 401) { location.assign('/admin-display?login=1'); throw new Error('Admin session expired.'); }
  const result = await response.json();
  if (!response.ok) throw new Error(result.error || 'Could not load logs.');
  return result;
}
function render() {
  $('rows').innerHTML = rows.length ? rows.map((row, index) => {
    const photo = typeof row.photo === 'string' && row.photo.startsWith('/static/portraits/') ? row.photo : '/static/portraits/default.svg';
    const checkout = row.state === 'inside' ? '<span class="logs-inside">Inside now</span>' : row.check_out ? stamp(row.check_out_local) : 'Unknown';
    return `<tr data-state="${esc(row.state)}">
      <td><div class="logs-person"><sbb-image image-src="${esc(photo)}" alt=""></sbb-image><strong>${esc(row.name)}</strong></div></td>
      <td>${stamp(row.check_in_local)}</td><td>${checkout}</td><td>${duration(row.duration_seconds)}</td>
      <td><sbb-transparent-button size="s" data-detail="${index}" aria-label="Visit details for ${esc(row.name)}" sbb-tooltip="${row.source === 'cache' ? 'Live cache · no presence event' : row.state === 'incomplete' ? 'Incomplete record · inspect events' : 'Visit details'}" icon-name="${row.state === 'incomplete' ? 'sign-exclamation-point-small' : 'document-text-small'}"></sbb-transparent-button></td>
    </tr>`;
  }).join('') : '<tr><td colspan="5">No matching visits.</td></tr>';
  $('count').textContent = total ? `${offset+1}–${offset+rows.length} / ${total} visits` : '0 visits';
  $('prev').disabled = offset === 0;
  $('next').disabled = offset + rows.length >= total;
}
async function load() {
  controller?.abort(); controller = new AbortController();
  const requestController = controller;
  $('table').setAttribute('aria-busy', 'true');
  $('export').disabled = true;
  error();
  try {
    const params = new URLSearchParams(filters); params.set('offset', offset);
    const result = await data(await fetch(`/api/logs?${params}`, {signal:requestController.signal}));
    total = result.total; rows = result.rows;
    if (offset >= total && offset > 0) { offset = Math.max(0, Math.ceil(total / 50 - 1) * 50); return load(); }
    render();
    $('zone').textContent = result.timezone;
    for (const key of ['from_date','until_date']) { $('' + key).min = result.date_bounds.min; $('' + key).max = result.date_bounds.max; }
  } catch (e) {
    if (e.name === 'AbortError') return;
    rows=[]; total=0; render(); error(e.message);
  } finally {
    if (controller === requestController) { $('table').removeAttribute('aria-busy'); $('export').disabled=false; }
  }
}
function details(index) {
  const row = rows[index]; if (!row) return;
  const entries = [
    ['Person', row.name], ['User ID', row.user_id], ['Plaksha ID', row.plaksha_id || '—'],
    ['Record', row.source === 'cache' ? 'Live cache · no presence event' : row.state === 'incomplete' ? 'Incomplete' : 'Presence events'],
    ['Check-in event', row.check_in_id || '—'], ['Checkout event', row.check_out_id || '—'],
    ['Check-in', row.check_in ? stamp(row.check_in_local) : 'Unknown'], ['Checkout', row.check_out ? stamp(row.check_out_local) : row.state==='inside' ? 'Inside now' : 'Unknown'],
    ['Entry method', row.method || '—'], ['Exit method', row.out_method || '—'],
    ['Entry device', row.device || '—'], ['Exit device', row.out_device || '—'],
    ['User type now', row.is_temp ? 'Visitor' : 'Member'], ['Account now', row.status],
  ];
  $('detail-content').innerHTML = `<dl class="logs-detail">${entries.map(([label,value]) => `<dt>${label}</dt><dd>${['Check-in','Checkout'].includes(label) ? value : esc(value)}</dd>`).join('')}</dl>`;
  $('detail-dialog').open();
}
async function initialize() {
  await Promise.all(['sbb-select','sbb-dialog','sbb-image','sbb-button','sbb-transparent-button','sbb-table-wrapper','sbb-tooltip'].map(t=>customElements.whenDefined(t)));
  if (!$('filters')) { setTimeout(initialize, 50); return; }
  const initial = new URLSearchParams(location.search);
  document.querySelectorAll('#logs-filters [data-filter]').forEach(n => { if (initial.has(n.dataset.filter)) n.value=initial.get(n.dataset.filter); });
  if ([...document.querySelectorAll('#logs-extra [data-filter]')].some(n=>n.value)) { $('extra').hidden=false; $('more').setAttribute('aria-expanded','true'); }
  // Explain the time bounds only on demand; keep the filter row quiet.
  $('mode').setAttribute('sbb-tooltip', 'Present during includes visits overlapping the continuous From–Until interval. Times without dates use today.');
  $('area').setAttribute('sbb-tooltip', 'Current permission; does not establish use of equipment or historical permission.');
  function applyFilters() {
    clearTimeout(debounce);
    offset=0; filters=formFilters();
    history.replaceState(null, '', location.pathname + (filters.size ? `?${filters}` : ''));
    load();
  }
  $('filters').addEventListener('submit', e => { e.preventDefault(); applyFilters(); });
  $('filters').addEventListener('input', e => {
    if (!e.target.matches('[data-filter]')) return;
    clearTimeout(debounce);
    // Do not show results for an old filter while a newer request is queued.
    controller?.abort(); controller=undefined; $('export').disabled=true;
    debounce=setTimeout(applyFilters, 300);
  });
  $('filters').addEventListener('change', e => { if (e.target.matches('[data-filter]')) applyFilters(); });
  $('more').addEventListener('click', () => { $('extra').hidden=!$('extra').hidden; $('more').setAttribute('aria-expanded', String(!$('extra').hidden)); });
  $('reset').addEventListener('click', () => {
    clearTimeout(debounce);
    document.querySelectorAll('#logs-filters [data-filter]').forEach(n => { n.value=n.dataset.filter==='mode' ? 'present' : ''; });
    offset=0; filters=formFilters(); history.replaceState(null,'',location.pathname); load();
  });
  $('prev').addEventListener('click', () => { offset=Math.max(0, offset-50); load(); });
  $('next').addEventListener('click', () => { offset+=50; load(); });
  $('rows').addEventListener('click', e => { const n=e.target.closest('[data-detail]'); if(n) details(Number(n.dataset.detail)); });
  $('detail-close').addEventListener('click', () => $('detail-dialog').close());
  $('export').addEventListener('click', async () => {
    $('export').disabled=true; error();
    try {
      const response = await fetch(`/api/logs/export?${filters}`);
      if (!response.ok) { await data(response); return; }
      const url=URL.createObjectURL(await response.blob());
      const link=document.createElement('a'); link.href=url; link.download='labauth-visits.csv'; link.click();
      setTimeout(()=>URL.revokeObjectURL(url),1000);
    } catch(e) { error(e.message); } finally { $('export').disabled=false; }
  });
  function showSchema() {
    const table=schema.find(t=>t.name===$('sql_table').value);
    if (!table) return;
    const links=table.foreign_keys;
    $('schema').innerHTML=`<div class="logs-schema-columns">${table.columns.map(c=> {
      const fk=links.filter(f=>f.from===c.name).map(f=>`${f.table}.${f.to || 'PK'}`).join(', ');
      return `<span><strong>${esc(c.name)}</strong> <small>${esc(c.type || 'ANY')}${c.pk?' · PK':''}${fk?' → '+esc(fk):''}</small></span>`;
    }).join('')}</div>`;
  }
  async function refreshSchema() {
    schema=(await data(await fetch('/api/logs/schema'))).tables;
    const selected=$('sql_table').value;
    $('sql_table').innerHTML=schema.map(t=>`<sbb-option value="${esc(t.name)}">${esc(t.name)}</sbb-option>`).join('');
    $('sql_table').value=schema.some(t=>t.name===selected)?selected:'presence_log';
    showSchema();
  }
  $('sql-open').addEventListener('click', async ()=> {
    $('sql-dialog').open();
    try { await refreshSchema(); } catch(e) { $('sql-status').textContent=e.message; }
  });
  $('sql-close').addEventListener('click', ()=>$('sql-dialog').close());
  $('sql_table').addEventListener('change', () => {
    const quoted='"'+$('sql_table').value.replaceAll('"','""')+'"';
    $('query').value=`SELECT * FROM ${quoted} LIMIT 100;`;
    showSchema();
    $('sql-status').textContent=''; $('sql-table').innerHTML='';
  });
  $('sql-run').addEventListener('click', async () => {
    $('sql-run').disabled=true; $('sql-status').textContent='Running…'; $('sql-table').innerHTML='';
    try {
      const result=await data(await fetch('/api/logs/sql', {method:'POST', headers:{'Content-Type':'application/json'},body:JSON.stringify({sql:$('query').value})}));
      $('sql-table').innerHTML=`<thead><tr>${result.columns.map(c=>`<th scope="col">${esc(c)}</th>`).join('')}</tr></thead><tbody>${result.rows.map(r=>`<tr>${r.map(c=>`<td>${esc(c)}</td>`).join('')}</tr>`).join('')}</tbody>`;
      $('sql-status').textContent=`${result.rows.length} rows${result.truncated?' · First 200; refine the query':''}`;
    } catch(e) { $('sql-status').textContent=e.message; } finally { $('sql-run').disabled=false; }
  });
  filters=formFilters(); await load();
  setInterval(() => { if (!document.hidden && $('table').getAttribute('aria-busy') !== 'true' && !$('sql-dialog').isOpen && !$('detail-dialog').isOpen) load(); }, 30000);
  document.addEventListener('visibilitychange', () => { if (!document.hidden) load(); });
}
if(document.readyState==='loading') document.addEventListener('DOMContentLoaded',initialize,{once:true}); else initialize();

const esc = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const $ = name => document.getElementById(`search-${name}`);
const photo = value => typeof value==='string' && value.startsWith('/static/portraits/') ? value : '/static/portraits/default.svg';
let query='', users=[], total=0, controller, detailController, debounce;
function message(value='') { $('error').textContent=value; $('error').hidden=!value; }
async function payload(response) {
  if (response.status===401) { location.assign('/admin-display?login=1'); throw new Error('Admin session expired.'); }
  const result=await response.json();
  if(!response.ok) throw new Error(result.error || 'Could not load users.');
  return result;
}
function render() {
  $('results-list').innerHTML=users.length ? users.map(user=>`
    <sbb-card class="search-user-card" color="transparent-bordered">
      <sbb-card-button data-user-id="${user.id}" aria-label="View ${esc(user.name)}">View ${esc(user.name)}</sbb-card-button>
      <div class="search-identity"><sbb-image class="search-photo" image-src="${esc(photo(user.photo))}" alt=""></sbb-image>
        <div class="search-card-text"><strong>${esc(user.name)}</strong><div class="search-card-ids"><span aria-label="Plaksha ID" title="Plaksha ID">${esc(user.plaksha_id || '—')}</span><span class="search-labauth-id" title="users.id — use this ID in SQL queries">LabAuth #${esc(user.id)}</span></div></div>
      </div>
    </sbb-card>`).join('') : '<p>No matching users.</p>';
  $('count').textContent=`${users.length} / ${total} users`;
  $('more').hidden=users.length>=total;
}
async function load(append=false) {
  controller?.abort(); controller=new AbortController(); const request=controller;
  $('results-list').setAttribute('aria-busy','true'); $('more').disabled=true; message();
  try {
    const result=await payload(await fetch(`/api/users/search?${new URLSearchParams({q:query,limit:30,offset:append?users.length:0})}`,{signal:request.signal}));
    if(controller!==request) return;
    users=append ? [...users,...result.users] : result.users; total=result.total; render();
  } catch(error) {
    if(error.name==='AbortError') return;
    if(controller!==request) return;
    users=[]; total=0; render(); message(error.message);
  } finally {
    if(controller===request) { $('results-list').removeAttribute('aria-busy'); $('more').disabled=false; }
  }
}
function apply() {
  clearTimeout(debounce); query=$('user-input').value.trim();
  history.replaceState(null,'',location.pathname+(query?'?'+new URLSearchParams({q:query}):''));
  load();
}
function profile(user) {
  const time = value => value ? user.time_labels[value] || value : '—';
  const pairs = values => `<dl class="search-details">${values.map(([label,value])=>`<dt>${esc(label)}</dt><dd>${esc(value == null || value === '' ? '—' : value)}</dd>`).join('')}</dl>`;
  const section = (label,body) => `<section class="search-profile-section"><h3>${label}</h3>${body}</section>`;
  $('profile-title').textContent=user.name;
  $('profile-content').innerHTML=`<sbb-image class="search-photo" image-src="${esc(photo(user.photo))}" alt="${esc(user.name)}"></sbb-image>`
    +pairs([
      ['Plaksha ID',user.plaksha_id], ['LabAuth ID',user.id], ['Email',user.email], ['Phone',user.phone],
      ['User type',user.is_temp?'Visitor':'Member'], ['Account',user.status==='inactive'?'Inactive':'Active'],
      ['Presence',user.checked_in_at?'Inside now':'Outside'], ['Checked in',time(user.checked_in_at)],
      ['Registered',time(user.created_at)], ['Updated',time(user.updated_at)],
    ])
    +section('Access',user.access.length ? user.access.map(a=>pairs([
      ['Area',a.label],['Code',a.code],['Area ID',a.id],['Granted',time(a.granted_at)],['Granted by',a.granted_by],
    ])).join('') : '<p>None</p>')
    +section('Credentials',user.credentials.length ? user.credentials.map(c=>pairs([
      ['Method',c.credential_type==='nfc'?'NFC':'Fingerprint'],['Credential ID',c.id],['Identifier',c.identifier],
      ['Status',c.is_active?'Active':'Inactive'],['Enrolled',time(c.enrolled_at)],
      ...(c.credential_type==='fingerprint'?[['Template',c.template_bytes ? `Registered · ${c.template_bytes} bytes`:'No stored template']]:[]),
    ])).join('') : '<p>None</p>')
    +section('Bans',user.bans.length ? user.bans.map(b=>pairs([
      ['Ban ID',b.id], ['Status',b.unbanned_at?'Lifted':'Banned'],['Reason',b.reason],
      ['Banned',time(b.banned_at)],['Banned by',b.banned_by],['Lifted',time(b.unbanned_at)],
    ])).join('') : '<p>None</p>');
}
async function openProfile(id) {
  detailController?.abort(); detailController=new AbortController(); const request=detailController;
  $('profile-title').textContent=users.find(u=>u.id===id)?.name || 'Profile';
  $('profile-content').innerHTML='<p role="status">Loading…</p>'; $('profile-dialog').open();
  try {
    const result=await payload(await fetch(`/api/users/${id}`,{signal:request.signal}));
    if(detailController===request) profile(result.user);
  } catch(error) {
    if(error.name==='AbortError' || detailController!==request) return;
    $('profile-content').innerHTML=`<p role="alert">${esc(error.message)}</p>`;
  }
}
async function initialize() {
  await Promise.all(['sbb-card','sbb-card-button','sbb-image','sbb-dialog','sbb-form-field'].map(t=>customElements.whenDefined(t)));
  while (!$('user-input')) await new Promise(requestAnimationFrame);
  $('user-input').value=new URLSearchParams(location.search).get('q') || '';
  $('user-input').addEventListener('input',()=> {
    clearTimeout(debounce); controller?.abort(); controller=undefined;
    $('results-list').setAttribute('aria-busy','true'); $('more').disabled=true;
    debounce=setTimeout(apply,250);
  });
  $('form').addEventListener('submit',e=>{e.preventDefault();apply();});
  $('more').addEventListener('click',()=>load(true));
  $('results-list').addEventListener('click',e=> {const target=e.target.closest('[data-user-id]');if(target) openProfile(Number(target.dataset.userId));});
  $('profile-close').addEventListener('click',()=>$('profile-dialog').close());
  $('profile-dialog').addEventListener('close',()=> {detailController?.abort();detailController=undefined;});
  apply();
}
initialize();

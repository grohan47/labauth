const esc = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const $ = name => document.getElementById(`search-${name}`);
const photo = value => typeof value==='string' && value.startsWith('/static/portraits/') ? value : '/static/portraits/default.svg';
let query='', users=[], total=0, controller, detailController, debounce, currentUser, editor, confirmation, busy=false;
const selected = new Set();
function message(value='', target='error') { $(target).textContent=value; $(target).hidden=!value; }
async function payload(response) {
  if (response.status===401) { location.assign('/admin-display?login=1'); throw new Error('Admin session expired.'); }
  const result=await response.json();
  if(!response.ok) throw new Error(result.error || result.detail || 'Could not save changes.');
  return result;
}
const api = (path, body, method='PATCH') => fetch(path,{method,headers:{'Content-Type':'application/json'},body:JSON.stringify(body)}).then(payload);
function updateSelection() {
  $('selected').textContent=selected.size ? `${selected.size} selected` : '';
  $('delete').disabled=busy || !selected.size;
  $('select-all').checked=users.length>0 && users.every(u=>selected.has(u.id));
  $('select-all').indeterminate=users.some(u=>selected.has(u.id)) && !$('select-all').checked;
  $('select-all').disabled=busy || !users.length;
  document.querySelectorAll('[data-select-user]').forEach(c=> {c.checked=selected.has(Number(c.dataset.selectUser));c.disabled=busy;});
}
function render() {
  $('results-list').innerHTML=users.length ? users.map(user=>`
    <tr class="search-user-row" data-row-id="${user.id}">
      <td><sbb-checkbox size="s" data-select-user="${user.id}" aria-label="Select ${esc(user.name)}"></sbb-checkbox></td>
      <td><div class="search-identity"><sbb-image class="search-photo" image-src="${esc(photo(user.photo))}" alt=""></sbb-image>
        <sbb-transparent-button size="s" data-user-id="${user.id}" aria-label="View ${esc(user.name)}">${esc(user.name)}</sbb-transparent-button></div></td>
      <td>${esc(user.plaksha_id || '—')}</td><td class="search-labauth-id">${user.id}</td>
    </tr>`).join('') : '<tr><td colspan="4">No matching users.</td></tr>';
  $('count').textContent=`${users.length} / ${total} users`;
  $('more').hidden=users.length>=total; updateSelection();
}
async function load(append=false) {
  controller?.abort(); controller=new AbortController(); const request=controller;
  $('results-list').setAttribute('aria-busy','true'); $('more').disabled=true; message();
  try {
    const result=await payload(await fetch(`/api/users/search?${new URLSearchParams({q:query,limit:100,offset:append?users.length:0})}`,{signal:request.signal}));
    if(controller!==request) return;
    users=append ? [...users,...result.users] : result.users; total=result.total; render();
  } catch(error) {
    if(error.name==='AbortError' || controller!==request) return;
    message(error.message);
  } finally {
    if(controller===request) { $('results-list').removeAttribute('aria-busy'); $('more').disabled=false; }
  }
}
function apply() {
  clearTimeout(debounce); query=$('user-input').value.trim(); selected.clear();
  history.replaceState(null,'',location.pathname+(query?'?'+new URLSearchParams({q:query}):''));
  load();
}
const action = (label, data, icon='pen-small') => `<sbb-transparent-button size="s" icon-name="${icon}" aria-label="${esc(label)}" sbb-tooltip="${esc(label)}" ${data}></sbb-transparent-button>`;
function profile(user) {
  currentUser=user; message('', 'profile-error');
  const time = value => value ? user.time_labels[value] || value : '—';
  const row = (label,value,controls='') => `<div class="search-detail-row"><span class="search-detail-label">${esc(label)}</span><span class="search-detail-value">${esc(value == null || value==='' ? '—':value)}</span><div class="search-entry-actions">${controls}</div></div>`;
  const field = (label,key,value,clear=false) => row(label,value,
    action(`Edit ${label}`,`data-edit-field="${key}"`) + (clear && user[key] ? action(`Delete ${label}`,`data-clear-field="${key}"`,'trash-small'):''));
  const section = (label,body,controls='') => `<section class="search-profile-section"><h3>${esc(label)} ${controls}</h3>${body}</section>`;
  $('profile-title').textContent=user.name;
  $('profile-content').innerHTML=`<sbb-image class="search-photo" image-src="${esc(photo(user.photo))}" alt="${esc(user.name)}"></sbb-image>`
    +row('Photograph','',action('Edit photograph','data-edit-field="photo"')+action('Delete photograph','data-clear-field="photo"','trash-small'))
    +field('Name','name',user.name)+field('Plaksha ID','plaksha_id',user.plaksha_id,true)
    +row('LabAuth ID',user.id)+field('Email','email',user.email,true)+field('Phone','phone',user.phone,true)
    +field('User type','is_temp',user.is_temp?'Visitor':'Member')+field('Account','status',user.status==='inactive'?'Inactive':'Active')
    +row('Presence',user.checked_in_at?'Inside now':'Outside')+row('Checked in',time(user.checked_in_at))
    +row('Registered',time(user.created_at))+row('Updated',time(user.updated_at))
    +section('Access',user.access.length ? user.access.map(a=>`<div class="search-record">${row(a.label,a.code,
      action(`Edit ${a.label}`, 'data-edit-access')+action(`Delete ${a.label}`,`data-delete-access="${a.id}"`,'trash-small'))}${row('Area ID',a.id)}${row('Granted',time(a.granted_at))}${row('Granted by',a.granted_by)}</div>`).join(''):'<p>None</p>',action('Edit access','data-edit-access'))
    +section('Credentials', (user.credentials.length ? user.credentials.map(c=>`<div class="search-record">${row(c.credential_type==='nfc'?'NFC UID':'Fingerprint',c.identifier,
      action('Edit credential',`data-edit-credential="${c.id}"`)+action('Delete credential',`data-delete-credential="${c.id}"`,'trash-small'))}${row('Credential ID',c.id)}${row('Status',c.is_active?'Active':'Inactive')}${row('Enrolled',time(c.enrolled_at))}${c.credential_type==='fingerprint'?row('Template',c.template_bytes?`Registered · ${c.template_bytes} bytes`:'Stored on reader'):''}</div>`).join(''):'<p>None</p>'), action('Add credential', 'data-add-credential', 'plus-small'))
    +section('Bans',user.bans.length ? user.bans.map(b=>`<div class="search-record">${row('Reason',b.reason,action('Edit ban',`data-edit-ban="${b.id}"`)+(!b.unbanned_at?action('Lift ban',`data-lift-ban="${b.id}"`,'trash-small'):''))}${row('Ban ID',b.id)}${row('Status',b.unbanned_at?'Lifted':'Banned')}${row('Banned',time(b.banned_at))}${row('Banned by',b.banned_by)}${row('Lifted',time(b.unbanned_at))}</div>`).join(''):'<p>None</p>');
}
async function openProfile(id) {
  detailController?.abort(); detailController=new AbortController(); const request=detailController;
  currentUser=null; message('', 'profile-error'); $('profile-delete').disabled=true;
  $('profile-title').textContent=users.find(u=>u.id===id)?.name || 'Profile';
  $('profile-content').innerHTML='<p role="status">Loading…</p>'; $('profile-dialog').open();
  try {
    const result=await payload(await fetch(`/api/users/${id}`,{signal:request.signal}));
    if(detailController===request) {profile(result.user);$('profile-delete').disabled=false;}
  } catch(error) {
    if(error.name!=='AbortError' && detailController===request) message(error.message,'profile-error');
  }
}
const input = (label,id,value='',type='text',max=200) => `<sbb-form-field size="m" floating-label><label for="${id}">${esc(label)}</label><input id="${id}" type="${type}" maxlength="${max}" value="${esc(value)}"></sbb-form-field>`;
const select = (label,id,options,value) => `<sbb-form-field size="m" floating-label><label for="${id}">${esc(label)}</label><sbb-select id="${id}" value="${esc(value)}">${options.map(([v,l])=>`<sbb-option value="${esc(v)}" ${String(v)===String(value)?'selected':''}>${esc(l)}</sbb-option>`).join('')}</sbb-select></sbb-form-field>`;
function showEditor(title, html, save) {
  message('', 'edit-error'); $('edit-title').textContent=title; $('edit-form').innerHTML=html;
  editor=save; $('edit-dialog').open();
}
function editField(key) {
  const user=currentUser, labels={name:'Name',plaksha_id:'Plaksha ID',email:'Email',phone:'Phone',photo:'Photograph',status:'Account',is_temp:'User type'};
  let html;
  if(key==='photo') html=input('Photograph','search-edit-value','','file');
  else if(key==='status') html=select('Account','search-edit-value',[['active','Active'],['inactive','Inactive']],user.status);
  else if(key==='is_temp') html=select('User type','search-edit-value',[['false','Member'],['true','Visitor']],String(Boolean(user.is_temp)));
  else html=input(labels[key],'search-edit-value',user[key],key==='email'?'email':key==='phone'?'tel':'text',key==='email'?254:key==='name'?200:100);
  showEditor(`Edit ${labels[key]}`,html,async()=> {
    let value=$('edit-value').value;
    if(key==='photo') {
      const file=$('edit-value').files[0]; if(!file) throw new Error('Choose a photograph');
      if(file.size>8*1024*1024) throw new Error('Choose a photo under 8 MB');
      const bitmap=await createImageBitmap(file); const scale=Math.min(1,1024/Math.max(bitmap.width,bitmap.height));
      const canvas=document.createElement('canvas'); canvas.width=Math.round(bitmap.width*scale);canvas.height=Math.round(bitmap.height*scale);
      canvas.getContext('2d').drawImage(bitmap,0,0,canvas.width,canvas.height);bitmap.close();value=canvas.toDataURL('image/png');
    }
    if(key==='is_temp') value=value==='true';
    return {[key]:value};
  });
  if(key==='photo') $('edit-value').accept='image/*';
}
async function editAccess() {
  try {
    const result=await payload(await fetch('/api/access-areas'));
    showEditor('Edit access',result.access_areas.map(a=>`<sbb-checkbox data-area="${a.id}" ${currentUser.access.some(g=>g.id===a.id)?'checked':''}>${esc(a.label)}</sbb-checkbox>`).join(''),
      ()=>({access_area_ids:[...$('edit-form').querySelectorAll('[data-area]')].filter(c=>c.checked).map(c=>Number(c.dataset.area))}));
  } catch(error) {message(error.message,'profile-error');}
}
function addCredential() {
  showEditor('Add credential',
    select('Credential type','search-cred-type',[['fingerprint','Fingerprint template'],['nfc','NFC Card UID']],'fingerprint')
    +input('Identifier (e.g. template:42 or AABBCCDD)','search-edit-value','','text',100)
    +select('Status','search-edit-active',[['true','Active'],['false','Inactive']],'true'),
    ()=> {
      const typeEl = $('cred-type');
      const kind = typeEl ? typeEl.value : 'fingerprint';
      const idVal = $('edit-value').value.trim();
      const activeVal = $('edit-active') ? $('edit-active').value === 'true' : true;
      if (!idVal) throw new Error('Enter an identifier');
      return {add_credential:{credential_type:kind,identifier:idVal,is_active:activeVal}};
    });
}
function editCredential(id) {
  const c=currentUser.credentials.find(c=>c.id===id);
  showEditor('Edit credential',input(c.credential_type==='nfc'?'NFC UID':'Fingerprint template ID','search-edit-value',c.identifier)
    +select('Status','search-edit-active',[['true','Active'],['false','Inactive']],String(Boolean(c.is_active))),
    ()=>({credential:{id,identifier:$('edit-value').value,is_active:$('edit-active').value==='true'}}));
}
function editBan(id) {
  const b=currentUser.bans.find(b=>b.id===id);
  showEditor('Edit ban',input('Reason','search-edit-value',b.reason,'text',1000)+input('Banned by','search-edit-by',b.banned_by,'text',1000),
    ()=>({ban:{id,reason:$('edit-value').value,banned_by:$('edit-by').value}}));
}
async function change(changes) {
  const result=await api(`/api/users/${currentUser.id}`,changes);profile(result.user);await load();
}
function confirm(title,text,operation) {
  $('confirm-title').textContent=title; $('confirm-text').textContent=text;message('', 'confirm-error');
  confirmation=operation; $('confirm-dialog').open();
}
function deleteUsers(ids) {
  const names=ids.length===1 ? users.find(u=>u.id===ids[0])?.name || currentUser?.name || 'person' : `${ids.length} people`;
  confirm(`Delete ${names}?`,'Access and enrolled credentials will be removed. Attendance history is retained. Keep the fingerprint reader connected.', async()=> {
    await api('/api/users/delete',{user_ids:ids},'POST'); ids.forEach(id=>selected.delete(id));
    if(currentUser && ids.includes(currentUser.id)) { $('profile-dialog').close();currentUser=null; }
    await load();
  });
}
async function initialize() {
  await Promise.all(['sbb-checkbox','sbb-image','sbb-dialog','sbb-form-field','sbb-select','sbb-transparent-button'].map(t=>customElements.whenDefined(t)));
  while (!$('user-input')) await new Promise(requestAnimationFrame);
  $('user-input').value=new URLSearchParams(location.search).get('q') || '';
  $('user-input').addEventListener('input',()=> {clearTimeout(debounce);controller?.abort();controller=undefined;debounce=setTimeout(apply,250);});
  $('form').addEventListener('submit',e=>{e.preventDefault();apply();});
  $('more').addEventListener('click',()=>load(true));
  $('select-all').addEventListener('change',()=>{users.forEach(u=>$('select-all').checked?selected.add(u.id):selected.delete(u.id));updateSelection();});
  $('results-list').addEventListener('change',e=>{const t=e.target.closest('[data-select-user]');if(t) {const id=Number(t.dataset.selectUser);t.checked?selected.add(id):selected.delete(id);updateSelection();}});
  $('results-list').addEventListener('click',e=> {
    if(e.target.closest('sbb-checkbox')) return;
    const row=e.target.closest('[data-row-id]');if(row) openProfile(Number(row.dataset.rowId));
  });
  $('delete').addEventListener('click',()=>deleteUsers([...selected]));
  $('profile-delete').addEventListener('click',()=>currentUser && deleteUsers([currentUser.id]));
  $('profile-close').addEventListener('click',()=>$('profile-dialog').close());
  $('profile-dialog').addEventListener('close',()=> {detailController?.abort();detailController=undefined;});
  $('profile-content').addEventListener('click',e=> {
    if(!currentUser || busy) return;
    const t=e.target.closest('sbb-transparent-button');if(!t) return;const d=t.dataset;
    if(d.editField) editField(d.editField);
    if(d.editAccess!==undefined) editAccess();
    if(d.addCredential!==undefined) addCredential();
    if(d.editCredential) editCredential(Number(d.editCredential));
    if(d.editBan) editBan(Number(d.editBan));
    if(d.clearField) confirm('Delete entry?',`Remove ${d.clearField.replace('_',' ')}?`,()=>change({[d.clearField]:null}));
    if(d.deleteAccess) confirm('Delete access?','Remove this access permission?',()=>change({access_area_ids:currentUser.access.filter(a=>a.id!==Number(d.deleteAccess)).map(a=>a.id)}));
    if(d.deleteCredential) {
      const c=currentUser.credentials.find(c=>c.id===Number(d.deleteCredential));
      confirm('Delete credential?',c.credential_type==='fingerprint'?'Remove this fingerprint from the reader and account? Keep the reader connected.':'Remove this enrolled NFC UID?',()=>change({credential:{id:c.id,delete:true}}));
    }
    if(d.liftBan) confirm('Lift ban?','Restore account access?',()=>change({ban:{id:Number(d.liftBan),lift:true}}));
  });
  $('edit-cancel').addEventListener('click',()=>$('edit-dialog').close());
  $('edit-form').addEventListener('submit',e=>{e.preventDefault();$('edit-save').click();});
  $('edit-save').addEventListener('click',async()=> {
    if(busy || !$('edit-form').reportValidity()) return;
    busy=true;$('edit-save').disabled=true;$('edit-cancel').disabled=true;message('','edit-error');
    try {await change(await editor());$('edit-dialog').close();} catch(error) {message(error.message,'edit-error');}
    finally {busy=false;$('edit-save').disabled=false;$('edit-cancel').disabled=false;updateSelection();}
  });
  $('confirm-cancel').addEventListener('click',()=>$('confirm-dialog').close());
  $('confirm-delete').addEventListener('click',async()=> {
    if(busy) return;busy=true;$('confirm-delete').disabled=true;$('confirm-cancel').disabled=true;
    try {await confirmation();$('confirm-dialog').close();} catch(error) {message(error.message,'confirm-error');}
    finally {busy=false;$('confirm-delete').disabled=false;$('confirm-cancel').disabled=false;updateSelection();}
  });
  apply();
}
initialize();

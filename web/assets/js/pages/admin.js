import { api, apiUrl, qs, store } from '../api.js';
import { applyTheme, go, reloadMe } from '../app.js';
import { $, $$, card, debounce, empty, esc, fail, icon, modal, paintIcons, roleLabel, status, table, timeAgo, toast } from '../ui.js';

const TABS = [['members', 'Members', 'users', 'people.manage'], ['roles', 'Roles & permissions', 'key-round', 'settings.manage'],
  ['sharing', 'Sharing & branding', 'sliders-horizontal', 'settings.manage'], ['departments', 'Departments', 'layers', 'settings.manage'],
  ['import', 'Import data', 'upload', 'data.import'], ['audit', 'Audit log', 'scroll-text', 'audit.view']];

export async function render(el, { parts }) {
  const tabs = TABS.filter((t) => store.can(t[3]));
  const tab = tabs.find((t) => t[0] === parts[1]) ? parts[1] : tabs[0][0];
  el.innerHTML = `<div class="ph"><div class="t"><div class="eyebrow">${esc(store.inst?.name || '')}</div><h1>Admin console</h1>
      <p class="lead">You decide who joins, what each role can do, and how much ${esc(store.inst?.short || 'the institution')} shares with the RICE network.</p></div></div>
    <nav class="tabs">${tabs.map(([k, l, ic]) => `<a href="#/admin/${k}" class="${tab === k ? 'on' : ''}">${icon(ic, 'i-sm')}${l}</a>`).join('')}</nav><div id="pane"></div>`;
  paintIcons(el);
  await ({ members, roles, sharing, departments, import: importer, audit })[tab]($('#pane'));
}

async function members(pane) {
  const st = { q: '', role: '', status: '' };
  pane.innerHTML = `<div class="filters"><span class="row grow" style="flex-wrap:nowrap">${icon('search')}<input class="input sm" id="mq" placeholder="Name or email" style="border:0;box-shadow:none"></span>
      <select class="input sm" id="mr" style="width:auto"><option value="">All roles</option>${Object.keys(store.me.roles).filter((r) => r !== 'platform_admin').map((r) => `<option value="${r}">${esc(roleLabel(r))}</option>`).join('')}</select>
      <select class="input sm" id="ms" style="width:auto"><option value="">Any status</option><option value="active">Active</option><option value="inactive">Deactivated</option><option value="pending">Waiting approval</option></select>
      <button class="btn sm primary" id="invite">${icon('user-plus', 'i-sm')}Add member</button></div><div id="mt"></div>`;
  paintIcons(pane);
  const load = async () => {
    const r = await api(`/api/admin/members${qs(st)}`);
    table($('#mt'), { rows: r.rows, pageSize: 20, columns: [
      { key: 'name', label: 'Member', render: (m) => `<a href="#/people/${m.id}"><b>${esc(m.name)}</b></a><br><span class="muted" style="font-size:12px">${esc(m.email || '')}</span>` },
      { key: 'role', label: 'Role', render: (m) => m.role === 'inst_admin' || m.id === store.me.user.id ? esc(roleLabel(m.role)) :
        `<select class="input sm" data-role="${m.id}" style="width:auto">${Object.keys(store.me.roles).filter((x) => !['platform_admin', 'inst_admin'].includes(x)).map((x) => `<option value="${x}" ${x === m.role ? 'selected' : ''}>${esc(roleLabel(x))}</option>`).join('')}</select>` },
      { key: 'dept', label: 'Dept', render: (m) => `<select class="input sm" data-dept="${m.id}" style="width:auto"><option value="">—</option>${store.me.departments.map((d) => `<option value="${d.id}" ${d.id === m.dept_id ? 'selected' : ''}>${esc(d.code)}</option>`).join('')}</select>` },
      { key: 'status', label: 'Status', render: (m) => status(m.status) },
      { key: 'last_login', label: 'Last sign-in', render: (m) => (m.last_login ? timeAgo(m.last_login) : '<span class="muted">never</span>') },
      { key: 'x', label: '', nosort: true, render: (m) => m.id === store.me.user.id || m.role === 'inst_admin' || m.status === 'pending' ? '' :
        `<button class="btn xs ${m.status === 'active' ? 'bad' : ''}" data-st="${m.id}:${m.status === 'active' ? 'inactive' : 'active'}">${m.status === 'active' ? 'Deactivate' : 'Reactivate'}</button>` }] });
    const patch = async (id, body, msg) => { try { await api(`/api/admin/members/${id}`, { method: 'PATCH', body }); toast(msg); } catch (e) { fail(e); load(); } };
    $('#mt').onchange = (e) => {
      const r1 = e.target.closest('[data-role]'), d1 = e.target.closest('[data-dept]');
      if (r1) patch(r1.dataset.role, { role: r1.value }, 'Role updated — they have been notified');
      if (d1) patch(d1.dataset.dept, { dept_id: d1.value ? +d1.value : null }, 'Department updated');
    };
    $('#mt').onclick = (e) => {
      const b = e.target.closest('[data-st]');
      if (!b) return;
      const [id, s] = b.dataset.st.split(':');
      patch(id, { status: s }, s === 'inactive' ? 'Deactivated — they can no longer sign in' : 'Reactivated').then(load);
    };
  };
  $('#mq').oninput = debounce((e) => { st.q = e.target.value; load(); }, 250);
  $('#mr').onchange = (e) => { st.role = e.target.value; load(); };
  $('#ms').onchange = (e) => { st.status = e.target.value; load(); };
  $('#invite').onclick = () => modal({
    title: 'Add a member',
    body: `<div class="form-grid"><label class="field wide"><span>Full name</span><input class="input" name="name"></label>
      <label class="field wide"><span>Email</span><input class="input" name="email" type="email"></label>
      <label class="field"><span>Role</span><select class="input" name="role">${['faculty', 'hod', 'scholar', 'student', 'staff', 'external'].map((r) => `<option value="${r}">${esc(roleLabel(r))}</option>`).join('')}</select></label>
      <label class="field"><span>Department</span><select class="input" name="dept_id"><option value="">—</option>${store.me.departments.map((d) => `<option value="${d.id}">${esc(d.name)}</option>`).join('')}</select></label>
      <label class="field wide"><span>Designation</span><input class="input" name="designation" placeholder="e.g. Assistant Professor"></label></div>`,
    actions: [{ label: 'Cancel', cls: 'ghost' }, {
      label: 'Add member', cls: 'primary', run: async (ov) => {
        const g = (n) => ov.querySelector(`[name=${n}]`).value.trim();
        const r = await api('/api/admin/members', { method: 'POST', body: { name: g('name'), email: g('email'), role: g('role'), dept_id: g('dept_id') ? +g('dept_id') : null, designation: g('designation') } });
        await modal({ title: 'Member added', body: `<p>${esc(r.message)}</p><pre class="cypher" style="font-size:15px">${esc(r.temp_password)}</pre><p class="muted" style="font-size:13px">Share it privately. They should change it from their account page after signing in.</p>`, actions: [{ label: 'Done', cls: 'primary' }] });
        load();
      },
    }],
  });
  await load();
}

async function roles(pane) {
  const d = await api('/api/admin/settings');
  const roleKeys = Object.keys(d.roles);
  const perms = Object.entries(d.permissions);
  const has = (role, p) => (d.settings.matrix[role] || []).includes(p);
  pane.innerHTML = card('What each role can do', `
    <div class="tbl-wrap"><table class="tbl matrix"><thead><tr><th>Permission</th>${roleKeys.map((r) => `<th>${esc(d.roles[r])}</th>`).join('')}</tr></thead>
    <tbody>${perms.map(([p, info]) => `<tr><td><b>${esc(info.label)}</b><br><span class="muted" style="font-size:12px">${esc(info.help)}</span></td>
      ${roleKeys.map((r) => `<td>${info.locked ? `<span class="muted" title="Only the institution admin can hold this">${icon('lock', 'i-sm')}</span>` : `<input type="checkbox" data-p="${p}" data-r="${r}" ${has(r, p) ? 'checked' : ''} aria-label="${esc(info.label)} for ${esc(d.roles[r])}">`}</td>`).join('')}</tr>`).join('')}</tbody></table></div>
    <div class="row mt"><button class="btn primary" id="save">${icon('save', 'i-sm')}Save permissions</button><span class="muted" style="font-size:12.5px">Locked rows stay with the institution admin. Changes apply the next time each person loads a page.</span></div>`,
    { sub: 'Tick to grant. Institution admins always have everything.' });
  paintIcons(pane);
  $('#save').onclick = async () => {
    const matrix = Object.fromEntries(roleKeys.map((r) => [r, $$(`[data-r="${r}"]:checked`, pane).map((c) => c.dataset.p)]));
    try { await api('/api/admin/settings', { method: 'PUT', body: { matrix } }); toast('Permissions saved'); } catch (e) { fail(e); }
  };
}

async function sharing(pane) {
  const d = await api('/api/admin/settings');
  pane.innerHTML = `<div class="stack">
    ${card('How much to share with the RICE network', `<div class="level">${Object.entries(d.share_levels).map(([k, v]) => `<label><span class="row"><input type="radio" name="lvl" value="${k}" ${d.inst.share_level === k ? 'checked' : ''}><b>${esc(k)}</b></span><span>${esc(v)}</span></label>`).join('')}</div>
      <div class="callout mt">${icon('repeat')}<span>Sharing is reciprocal — you see other institutions at most at the level you share. Individual researchers can still hide their own profile from other institutions.</span></div>`)}
    ${card('Rules', `<div class="stack" style="gap:12px">
      <label class="switch"><input type="checkbox" id="ver" ${d.settings.require_verification ? 'checked' : ''}>New research records need verification by a HoD or the research cell</label>
      <label class="switch"><input type="checkbox" id="sign" ${d.settings.allow_signup ? 'checked' : ''}>People can ask to join from the sign-in page (you still approve each one)</label></div>`)}
    ${card('Branding', `<div class="form-grid"><label class="field"><span>Brand colour</span><span class="row"><input type="color" id="brand" value="${esc(d.inst.brand)}" style="width:52px;height:40px;border:0;background:none"><span class="mono">${esc(d.inst.brand)}</span></span>
      <small>Used for your institution chip and the “Campus colours” theme.</small></label>
      <label class="field"><span>Tagline</span><input class="input" id="tag" value="${esc(d.inst.tagline || '')}"><small>Shown on your public showcase.</small></label></div>`)}
    <div><button class="btn primary" id="save">${icon('save', 'i-sm')}Save changes</button></div></div>`;
  paintIcons(pane);
  $('#save').onclick = async () => {
    try {
      await api('/api/admin/settings', { method: 'PUT', body: { share_level: $('[name=lvl]:checked', pane).value, require_verification: $('#ver').checked,
        allow_signup: $('#sign').checked, brand: $('#brand').value, tagline: $('#tag').value } });
      toast('Saved');
      await reloadMe();
      try { applyTheme(localStorage.getItem('rice.theme') || 'marker'); } catch (e) { /* ignore */ }
      go('#/admin/sharing');
    } catch (e) { fail(e); }
  };
}

async function departments(pane) {
  pane.innerHTML = `<div class="grid g-2-1">${card('Departments', `<div class="list">${store.me.departments.map((d) => `<div class="it"><span class="chip mono">${esc(d.code)}</span><div class="body"><b>${esc(d.name)}</b><div class="meta">${esc(d.field || '')}</div></div>
      <a class="btn xs" href="#/analytics/overview?scope=department&dept=${d.id}">Analytics</a></div>`).join('')}</div>`)}
    ${card('Add a department', `<form id="df" class="stack" style="gap:12px"><label class="field"><span>Code</span><input class="input" name="code" maxlength="8" placeholder="e.g. BME"></label>
      <label class="field"><span>Name</span><input class="input" name="name" placeholder="Biomedical Engineering"></label>
      <label class="field"><span>Field</span><select class="input" name="field">${['Computing', 'Engineering', 'Sciences', 'Life Sciences', 'Management'].map((f) => `<option>${f}</option>`).join('')}</select></label>
      <button class="btn primary">Add department</button></form>`)}</div>`;
  paintIcons(pane);
  $('#df').onsubmit = async (e) => {
    e.preventDefault();
    const f = e.target;
    try { await api('/api/admin/departments', { method: 'POST', body: { code: f.code.value.trim(), name: f.name.value.trim(), field: f.field.value } }); toast('Department added'); await reloadMe(); go('#/admin/departments'); } catch (err) { fail(err); }
  };
}

async function importer(pane) {
  pane.innerHTML = `<div class="grid g-2-1">
    ${card('Upload a file', `<label class="drop" id="drop">${icon('upload-cloud')}<div style="margin-top:8px"><b>Drop an .xlsx or .csv here</b>, or click to choose</div>
        <div class="muted" style="font-size:12.5px;margin-top:4px">RICE recognises a faculty roster, a publication list, or a SciVal researcher export.</div><input type="file" id="file" accept=".xlsx,.csv" hidden></label>
      <div id="preview" class="mt"></div>`)}
    ${card('Templates', `<div class="stack" style="gap:10px">
      <a class="btn" href="${apiUrl('/api/admin/templates/people')}" download>${icon('file-spreadsheet', 'i-sm')}People roster (.csv)</a>
      <a class="btn" href="${apiUrl('/api/admin/templates/publications')}" download>${icon('file-spreadsheet', 'i-sm')}Publications (.csv)</a>
      <div class="muted" style="font-size:13px;line-height:1.5">SciVal: export <i>Researchers</i> with groups (Author, Scopus Author ID, Level 1…). Each group's institution is added to <a href="#/network">Network</a> as a tracked institution with its researcher list.</div>
      <div class="muted" style="font-size:13px;line-height:1.5">Imported people get the temporary password set by the server (RICE_IMPORT_PASSWORD) and should change it at first sign-in.</div></div>`)}</div>`;
  paintIcons(pane);
  const drop = $('#drop'), input = $('#file');
  let file = null;
  const preview = async (commit) => {
    const fd = new FormData();
    fd.append('file', file);
    fd.append('commit', commit ? 'true' : 'false');
    const out = $('#preview');
    out.innerHTML = '<div class="skel" style="height:120px"></div>';
    try {
      const r = await api('/api/admin/import', { method: 'POST', form: fd });
      const rows = r.preview || [];
      out.innerHTML = `<div class="callout ${r.errors?.length ? 'warn' : ''}">${icon(commit ? 'check-circle-2' : 'file-search')}<span>
          <b>${esc({ scival: 'SciVal researcher export', people: 'People roster', publications: 'Publication list' }[r.format])}</b> —
          ${r.format === 'scival' ? `${r.institutions} institutions, ${r.people} researchers` : `${r.valid} of ${r.rows} rows ready`}
          ${commit ? ` · <b>imported${r.created !== undefined ? ` ${r.created}` : ''}</b>` : ''}</span></div>
        ${rows.length ? `<div class="tbl-wrap mt"><table class="tbl"><thead><tr>${Object.keys(rows[0]).map((k) => `<th>${esc(k)}</th>`).join('')}</tr></thead><tbody>${rows.map((x) => `<tr>${Object.values(x).map((v) => `<td>${esc(v)}</td>`).join('')}</tr>`).join('')}</tbody></table></div>` : ''}
        ${r.errors?.length ? `<details class="mt"><summary>${r.errors.length} rows need attention</summary><ul>${r.errors.map((e) => `<li>${esc(e)}</li>`).join('')}</ul></details>` : ''}
        ${commit ? '' : `<div class="row mt"><button class="btn primary" id="commit">${icon('check', 'i-sm')}Import ${r.format === 'scival' ? r.people : r.valid} rows</button><button class="btn ghost" id="cancel">Cancel</button></div>`}`;
      paintIcons(out);
      $('#commit')?.addEventListener('click', () => preview(true));
      $('#cancel')?.addEventListener('click', () => { out.innerHTML = ''; });
      if (commit) toast('Import finished');
    } catch (e) { out.innerHTML = `<div class="callout warn">${icon('alert-triangle')}<span>${esc(e.message)}</span></div>`; paintIcons(out); }
  };
  input.onchange = () => { file = input.files[0]; if (file) preview(false); };
  drop.ondragover = (e) => { e.preventDefault(); drop.classList.add('over'); };
  drop.ondragleave = () => drop.classList.remove('over');
  drop.ondrop = (e) => { e.preventDefault(); drop.classList.remove('over'); file = e.dataTransfer.files[0]; if (file) preview(false); };
}

async function audit(pane) {
  const r = await api('/api/admin/audit');
  pane.innerHTML = card('Who changed what', '<div id="at"></div>', { sub: 'The last 200 changes made by members of this institution.' });
  table($('#at'), { rows: r.rows, pageSize: 25, columns: [
    { key: 'created_at', label: 'When', render: (x) => `<span class="nowrap">${timeAgo(x.created_at)}</span>` }, { key: 'actor', label: 'Who' },
    { key: 'action', label: 'Action', render: (x) => `<span class="chip mono">${esc(x.action)}</span>` }, { key: 'target', label: 'What' }, { key: 'detail', label: 'Detail' }] });
  if (!r.rows.length) pane.innerHTML = empty('No changes recorded yet', '', 'scroll-text');
}

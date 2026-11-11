import { api, store } from '../api.js';
import { applyTheme, reloadMe, go, THEMES } from '../app.js';
import { $, $$, avatar, card, esc, fail, icon, paintIcons, toast } from '../ui.js';

export async function render(el) {
  const u = store.me.user;
  let interests = [...u.interests];
  el.innerHTML = `<div class="ph"><div class="t"><div class="eyebrow">Your account</div><h1>Profile & preferences</h1>
      <p class="lead">Your interests drive expert search and collaborator suggestions. Your institution admin controls your role and department.</p></div>
      <div class="acts"><a class="btn" href="#/people/${u.id}">${icon('user')}View my profile</a></div></div>
    <div class="grid g-3-2">
      <div class="stack">
        ${card('Research profile', `<form id="pf" class="form-grid">
          <div class="wide row">${avatar(u, 'lg')}<div><b style="font-size:17px">${esc(u.name)}</b><div class="muted">${esc(u.role_label)}${u.dept ? ` · ${esc(u.dept)}` : ''} · ${esc(store.inst?.name || '')}</div><div class="muted" style="font-size:12.5px">${esc(u.email || '')}</div></div></div>
          <label class="field"><span>Designation</span><input class="input" name="designation" value="${esc(u.designation || '')}"></label>
          <label class="field"><span>Profile visibility</span><select class="input" name="visibility"><option value="network" ${u.visibility === 'network' ? 'selected' : ''}>RICE network (if my institution shares)</option><option value="internal" ${u.visibility === 'internal' ? 'selected' : ''}>My institution only</option></select></label>
          <div class="field wide"><span>Research interests</span><div class="chips" id="ints"></div>
            <input class="input mt" id="int-in" list="topic-list" placeholder="Add a topic and press Enter" style="margin-top:8px"><datalist id="topic-list">${store.me.topics.map((t) => `<option value="${esc(t)}">`).join('')}</datalist></div>
          <label class="field wide"><span>Short bio</span><textarea class="input" name="bio">${esc(u.bio || '')}</textarea></label>
          <label class="field"><span>ORCID iD</span><input class="input" name="orcid" value="${esc(u.orcid || '')}" placeholder="0000-0002-1825-0097"><small>Lets you import your works from OpenAlex.</small></label>
          <label class="field"><span>Scopus author ID</span><input class="input" name="scopus_id" value="${esc(u.scopus_id || '')}"></label>
          <div class="wide"><button class="btn primary">${icon('save', 'i-sm')}Save profile</button></div></form>`)}
      </div>
      <div class="stack">
        ${card('Theme', `<div class="grid g2" style="gap:8px">${THEMES.map((t) => `<button class="persona" data-th="${t.key}"><span class="swatch" style="background:${t.sw || store.inst?.brand || '#2B59FF'}"></span><span><b>${t.name}</b><span>${t.key === 'campus' ? `Your institution's colour` : 'Bright'}</span></span></button>`).join('')}</div>`)}
        ${card('Password', `<form id="pw" class="stack" style="gap:10px"><label class="field"><span>Current password</span><input class="input" type="password" name="current" autocomplete="current-password"></label>
          <label class="field"><span>New password</span><input class="input" type="password" name="new" minlength="8" autocomplete="new-password"><small>At least 8 characters.</small></label>
          <button class="btn">Change password</button></form>`)}
        ${card('Your permissions', `<div class="chips">${store.me.perms.map((p) => `<span class="chip">${esc(store.me.permissions[p]?.label || p)}</span>`).join('')}</div>`, { sub: 'Set by your institution admin for your role.' })}
      </div></div>`;
  paintIcons(el);
  const drawInts = () => {
    $('#ints').innerHTML = interests.map((t, i) => `<span class="chip acc">${esc(t)}<button type="button" data-rm="${i}" aria-label="Remove ${esc(t)}" style="border:0;background:none;cursor:pointer;padding:0;color:inherit">×</button></span>`).join('') || '<span class="muted">No interests yet</span>';
    $$('[data-rm]', el).forEach((b) => b.onclick = () => { interests.splice(+b.dataset.rm, 1); drawInts(); });
  };
  drawInts();
  $('#int-in').onkeydown = (e) => {
    if (e.key !== 'Enter') return;
    e.preventDefault();
    const v = e.target.value.trim();
    if (v && !interests.includes(v) && interests.length < 10) { interests.push(v); drawInts(); }
    e.target.value = '';
  };
  $('#pf').onsubmit = async (e) => {
    e.preventDefault();
    const f = e.target;
    try {
      await api('/api/me', { method: 'PATCH', body: { designation: f.designation.value.trim(), visibility: f.visibility.value, interests, bio: f.bio.value.trim(), orcid: f.orcid.value.trim() || null, scopus_id: f.scopus_id.value.trim() || null } });
      toast('Profile saved');
      await reloadMe();
      go('#/account');
    } catch (err) { fail(err); }
  };
  $('#pw').onsubmit = async (e) => {
    e.preventDefault();
    try { await api('/api/me/password', { method: 'POST', body: { current: e.target.current.value, new: e.target.new.value } }); toast('Password changed'); e.target.reset(); } catch (err) { fail(err); }
  };
  $$('[data-th]', el).forEach((b) => b.onclick = () => { applyTheme(b.dataset.th); toast('Theme applied'); });
}

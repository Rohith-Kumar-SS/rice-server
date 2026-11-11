import { api, store } from '../api.js';
import { $, $$, card, crore, empty, esc, fail, icon, paintIcons, roleLabel, timeAgo, toast, who } from '../ui.js';

export async function render(el, { query, refreshCounts }) {
  let tab = query.tab || 'records';
  const draw = async () => {
    const d = await api('/api/admin/approvals');
    const tabs = [
      store.can('outputs.verify') && ['records', 'Research records', d.records.length],
      store.can('people.manage') && ['members', 'Member requests', d.members.length],
      store.can('people.manage') && ['posts', 'Network posts', d.opportunities.length],
      ['collab', 'Collaboration requests', d.collab.length],
    ].filter(Boolean);
    if (!tabs.find((t) => t[0] === tab)) tab = tabs[0][0];
    el.innerHTML = `<div class="ph"><div class="t"><div class="eyebrow">${esc(store.inst?.name || '')}</div><h1>Approvals</h1>
        <p class="lead">${store.me.user.role === 'hod' ? 'Records from your department wait here until you verify them.' : 'Everything that needs a decision from the institution, in one queue.'}</p></div></div>
      <nav class="tabs">${tabs.map(([k, l, n]) => `<a href="javascript:void 0" data-t="${k}" class="${tab === k ? 'on' : ''}">${l} ${n ? `<span class="badge">${n}</span>` : '<span class="badge n">0</span>'}</a>`).join('')}</nav>
      <div id="pane"></div>`;
    paintIcons(el);
    $$('[data-t]', el).forEach((b) => b.onclick = () => { tab = b.dataset.t; draw(); });
    const pane = $('#pane');
    if (tab === 'records') {
      pane.innerHTML = d.records.length ? card(`${d.records.length} records waiting`, `
        <div class="row mb"><label class="check"><input type="checkbox" id="all">Select all</label><button class="btn sm good" id="bulk-ok">${icon('check-check', 'i-sm')}Verify selected</button></div>
        <div class="list">${d.records.map((r) => `<div class="it"><input type="checkbox" data-sel="${r.entity}:${r.id}" style="margin-top:4px;width:17px;height:17px;accent-color:var(--accent)">
          <div class="body"><div class="ttl">${esc(r.title)}</div>
          <div class="meta"><span class="chip">${esc(r.entity)}</span><span>${esc(r.venue || '')}</span><span>${r.year || ''}</span>${r.amount ? `<b>${crore(r.amount)}</b>` : ''}<span>${esc(r.depts.join(', '))}</span></div>
          <div class="meta">Added by ${esc(r.by)} · authors ${esc(r.people.join(', '))}</div></div>
          <div class="row" style="flex-wrap:nowrap"><button class="btn xs good" data-v="${r.entity}:${r.id}:verified">Verify</button><button class="btn xs bad" data-v="${r.entity}:${r.id}:rejected">Return</button></div></div>`).join('')}</div>`)
        : empty('Nothing to verify', 'New records from your scope appear here.', 'badge-check');
    } else if (tab === 'members') {
      pane.innerHTML = d.members.length ? `<div class="grid g2">${d.members.map((m) => `<section class="card"><div class="bd" style="padding:18px">
          ${who({ ...m, id: null }, { link: false, sub: `${m.email} · asked ${timeAgo(m.created_at)}` })}
          <div class="chips mt">${m.interests.map((t) => `<span class="chip">${esc(t)}</span>`).join('')}</div>
          <div class="form-grid mt"><label class="field"><span>Role</span><select class="input sm" data-role="${m.id}">${['faculty', 'scholar', 'student', 'staff', 'hod', 'external'].map((r) => `<option value="${r}" ${r === m.role ? 'selected' : ''}>${esc(roleLabel(r))}</option>`).join('')}</select></label>
          <label class="field"><span>Department</span><select class="input sm" data-dept="${m.id}">${store.me.departments.map((x) => `<option value="${x.id}" ${x.id === m.dept_id ? 'selected' : ''}>${esc(x.name)}</option>`).join('')}</select></label></div>
          <div class="row mt"><button class="btn sm good" data-ok="${m.id}">${icon('user-check', 'i-sm')}Approve</button><button class="btn sm bad" data-no="${m.id}">Decline</button></div></div></section>`).join('')}</div>`
        : empty('No one is waiting to join', 'People who ask to join from the sign-in page appear here.', 'user-plus');
    } else if (tab === 'posts') {
      pane.innerHTML = d.opportunities.length ? `<div class="list card" style="padding:6px 18px">${d.opportunities.map((o) => `<div class="it"><div class="body"><div class="ttl">${esc(o.title)}</div>
          <div class="meta"><span>${esc(o.poster || '')}</span><span>deadline ${esc(o.deadline)}</span></div><p class="soft" style="margin:6px 0 0">${esc(o.body || '')}</p></div>
          <div class="row" style="flex-wrap:nowrap"><button class="btn xs good" data-post="${o.id}:open">Publish to network</button><button class="btn xs bad" data-post="${o.id}:closed">Decline</button></div></div>`).join('')}</div>`
        : empty('No posts waiting', 'Faculty posts meant for the whole network appear here first.', 'megaphone');
    } else {
      pane.innerHTML = d.collab.length ? `<div class="list card" style="padding:6px 18px">${d.collab.map((r) => `<div class="it"><div class="body">${who(r.other)}<p style="margin:8px 0 0">${esc(r.message)}</p>
          <div class="meta"><span class="chip acc">${esc(r.topic || 'General')}</span><span>${timeAgo(r.created_at)}</span></div></div>
          <div class="row" style="flex-wrap:nowrap"><button class="btn xs good" data-acc="${r.id}">Accept</button><button class="btn xs bad" data-dec="${r.id}">Decline</button></div></div>`).join('')}</div>`
        : empty('No collaboration requests for you', '', 'handshake');
    }
    paintIcons(pane);
    const after = (msg) => { toast(msg); refreshCounts?.(); draw(); };
    $$('[data-v]', pane).forEach((b) => b.onclick = async () => {
      const [entity, id, decision] = b.dataset.v.split(':');
      try { await api(`/api/verify/${entity}/${id}`, { method: 'POST', body: { decision } }); after(decision === 'verified' ? 'Verified' : 'Returned to the author'); } catch (e) { fail(e); }
    });
    $('#all')?.addEventListener('change', (e) => $$('[data-sel]', pane).forEach((c) => { c.checked = e.target.checked; }));
    $('#bulk-ok')?.addEventListener('click', async () => {
      const items = $$('[data-sel]:checked', pane).map((c) => { const [entity, id] = c.dataset.sel.split(':'); return { entity, id: +id }; });
      if (!items.length) return toast('Tick the records to verify first', 'err');
      try { const r = await api('/api/verify-bulk', { method: 'POST', body: { items, decision: 'verified' } }); after(`Verified ${r.done} records`); } catch (e) { fail(e); }
    });
    $$('[data-ok],[data-no]', pane).forEach((b) => b.onclick = async () => {
      const id = b.dataset.ok || b.dataset.no;
      const approve = !!b.dataset.ok;
      try {
        await api(`/api/admin/members/${id}/decision`, { method: 'POST', body: { approve, role: $(`[data-role="${id}"]`).value, dept_id: +$(`[data-dept="${id}"]`).value } });
        after(approve ? 'Approved — they can sign in now' : 'Declined');
      } catch (e) { fail(e); }
    });
    $$('[data-post]', pane).forEach((b) => b.onclick = async () => {
      const [id, s] = b.dataset.post.split(':');
      try { await api(`/api/opportunities/${id}/status`, { method: 'POST', body: { status: s } }); after(s === 'open' ? 'Published to the network' : 'Declined'); } catch (e) { fail(e); }
    });
    $$('[data-acc],[data-dec]', pane).forEach((b) => b.onclick = async () => {
      try { await api(`/api/collab/${b.dataset.acc || b.dataset.dec}/respond`, { method: 'POST', body: { accept: !!b.dataset.acc } }); after(b.dataset.acc ? 'Accepted' : 'Declined'); } catch (e) { fail(e); }
    });
  };
  await draw();
}

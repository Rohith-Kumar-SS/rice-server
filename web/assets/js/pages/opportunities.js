import { api, store } from '../api.js';
import { $, $$, daysLeft, empty, esc, fail, fmtDate, icon, modal, paintIcons, timeAgo, toast } from '../ui.js';

const KIND = { call: ['Funding call', 'landmark'], position: ['Opening', 'briefcase'], collab: ['Collaboration ask', 'handshake'], event: ['Event', 'calendar'] };

export async function render(el) {
  let filter = '';
  const draw = async () => {
    const r = await api('/api/opportunities');
    const rows = r.rows.filter((o) => !filter || o.kind === filter).sort((a, b) => (b.match - a.match) || a.deadline.localeCompare(b.deadline));
    el.innerHTML = `<div class="ph"><div class="t"><div class="eyebrow">Opportunities</div><h1>Calls, openings and asks</h1>
        <p class="lead">Internal posts are visible to ${esc(store.inst?.short || 'your institution')}; network posts reach every RICE institution that shares with you. Posts matching your interests come first.</p></div>
        <div class="acts">${r.can_post ? `<button class="btn primary" id="post">${icon('plus')}Post an opportunity</button>` : ''}</div></div>
      <div class="chips mb"><button class="chip ${filter ? '' : 'on'}" data-f="">All · ${r.rows.length}</button>${Object.entries(KIND).map(([k, [l]]) => `<button class="chip ${filter === k ? 'on' : ''}" data-f="${k}">${l} · ${r.rows.filter((o) => o.kind === k).length}</button>`).join('')}</div>
      ${rows.length ? `<div class="grid g2">${rows.map((o) => {
        const dl = daysLeft(o.deadline);
        return `<section class="card"><div class="bd" style="padding:18px;display:flex;flex-direction:column;gap:10px">
          <div class="row between"><span class="chip acc">${icon(KIND[o.kind][1], 'i-sm')}${KIND[o.kind][0]}</span>
            <span class="row" style="gap:6px">${o.status === 'pending' ? '<span class="st pending">awaiting approval</span>' : ''}${o.status === 'closed' ? '<span class="st closed">closed</span>' : ''}
            <span class="chip" title="${fmtDate(o.deadline)}">${dl < 0 ? 'Closed' : dl === 0 ? 'Due today' : `${dl} days left`}</span></span></div>
          <div style="font:600 17px/1.35 var(--f-display);letter-spacing:-.01em">${esc(o.title)}</div>
          <p class="soft" style="margin:0">${esc(o.body || '')}</p>
          <div class="chips">${o.tags.map((t) => `<span class="chip ${store.me.user.interests.includes(t) ? 'acc' : ''}">${esc(t)}</span>`).join('')}</div>
          <div class="row between" style="margin-top:4px"><span class="muted" style="font-size:12.5px"><span class="swatch" style="display:inline-block;vertical-align:-3px;width:12px;height:12px;border-radius:4px;background:${esc(o.brand || '#ccc')}"></span>
            ${esc(o.inst_name)} · ${esc(o.poster || '')} · ${o.audience === 'network' ? 'Network' : 'Internal'} · ${timeAgo(o.created_at)}</span>
            <span class="row">${o.interested ? `<span class="muted" style="font-size:12.5px">${o.interested} interested</span>` : ''}
              ${o.status === 'open' && !(o.own && o.posted_by === store.me.user.id) ? `<button class="btn sm ${o.mine ? '' : 'primary'}" data-int="${o.id}">${o.mine ? `${icon('check', 'i-sm')}Interested` : "I'm interested"}</button>` : ''}
              ${o.own && (o.posted_by === store.me.user.id || store.can('people.manage')) && o.status !== 'pending' ? `<button class="btn sm ghost" data-close="${o.id}:${o.status === 'open' ? 'closed' : 'open'}">${o.status === 'open' ? 'Close' : 'Reopen'}</button>` : ''}</span></div>
        </div></section>`; }).join('')}</div>` : empty('Nothing posted here yet', r.can_post ? 'Post a call, an opening or a collaboration ask.' : '', 'megaphone')}`;
    paintIcons(el);
    $$('[data-f]', el).forEach((b) => b.onclick = () => { filter = b.dataset.f; draw(); });
    $$('[data-int]', el).forEach((b) => b.onclick = async () => {
      try { const x = await api(`/api/opportunities/${b.dataset.int}/interest`, { method: 'POST', body: {} }); toast(x.interested ? 'The poster has been told you are interested' : 'Interest withdrawn'); draw(); } catch (e) { fail(e); }
    });
    $$('[data-close]', el).forEach((b) => b.onclick = async () => {
      const [id, s] = b.dataset.close.split(':');
      try { await api(`/api/opportunities/${id}/status`, { method: 'POST', body: { status: s } }); draw(); } catch (e) { fail(e); }
    });
    $('#post')?.addEventListener('click', post);
  };
  const post = () => modal({
    title: 'Post an opportunity',
    body: `<div class="form-grid">
      <label class="field"><span>Type</span><select class="input" name="kind">${Object.entries(KIND).map(([k, [l]]) => `<option value="${k}">${l}</option>`).join('')}</select></label>
      <label class="field"><span>Deadline</span><input class="input" type="date" name="deadline" value="${new Date(Date.now() + 30 * 864e5).toISOString().slice(0, 10)}"></label>
      <label class="field wide"><span>Title</span><input class="input" name="title"></label>
      <label class="field wide"><span>Details</span><textarea class="input" name="body"></textarea></label>
      <label class="field wide"><span>Topics</span><input class="input" name="tags" placeholder="Separate with semicolons — people with these interests see it first"></label>
      <label class="field wide"><span>Who can see it</span><select class="input" name="audience"><option value="internal">${esc(store.inst?.short || 'My institution')} only</option><option value="network">RICE network (needs admin approval)</option></select></label></div>`,
    actions: [{ label: 'Cancel', cls: 'ghost' }, {
      label: 'Post', cls: 'primary', run: async (ov) => {
        const g = (n) => ov.querySelector(`[name=${n}]`).value.trim();
        const r = await api('/api/opportunities', { method: 'POST', body: { kind: g('kind'), deadline: g('deadline'), title: g('title'), body: g('body'),
          tags: g('tags').split(';').map((x) => x.trim()).filter(Boolean), audience: g('audience') } });
        toast(r.message);
        draw();
      },
    }],
  });
  await draw();
}

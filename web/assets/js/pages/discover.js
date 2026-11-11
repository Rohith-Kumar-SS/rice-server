import { api, qs, store } from '../api.js';
import { $, $$, avatar, card, empty, esc, fail, icon, paintIcons } from '../ui.js';
import { requestCollab } from './collaborate.js';

const EXAMPLES = ['Federated Learning', 'Battery Management Systems', 'Remote Sensing & GIS', 'Post-Quantum Cryptography', 'Drug Discovery', 'Supply Chain Analytics'];

export async function render(el, { parts, query }) {
  const tab = parts[1] || (query.q ? 'experts' : 'experts');
  const researcher = !['external', 'platform_admin', 'inst_admin', 'staff'].includes(store.me.user.role);
  el.innerHTML = `
    <div class="ph"><div class="t"><div class="eyebrow">Discover</div><h1>Find the right people</h1>
      <p class="lead">Search expertise across ${esc(store.inst?.short || 'your institution')}${store.can('graph.network') ? ' and the RICE institutions that share with it' : ''}. Matches are explained, never a black box.</p></div>
      <span class="engine ${store.me.graph_engine?.engine === 'neo4j' ? '' : 'off'}"><span class="dot"></span>${esc(store.me.graph_engine?.label || '')}</span></div>
    <nav class="tabs">
      <a href="#/discover/experts" class="${tab === 'experts' ? 'on' : ''}">${icon('radar', 'i-sm')}Expert finder</a>
      ${researcher ? `<a href="#/discover/suggested" class="${tab === 'suggested' ? 'on' : ''}">${icon('sparkles', 'i-sm')}Suggested for you</a>` : ''}
      <a href="#/discover/team" class="${tab === 'team' ? 'on' : ''}">${icon('users-round', 'i-sm')}Build a proposal team</a>
    </nav><div id="pane"></div>`;
  paintIcons(el);
  const pane = $('#pane');
  if (tab === 'suggested') return suggested(pane);
  if (tab === 'team') return team(pane);
  return experts(pane, query.q || '');
}

function personCard(p, extra = '') {
  return `<div class="pcard" style="cursor:default">
    <div class="row between" style="flex-wrap:nowrap;align-items:flex-start"><a class="who" href="${p.external_inst ? '#/network/' + p.inst_id : '#/people/' + p.id}">${avatar(p)}<span style="min-width:0"><span class="nm">${esc(p.name)}</span><br>
      <span class="ds">${esc(p.designation || '')} · ${esc(p.dept)} · ${esc(p.inst)}</span></span></a>${p.match !== undefined ? `<span class="match" title="Relative match">${p.match}%</span>` : p.score !== undefined ? `<span class="match" title="Match score">${p.score}</span>` : ''}</div>
    ${p.external_inst ? `<div class="chip" style="align-self:flex-start">${icon('radar', 'i-sm')}Tracked externally${p.scopus_id ? ` · <a href="https://www.scopus.com/authid/detail.uri?authorId=${esc(p.scopus_id)}" target="_blank" rel="noopener">Scopus</a>` : ''}</div>` : ''}
    <div class="chips">${(p.matched?.length ? p.matched : p.interests || []).slice(0, 4).map((t) => `<span class="chip ${p.matched?.includes(t) ? 'acc' : ''}">${esc(t)}</span>`).join('')}</div>
    ${p.pubs !== undefined && !p.external_inst ? `<div class="stats"><span><b>${p.pubs}</b>papers</span><span><b>${p.citations}</b>cites</span><span><b>${p.h_index}</b>h-index</span></div>` : ''}
    ${extra}</div>`;
}

async function experts(pane, q) {
  pane.innerHTML = `<form id="ef" class="filters" style="padding:14px"><span class="row grow" style="flex-wrap:nowrap">${icon('search')}
      <input class="input" name="q" value="${esc(q)}" placeholder="A topic, method or problem — e.g. “battery health with machine learning”" style="border:0;box-shadow:none;height:36px"></span>
      ${store.can('graph.network') ? `<div class="seg"><button type="button" data-s="network" class="on">RICE network</button><button type="button" data-s="institution">${esc(store.inst?.short || 'Mine')}</button></div>` : ''}
      <button class="btn primary">Search</button></form>
    <div class="chips mb">${EXAMPLES.map((t) => `<a class="chip" href="#/discover/experts?q=${encodeURIComponent(t)}">${esc(t)}</a>`).join('')}</div>
    <div id="res"></div>`;
  paintIcons(pane);
  let scope = 'network';
  $$('[data-s]', pane).forEach((b) => b.onclick = () => { scope = b.dataset.s; $$('[data-s]', pane).forEach((x) => x.classList.toggle('on', x === b)); run(); });
  const f = $('#ef');
  const run = async () => {
    const qq = f.q.value.trim();
    const res = $('#res');
    if (!qq) { res.innerHTML = empty('Search by topic', 'RICE reads interests, paper titles and keywords to rank people.', 'radar'); paintIcons(res); return; }
    res.innerHTML = '<div class="pgrid">' + '<div class="skel" style="height:190px"></div>'.repeat(6) + '</div>';
    try {
      const r = await api(`/api/experts${qs({ q: qq, scope })}`);
      res.innerHTML = r.results.length ? `<div class="muted mb" style="font-size:13px">${r.results.length} people, best match first</div><div class="pgrid">${r.results.map((p) => personCard(p,
        `${p.evidence?.length ? `<div class="stack" style="gap:4px;font-size:12.5px">${p.evidence.map((e) => `<div class="reason">${icon('file-text', 'i-sm')}<span>${esc(e.title)} <span class="muted">(${e.year})</span></span></div>`).join('')}</div>` : ''}
        ${store.can('collab.request') && !p.external_inst && p.id !== store.me.user.id ? `<div><button class="btn xs" data-req="${p.id}">${icon('handshake', 'i-sm')}Request to collaborate</button></div>` : ''}`)).join('')}</div>`
        : empty('No one matches yet', 'Try a broader term, or search the whole RICE network.', 'search-x');
      paintIcons(res);
      $$('[data-req]', res).forEach((b) => b.onclick = () => { const p = r.results.find((x) => x.id === +b.dataset.req); requestCollab(p, qq); });
    } catch (e) { res.innerHTML = empty(e.message, '', 'lock'); paintIcons(res); }
  };
  f.onsubmit = (e) => { e.preventDefault(); history.replaceState(null, '', `#/discover/experts?q=${encodeURIComponent(f.q.value.trim())}`); run(); };
  run();
}

async function suggested(pane) {
  pane.innerHTML = '<div class="pgrid">' + '<div class="skel" style="height:220px"></div>'.repeat(6) + '</div>';
  try {
    const r = await api('/api/recommendations');
    const viaNeo = r.results.some((x) => x.engine === 'neo4j');
    pane.innerHTML = `<div class="callout mb">${icon('sparkles')}<span>People you haven't published with yet, ranked by how close your work is (text and topic overlap)
      and how close you are in the collaboration graph (shared co-authors, Adamic-Adar)${viaNeo ? ' — link prediction runs in Neo4j' : ''}. People in other departments and institutions get a small boost.</span></div>
      ${r.results.length ? `<div class="pgrid">${r.results.map((p) => personCard(p, `
        <div class="stack" style="gap:5px">${p.reasons.map((x) => `<div class="reason">${icon('sparkle', 'i-sm')}<span>${esc(x)}</span></div>`).join('')}</div>
        <div class="chips">${Object.entries(p.signals || {}).map(([k, v]) => `<span class="chip mono" title="${esc({ text: 'Text similarity', topics: 'Topic Jaccard', adamic_adar: 'Adamic-Adar' }[k])}">${esc({ text: 'text', topics: 'topics', adamic_adar: 'AA' }[k])} ${v}</span>`).join('')}</div>
        ${store.can('collab.request') ? `<div><button class="btn xs primary" data-req="${p.id}">${icon('handshake', 'i-sm')}Request to collaborate</button></div>` : ''}`)).join('')}</div>`
      : empty('No suggestions yet', 'Add research interests on your profile, or add a publication.', 'radar', '<a class="btn" href="#/account">Edit interests</a>')}`;
    paintIcons(pane);
    $$('[data-req]', pane).forEach((b) => b.onclick = () => { const p = r.results.find((x) => x.id === +b.dataset.req); requestCollab(p, p.shared?.[0] || ''); });
  } catch (e) { pane.innerHTML = empty(e.message, '', 'lock'); paintIcons(pane); }
}

async function team(pane) {
  pane.innerHTML = `<div class="grid g-1-2">
    ${card('Describe the proposal', `<form id="tf" class="stack" style="gap:12px">
      <textarea class="input" name="brief" style="min-height:150px" placeholder="e.g. Low-cost IoT sensing with machine learning for early flood warning in hill districts, with GIS mapping and community dashboards.">Low-cost IoT sensing with machine learning for flood early warning, with remote sensing and GIS mapping</textarea>
      <label class="field"><span>Team size</span><select class="input" name="size"><option>3</option><option selected>4</option><option>5</option><option>6</option></select></label>
      ${store.can('graph.network') ? `<label class="field"><span>Look in</span><select class="input" name="scope"><option value="network">RICE network</option><option value="institution">${esc(store.inst?.short || 'My institution')} only</option></select></label>` : ''}
      <button class="btn primary">${icon('wand-2')}Suggest a team</button></form>`, { sub: 'RICE picks the strongest match first, then adds people who cover new ground — other departments and institutions — and prefers people who already know each other.' })}
    <div id="tres">${empty('Your team appears here', 'Each pick comes with the reason it was chosen.', 'users-round')}</div></div>`;
  paintIcons(pane);
  $('#tf').onsubmit = async (e) => {
    e.preventDefault();
    const f = e.target;
    const out = $('#tres');
    out.innerHTML = '<div class="skel" style="height:320px"></div>';
    try {
      const r = await api('/api/team', { method: 'POST', body: { brief: f.brief.value, size: +f.size.value, scope: f.scope?.value || 'institution' } });
      if (!r.team.length) { out.innerHTML = empty('No one matched that brief', 'Use plainer topic words.', 'search-x'); paintIcons(out); return; }
      out.innerHTML = `${card(`Suggested team <span class="badge n">${r.team.length}</span>`, `
        <div class="row mb" style="gap:16px;font-size:13.5px"><span><b>${r.depts}</b> departments</span><span><b>${r.insts}</b> institution${r.insts > 1 ? 's' : ''}</span>
          <span><b>${r.existing_ties}</b> of ${r.pairs} pairs have published together</span></div>
        <div class="grid g2" style="gap:12px">${r.team.map((p, i) => personCard(p, `<div class="stack" style="gap:4px">${p.why.map((w) => `<div class="reason">${icon(i === 0 ? 'crown' : 'plus-circle', 'i-sm')}<span>${esc(w)}</span></div>`).join('')}</div>`)).join('')}</div>
        ${r.coverage.length ? `<h4 class="mt2" style="font-size:12px;letter-spacing:.08em;text-transform:uppercase;color:var(--ink-3)">Who covers what</h4>
        <div class="tbl-wrap mt"><table class="tbl"><thead><tr><th>Term in your brief</th><th>Covered by</th></tr></thead><tbody>${r.coverage.map((c) => `<tr><td><b>${esc(c.term)}</b></td>
          <td>${c.by.length ? esc(c.by.join(', ')) : '<span class="st pending">gap</span>'}</td></tr>`).join('')}</tbody></table></div>` : ''}`)}`;
      paintIcons(out);
    } catch (err) { fail(err); out.innerHTML = ''; }
  };
}

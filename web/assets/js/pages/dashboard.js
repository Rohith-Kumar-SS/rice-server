import { api, store } from '../api.js';
import { bars, donut, lines, paintSparks, PALETTE } from '../charts.js';
import { $, $$, avatar, card, crore, empty, esc, fmtDate, daysLeft, icon, kpi, marks, num, paintIcons, quart } from '../ui.js';
import { requestCollab } from './collaborate.js';

const CLASS_LABEL = { single: 'One department', inter_dept: 'Across departments', cross_inst: 'With RICE peers', national: 'Other Indian institutions', international: 'International' };

export async function render(el) {
  const d = await api('/api/dashboard');
  const u = store.me.user;
  const hr = new Date().getHours();
  const greet = hr < 12 ? 'Good morning' : hr < 17 ? 'Good afternoon' : 'Good evening';
  const today = new Date().toLocaleDateString('en-IN', { weekday: 'long', day: 'numeric', month: 'long', year: 'numeric' });
  const k = d.kpis, t = d.trend;
  const scopeName = d.scope.kind === 'me' ? 'your research' : d.scope.name;
  const researcher = !!d.me;

  el.innerHTML = `
    <div class="ph"><div class="t">
      <div class="eyebrow">${esc(today)}${store.inst ? ` · ${esc(store.inst.name)}` : ''}</div>
      <h1>${greet}, ${esc(u.name.split(' ')[0])}</h1>
      <p class="lead">Here is what changed in ${esc(scopeName)} — ${t.years[0]} to ${t.years[t.years.length - 1]}, verified records only.</p></div>
      <div class="acts">${store.can('graph.institution') ? `<a class="btn" href="#/graph">${icon('share-2')}Open the graph</a>` : ''}
        ${store.can('reports.view') ? `<a class="btn" href="#/reports">${icon('file-bar-chart')}Reports</a>` : ''}</div></div>

    ${d.tasks.length ? `<div class="tasks mb">${d.tasks.map((x) => `<a class="task" href="${x.link}"><span class="n">${x.count}</span>${esc(x.text.replace(/^\d+\s/, ''))}${icon('arrow-right', 'i-sm')}</a>`).join('')}</div>` : ''}

    ${d.insights.length ? `<section class="pulse swipe mb" aria-label="Research pulse">
      <div class="lab">${icon('activity', 'i-sm')}Research pulse · ${esc(d.scope.kind === 'me' ? 'You' : d.scope.name)}</div>
      <ol>${d.insights.map((x, i) => `<li><a href="${x.link}">${marks(x.text, i)}${icon('arrow-up-right', 'go i-sm')}</a></li>`).join('')}</ol>
    </section>` : ''}

    ${d.scope.kind !== 'me' ? `<div class="kpis mb">
      ${kpi({ label: 'Publications', value: num(k.publications), delta: k.publications_growth, basis: k.growth_basis, note: `${k.pubs_per_faculty} per faculty`, icon: 'file-text', spark: t.publications })}
      ${kpi({ label: 'Citations', value: num(k.citations), note: `${k.cites_per_paper} per paper`, icon: 'quote', spark: t.citations })}
      ${kpi({ label: 'h-index', value: k.h_index, note: `FWCI ${k.fwci ?? '—'}`, icon: 'trending-up' })}
      ${kpi({ label: 'Q1 journal share', value: k.q1_share, unit: '%', note: `${k.open_access_share}% open access`, icon: 'award' })}
      ${kpi({ label: 'Grants sanctioned', value: crore(k.funding_lakh), note: `${k.active_projects} active projects`, icon: 'landmark', spark: t.funding })}
      ${kpi({ label: 'Patents', value: num(k.patents), note: `${k.patents_granted} granted`, icon: 'lightbulb', spark: t.patents })}
    </div>` : ''}

    ${researcher ? `<div class="grid g-1-2 mb">
      ${card('Your research', `<div class="mini-stats">
          <div class="s"><div class="v">${num(d.me.pubs)}</div><div class="k">Papers</div></div>
          <div class="s"><div class="v">${num(d.me.citations)}</div><div class="k">Citations</div></div>
          <div class="s"><div class="v">${d.me.h_index}</div><div class="k">h-index</div></div>
          <div class="s"><div class="v">${d.me.coauthors}</div><div class="k">Co-authors</div></div></div>
        <div class="chart short mt" id="c-me"></div>`, { actions: `<a class="btn sm ghost" href="#/people/${u.id}">Profile ${icon('arrow-right', 'i-sm')}</a>` })}
      ${card('People you should meet', d.suggestions?.length ? `<div class="grid g2" style="gap:12px">${d.suggestions.map(sugg).join('')}</div>`
        : empty('No suggestions yet', 'Add research interests on your profile to get matched.', 'radar'),
        { actions: store.can('discover.experts') ? `<a class="btn sm ghost" href="#/discover/suggested">See all ${icon('arrow-right', 'i-sm')}</a>` : '',
          sub: 'Matched on topics and shared co-authors — people you have not published with yet.' })}
    </div>` : ''}

    ${d.scope.kind !== 'me' ? `<div class="grid g-2-1 mb">
      ${card('Research output over time', '<div class="chart" id="c-trend"></div>', { actions: `<div class="seg" id="metric">
        <button class="on" data-m="publications">Papers</button><button data-m="citations">Citations</button><button data-m="funding">Funding</button>
        <button data-m="patents">Patents</button><button data-m="international">International</button></div>` })}
      ${card('Who the papers are written with', '<div class="chart" id="c-collab"></div>', { sub: 'Each paper counted once, at its widest reach.' })}
    </div>` : ''}

    <div class="grid g3">
      ${card('Rising topics', d.rising.length ? `<div class="list">${d.rising.map((r) => `<div class="it"><div class="body">
        <a class="ttl" href="#/discover/experts?q=${encodeURIComponent(r.topic)}">${esc(r.topic)}</a>
        <div class="meta"><span>${r.recent} papers in the last 3 years</span><span>vs ${r.earlier} before</span></div></div>
        <span class="delta up">+${r.growth}%</span></div>`).join('')}</div>` : empty('No rising topics yet', 'Topics appear here once they gain momentum.', 'trending-up'),
        { actions: `<a class="btn sm ghost" href="#/analytics/topics">Topics ${icon('arrow-right', 'i-sm')}</a>` })}
      ${card('Upcoming deadlines', d.deadlines.length ? `<div class="list">${d.deadlines.map((o) => {
        const dl = daysLeft(o.deadline);
        return `<div class="it"><div class="body"><a class="ttl" href="#/opportunities">${esc(o.title)}</a>
          <div class="meta"><span>${esc({ call: 'Funding call', position: 'Opening', collab: 'Collaboration ask', event: 'Event' }[o.kind])}</span><span>${esc(o.inst)}</span><span>${fmtDate(o.deadline)}</span></div></div>
          <span class="chip ${dl <= 10 ? 'acc' : ''}">${dl} d</span></div>`; }).join('')}</div>` : empty('Nothing due soon', '', 'calendar'),
        { actions: `<a class="btn sm ghost" href="#/opportunities">All ${icon('arrow-right', 'i-sm')}</a>` })}
      ${card('Recently verified', d.feed.length ? `<div class="list">${d.feed.map((p) => `<div class="it"><div class="body">
        <div class="ttl">${esc(p.title)}</div><div class="meta"><span>${esc(p.people.join(', '))}</span><span>${p.year}</span>${quart(p.quartile)}</div></div></div>`).join('')}</div>`
        : empty('No verified records yet', 'Add your first publication to start the graph.', 'file-text'))}
    </div>

    ${d.platform ? `<div class="mt2">${card('RICE platform at a glance', platformTable(d.platform), { actions: `<a class="btn sm" href="#/platform">Manage tenants ${icon('arrow-right', 'i-sm')}</a>`,
      sub: `${d.platform.tenants.length} institutions subscribed · ${d.platform.tracked} tracked externally · ${d.platform.onboarding.filter((o) => o.status === 'new').length} onboarding requests waiting` })}</div>` : ''}
    ${store.me.user.role === 'external' ? `<div class="mt2">${card('Working with ' + esc(store.inst?.name || 'RICE'), `<p class="soft" style="margin:0 0 12px">As an industry partner you can search experts across the institutions that share with ${esc(store.inst?.short || '')}, and follow their open calls.</p>
      <div class="row"><a class="btn primary" href="#/discover">${icon('radar')}Find experts</a><a class="btn" href="#/opportunities">${icon('megaphone')}Open opportunities</a></div>`)}</div>` : ''}`;

  paintIcons(el);
  paintSparks(el);
  if (d.scope.kind !== 'me') {
    const drawTrend = (m) => {
      const lab = { publications: 'Papers', citations: 'Citations to papers from that year', funding: 'Sanctioned funding (₹ lakh)', patents: 'Patents', international: 'Papers with international co-authors' }[m];
      bars($('#c-trend'), { categories: t.years, series: [{ name: lab, data: t[m] }], fmt: m === 'funding' ? (v) => crore(v) : (v) => num(v) });
    };
    drawTrend('publications');
    $$('#metric button').forEach((b) => b.onclick = () => { $$('#metric button').forEach((x) => x.classList.toggle('on', x === b)); drawTrend(b.dataset.m); });
    donut($('#c-collab'), { data: Object.entries(d.collab).map(([k2, v]) => ({ name: CLASS_LABEL[k2], value: v })), center: 'papers' });
  }
  if (researcher && d.me_trend) {
    lines($('#c-me'), { categories: d.me_trend.years, series: [{ name: 'Your papers', data: d.me_trend.publications, area: true }] });
  }
  $$('[data-req]', el).forEach((b) => b.onclick = () => {
    const s = d.suggestions.find((x) => x.id === +b.dataset.req);
    requestCollab(s, s.shared?.[0] || s.interests?.[0] || '');
  });
}

function sugg(s) {
  return `<div class="card flat tint" style="padding:14px;display:flex;flex-direction:column;gap:8px">
    <div class="row between" style="flex-wrap:nowrap"><a class="who" href="#/people/${s.id}">${avatar(s)}<span style="min-width:0"><span class="nm">${esc(s.name)}</span><br>
      <span class="ds">${esc(s.designation)} · ${esc(s.dept)} · ${esc(s.inst)}</span></span></a><span class="match" title="Match score">${s.score}</span></div>
    ${s.reasons.slice(0, 2).map((r) => `<div class="reason">${icon('sparkle', 'i-sm')}<span>${esc(r)}</span></div>`).join('')}
    ${store.can('collab.request') ? `<div><button class="btn xs" data-req="${s.id}">${icon('handshake', 'i-sm')}Request to collaborate</button></div>` : ''}</div>`;
}

function platformTable(p) {
  return `<div class="tbl-wrap"><table class="tbl"><thead><tr><th>Institution</th><th>Plan</th><th>Sharing</th><th class="num">Members</th><th class="num">Active 30 d</th><th class="num">Papers (2019+)</th><th class="num">Grants</th></tr></thead>
  <tbody>${p.tenants.map((t) => `<tr><td><span class="row" style="flex-wrap:nowrap"><span class="swatch" style="background:${esc(t.brand)};width:14px;height:14px;border-radius:4px"></span><b>${esc(t.name)}</b> <span class="muted">${esc(t.city || '')}</span></span></td>
    <td>${esc(t.plan)}</td><td><span class="chip">${esc(t.share_level)}</span></td><td class="num">${num(t.members)}</td><td class="num">${num(t.active_30d)}</td>
    <td class="num">${num(t.publications)}</td><td class="num">${crore(t.funding_lakh)}</td></tr>`).join('')}</tbody></table></div>`;
}
export { PALETTE };

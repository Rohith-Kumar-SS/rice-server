import { api, qs, store } from '../api.js';
import { bars, heatmap, ink, mount, PALETTE } from '../charts.js';
import { $, $$, avatar, card, crore, debounce, empty, esc, icon, paintIcons, pubLine, roleLabel, status } from '../ui.js';
import { requestCollab } from './collaborate.js';

export async function render(el, { parts, query }) {
  if (parts[1]) return profile(el, +parts[1]);
  return directory(el, query);
}

async function directory(el, query) {
  const me = store.me;
  const st = { q: query.q || '', dept: query.dept || '', role: query.role || '', sort: 'name', size: 48 };
  el.innerHTML = `<div class="ph"><div class="t"><div class="eyebrow">${esc(store.inst?.name || '')}</div><h1>People</h1>
      <p class="lead">Everyone in the institution's research community — faculty, scholars, students and staff — in one directory.</p></div></div>
    <div class="filters">
      <span class="row grow" style="flex-wrap:nowrap">${icon('search')}<input class="input sm" id="q" placeholder="Name or research interest" value="${esc(st.q)}" style="border:0;box-shadow:none"></span>
      <select class="input sm" id="dept" style="width:auto"><option value="">All departments</option>${me.departments.map((d) => `<option value="${d.id}">${esc(d.name)}</option>`).join('')}</select>
      <select class="input sm" id="role" style="width:auto"><option value="">Everyone</option>${['hod', 'faculty', 'scholar', 'student', 'staff', 'inst_admin'].map((r) => `<option value="${r}">${esc(roleLabel(r))}</option>`).join('')}</select>
      <select class="input sm" id="sort" style="width:auto"><option value="name">A–Z</option><option value="pubs">Most papers</option><option value="citations">Most cited</option><option value="h_index">h-index</option></select>
    </div><div id="counts" class="chips mb"></div><div id="grid"></div>`;
  paintIcons(el);
  const load = async () => {
    const r = await api(`/api/people${qs({ q: st.q, dept: st.dept, role: st.role, sort: st.sort, page: 1, size: st.size })}`);
    $('#counts').innerHTML = `<span class="chip acc">${r.total} people</span>` + Object.entries(r.counts).map(([k, v]) => `<span class="chip">${v} ${esc(roleLabel(k).toLowerCase())}</span>`).join('');
    $('#grid').innerHTML = r.rows.length ? `<div class="pgrid">${r.rows.map((p) => `<a class="pcard" href="#/people/${p.id}">
        <div class="who">${avatar(p)}<span style="min-width:0"><span class="nm">${esc(p.name)}</span><br><span class="ds">${esc(p.designation || roleLabel(p.role))} · ${esc(p.dept || '—')}</span></span></div>
        <div class="chips">${p.interests.slice(0, 3).map((t) => `<span class="chip">${esc(t)}</span>`).join('')}</div>
        <div class="stats"><span><b>${p.pubs}</b>papers</span><span><b>${p.citations}</b>cites</span><span><b>${p.h_index}</b>h</span>${p.students ? `<span><b>${p.students}</b>guided</span>` : ''}</div></a>`).join('')}</div>
        ${r.total > r.rows.length ? `<div class="row mt" style="justify-content:center"><button class="btn" id="more">Show more (${r.total - r.rows.length} left)</button></div>` : ''}`
      : empty('No one matches', 'Clear a filter or search a broader interest.', 'users');
    paintIcons($('#grid'));
    $('#more')?.addEventListener('click', () => { st.size += 48; load(); });
  };
  $('#q').oninput = debounce((e) => { st.q = e.target.value; load(); }, 250);
  ['dept', 'role', 'sort'].forEach((k) => { $('#' + k).value = st[k]; $('#' + k).onchange = (e) => { st[k] = e.target.value; load(); }; });
  await load();
}

async function profile(el, id) {
  const p = await api(`/api/people/${id}`);
  const m = p.metrics;
  const isMe = id === store.me.user.id;
  el.innerHTML = `
    <section class="card mb"><div class="hero-card">${avatar(p, 'xl')}
      <div class="id"><div class="eyebrow">${esc(p.role_label)}${p.external_inst ? ' · tracked externally' : ''}</div><h1>${esc(p.name)}</h1>
        <div class="soft" style="margin-top:4px">${esc([p.designation, p.dept_name, p.inst_name].filter(Boolean).join(' · '))}</div>
        <div class="chips mt">${p.interests.map((t) => `<a class="chip" href="#/discover/experts?q=${encodeURIComponent(t)}">${esc(t)}</a>`).join('')}</div>
        <div class="row mt" style="font-size:13px">${p.orcid ? `<a href="https://orcid.org/${esc(p.orcid)}" target="_blank" rel="noopener">${icon('external-link', 'i-sm')} ORCID ${esc(p.orcid)}</a>` : ''}
          ${p.scopus_id ? `<a href="https://www.scopus.com/authid/detail.uri?authorId=${esc(p.scopus_id)}" target="_blank" rel="noopener">${icon('external-link', 'i-sm')} Scopus ${esc(p.scopus_id)}</a>` : ''}
          ${p.email ? `<span class="muted">${icon('mail', 'i-sm')} ${esc(p.email)}</span>` : ''}${p.joined ? `<span class="muted">Since ${p.joined}</span>` : ''}</div></div>
      <div class="stack" style="gap:8px;align-items:flex-end">
        ${p.can_request ? `<button class="btn primary" id="req">${icon('handshake')}Request to collaborate</button>` : ''}
        ${isMe ? `<a class="btn" href="#/account">${icon('pencil')}Edit profile</a>` : ''}
        ${store.can('graph.institution') ? `<a class="btn ghost" href="#/graph?ego=${id}">${icon('orbit')}Open in graph explorer</a>` : ''}</div></div></section>
    ${p.bio ? `<p class="soft mb" style="max-width:900px">${esc(p.bio)}</p>` : ''}
    <div class="mini-stats mb">
      ${[['Papers', m.pubs], ['Citations', m.citations], ['h-index', m.h_index], ['FWCI', m.fwci ?? '—'], ['Q1 papers', m.q1], ['Co-authors', m.coauthors],
        ['Funded projects', m.projects], ['Grants as PI/Co-PI', m.funding ? crore(m.funding) : '—'], ['Patents', m.patents], ['Guides', m.students]].map(([k, v]) =>
        `<div class="s"><div class="v">${v}</div><div class="k">${k}</div></div>`).join('')}</div>
    <div class="grid g-3-2 mb">
      ${card('Knowledge graph', '<div class="chart tall" id="c-ego"></div>', { sub: 'Co-authors, topics, projects and partner organisations around this researcher.', actions: '<span class="engine" id="ego-eng"><span class="dot"></span>…</span>' })}
      ${card('Output and citations', '<div class="chart short" id="c-tr"></div><div class="chart short" id="c-ci"></div>')}
    </div>
    ${p.topic_timeline.topics.length ? `<div class="mb">${card('How the research focus has moved', '<div class="chart" id="c-tt"></div>')}</div>` : ''}
    <div class="grid g-2-1">
      <div class="stack">
        ${card(`Publications <span class="badge n">${p.publications.length}</span>`, p.publications.length ? `<div class="list" id="pubs">${p.publications.slice(0, 25).map((x) => pubLine(x)).join('')}</div>
          ${p.publications.length > 25 ? `<button class="btn sm mt" id="more-pubs">Show all ${p.publications.length}</button>` : ''}` : empty('No publications yet', isMe ? 'Add one from Research records, or import from ORCID.' : '', 'file-text'))}
        ${p.projects.length ? card('Projects', `<div class="list">${p.projects.map((j) => `<div class="it"><div class="body"><div class="ttl">${esc(j.title)}</div>
          <div class="meta"><b class="soft">${esc(j.agency)}</b><span>${esc(j.scheme || '')}</span><span>${j.start_year}–${j.end_year}</span>${status(j.stage)}<span>${esc(j.members.find((x) => x.id === id)?.role || '')}</span></div></div>
          <b class="nowrap">${crore(j.amount)}</b></div>`).join('')}</div>`) : ''}
        ${p.patents.length ? card('Patents', `<div class="list">${p.patents.map((x) => `<div class="it"><div class="body"><div class="ttl">${esc(x.title)}</div><div class="meta"><span class="mono">${esc(x.number)}</span><span>${x.year}</span>${status(x.stage)}</div></div></div>`).join('')}</div>`) : ''}
      </div>
      <div class="stack">
        ${p.supervisor ? card('Supervisor', `<a class="who" href="#/people/${p.supervisor.id}">${avatar(p.supervisor)}<span><span class="nm">${esc(p.supervisor.name)}</span><br><span class="ds">${esc(p.supervisor.designation)} · ${esc(p.supervisor.dept)}</span></span></a>`) : ''}
        ${card('Frequent co-authors', p.coauthors.length ? `<div class="list">${p.coauthors.map((c) => `<div class="it"><a class="who" href="#/people/${c.id}" style="flex:1">${avatar(c, 'sm')}<span style="min-width:0"><span class="nm">${esc(c.name)}</span><br><span class="ds">${esc(c.dept)} · ${esc(c.inst)}</span></span></a><span class="mono muted">${c.count}</span></div>`).join('')}</div>` : empty('No co-authors yet', '', 'users'))}
        ${p.students.length ? card(`Guides <span class="badge n">${p.students.length}</span>`, `<div class="list">${p.students.map((c) => `<div class="it"><a class="who" href="#/people/${c.id}">${avatar(c, 'sm')}<span><span class="nm">${esc(c.name)}</span><br><span class="ds">${esc(c.designation)}</span></span></a></div>`).join('')}</div>`) : ''}
        ${p.external_partners.length ? card('Partner organisations', `<div class="chips">${p.external_partners.map((x) => `<span class="chip">${esc(x)}</span>`).join('')}</div>`) : ''}
        <div id="similar"></div>
      </div></div>`;
  paintIcons(el);
  $('#req')?.addEventListener('click', () => requestCollab(p, p.interests[0] || ''));
  $('#more-pubs')?.addEventListener('click', (e) => { $('#pubs').innerHTML = p.publications.map((x) => pubLine(x)).join(''); e.target.remove(); paintIcons($('#pubs')); });
  bars($('#c-tr'), { categories: p.trend.years, series: [{ name: 'Papers', data: p.trend.pubs }] });
  bars($('#c-ci'), { categories: p.trend.years, series: [{ name: 'Citations to that year\'s papers', data: p.trend.citations }], colors: [PALETTE[1]] });
  if (p.topic_timeline.topics.length) heatmap($('#c-tt'), { x: p.topic_timeline.years, y: p.topic_timeline.topics, data: p.topic_timeline.cells });
  api(`/api/graph-ego/${id}`).then((g) => {
    const eng = g.engine_info || {};
    const pill = $('#ego-eng');
    if (pill) { pill.className = `engine ${g.engine === 'neo4j' ? '' : 'off'}`; pill.innerHTML = `<span class="dot"></span>${esc(g.engine === 'neo4j' ? 'Neo4j' : 'In-memory')}`; pill.title = eng.label || ''; }
    egoChart($('#c-ego'), g);
  }).catch((e) => { $('#c-ego').innerHTML = empty(e.message, '', 'lock'); paintIcons($('#c-ego')); });
  if (store.can('discover.experts') && !p.external_inst) {
    api(`/api/people/${id}/similar`).then((r) => {
      if (!r.results.length) return;
      $('#similar').innerHTML = card(isMe ? 'People you should meet' : 'Researchers with similar work', `<div class="list">${r.results.map((s) => `<div class="it">
        <a class="who" href="#/people/${s.id}" style="flex:1">${avatar(s, 'sm')}<span style="min-width:0"><span class="nm">${esc(s.name)}</span><br><span class="ds">${esc(s.reasons[0] || '')}</span></span></a>
        <span class="match">${s.score}</span></div>`).join('')}</div>`, { sub: 'Not yet co-authors — matched on topics and shared collaborators.' });
      paintIcons($('#similar'));
    }).catch(() => {});
  }
}

export function egoChart(el, g) {
  const k = ink();
  const colors = { person: PALETTE[0], topic: PALETTE[2], project: PALETTE[3], org: PALETTE[1] };
  const ch = mount(el, {
    tooltip: { backgroundColor: k.card, borderColor: k.line2, textStyle: { color: k.t1, fontSize: 12.5 }, formatter: (x) => (x.dataType === 'node' ? `<b>${esc(x.data.raw.name)}</b><br>${esc({ person: x.data.raw.inst || 'Researcher', topic: 'Topic', project: `Project · ${x.data.raw.agency || ''}`, org: 'Partner organisation' }[x.data.raw.kind])}` : '') },
    legend: { data: ['Researcher', 'Topic', 'Project', 'Organisation'], bottom: 0, icon: 'circle', itemWidth: 9, textStyle: { color: k.t2, fontSize: 11.5 } },
    series: [{
      type: 'graph', layout: 'none', roam: true,
      categories: [{ name: 'Researcher', itemStyle: { color: colors.person } }, { name: 'Topic', itemStyle: { color: colors.topic } },
        { name: 'Project', itemStyle: { color: colors.project } }, { name: 'Organisation', itemStyle: { color: colors.org } }],
      data: g.nodes.map((n) => ({ id: n.id, name: n.name.length > 30 ? n.name.slice(0, 28) + '…' : n.name, x: n.x, y: n.y, raw: n,
        category: { person: 0, topic: 1, project: 2, org: 3 }[n.kind],
        symbolSize: n.focus ? 40 : n.kind === 'person' ? 9 + Math.sqrt(n.degree) * 2.4 : 13,
        symbol: n.kind === 'topic' ? 'roundRect' : n.kind === 'project' ? 'diamond' : n.kind === 'org' ? 'triangle' : 'circle',
        itemStyle: { color: colors[n.kind], borderColor: n.focus ? '#FFE45C' : k.card, borderWidth: n.focus ? 5 : 1.5 },
        label: { show: n.focus || n.kind !== 'person' || n.degree > 3 } })),
      links: g.edges.map((e) => ({ source: e.source, target: e.target, lineStyle: { width: Math.min(4, 0.6 + e.weight * 0.4) } })),
      label: { position: 'right', fontSize: 11, color: k.t1, textBorderColor: k.card, textBorderWidth: 3 }, labelLayout: { hideOverlap: true },
      lineStyle: { color: k.line2, opacity: 0.7, curveness: 0.1 }, emphasis: { focus: 'adjacency' },
    }],
  });
  ch?.on('click', (x) => { if (x.dataType === 'node' && x.data.raw.kind === 'person' && !x.data.raw.focus) location.hash = `#/people/${x.data.raw.ref}`; });
}

import { api, download, qs, store } from '../api.js';
import { bars, boxplot, chord, donut, heatmap, lines, PALETTE, radar, sankey, scatter } from '../charts.js';
import { $, $$, avatar, card, crore, empty, esc, fail, icon, kpi, marks, num, paintIcons, pct, pubLine, quart, table, toast } from '../ui.js';

const TABS = [
  ['overview', 'Overview', 'gauge'], ['output', 'Output', 'file-text'], ['impact', 'Impact', 'quote'], ['topics', 'Topics & SDGs', 'tags'],
  ['funding', 'Funding', 'landmark'], ['people', 'People', 'users'], ['collaboration', 'Collaboration', 'handshake'],
  ['departments', 'Departments', 'layers'], ['graph', 'Graph analysis', 'share-2'],
];
const KIND = { journal: 'Journal', conference: 'Conference', chapter: 'Book chapter', book: 'Book', preprint: 'Preprint' };
const CLASS = { single: 'Single department', inter_dept: 'Across departments', cross_inst: 'With RICE institutions', national: 'Other Indian institutions', international: 'International' };

export async function render(el, { parts, query }) {
  const me = store.me;
  const canInst = store.can('analytics.institution'), canDept = store.can('analytics.department') || canInst;
  const researcher = !['external', 'platform_admin', 'inst_admin', 'staff'].includes(me.user.role);
  const scopes = [canInst && ['institution', store.inst?.short || 'Institution'], canDept && ['department', 'Department'], researcher && ['me', 'My research']].filter(Boolean);
  const st = {
    tab: parts[1] || 'overview',
    scope: query.scope || scopes[0]?.[0] || 'me',
    dept: query.dept ? +query.dept : (me.user.dept_id || me.departments[0]?.id),
    y0: +(query.y0 || me.years[0]), y1: +(query.y1 || me.years[1]), pending: false,
  };
  if (!scopes.find((s) => s[0] === st.scope)) st.scope = scopes[0]?.[0] || 'me';
  if (st.tab === 'departments' && st.scope === 'me') st.tab = 'overview';

  const yopts = (v) => { let o = ''; for (let y = me.years[1]; y >= me.years[0]; y--) o += `<option ${y === v ? 'selected' : ''}>${y}</option>`; return o; };
  const header = () => `
    <div class="ph"><div class="t"><div class="eyebrow">Analytics <span class="scope-tag">${esc(st.scope === 'me' ? 'YOU' : st.scope === 'department' ? (me.departments.find((d) => d.id === st.dept)?.code || 'DEPT') : store.inst?.short || '')}</span></div>
      <h1>Research analytics</h1><p class="lead">Verified records only unless you include pending ones. Every chart has a table behind it — hover for exact values.</p></div>
      <div class="acts">${store.can('data.export') && st.scope !== 'me' ? `<div style="position:relative"><button class="btn" id="exp">${icon('download')}Export CSV</button></div>` : ''}</div></div>
    <div class="filters">
      ${scopes.length > 1 ? `<div class="seg">${scopes.map(([k, l]) => `<button data-scope="${k}" class="${st.scope === k ? 'on' : ''}">${esc(l)}</button>`).join('')}</div>` : ''}
      ${st.scope === 'department' ? `<select class="input sm" id="f-dept" style="width:auto" ${canInst ? '' : 'disabled'}>${me.departments.map((d) => `<option value="${d.id}" ${d.id === st.dept ? 'selected' : ''}>${esc(d.name)}</option>`).join('')}</select>` : ''}
      <span class="lbl">Years</span><select class="input sm" id="f-y0" style="width:auto">${yopts(st.y0)}</select><span class="muted">–</span><select class="input sm" id="f-y1" style="width:auto">${yopts(st.y1)}</select>
      <label class="switch"><input type="checkbox" id="f-pend" ${st.pending ? 'checked' : ''}>Include pending</label>
    </div>
    <nav class="tabs">${TABS.filter(([k]) => !(k === 'departments' && st.scope === 'me') && !(k === 'graph' && !store.can('graph.institution'))).map(([k, l, ic]) =>
      `<a href="javascript:void 0" data-tab="${k}" class="${st.tab === k ? 'on' : ''}">${icon(ic, 'i-sm')}${l}</a>`).join('')}</nav>
    <div id="pane"></div>`;

  const params = () => ({ scope: st.scope, dept: st.scope === 'department' ? st.dept : undefined, y0: st.y0, y1: st.y1, pending: st.pending ? 1 : undefined });
  const draw = async () => {
    el.innerHTML = header();
    paintIcons(el);
    wire();
    const pane = $('#pane');
    pane.innerHTML = '<div class="loading"><div class="skel" style="height:110px"></div><div class="skel" style="height:320px"></div></div>';
    try {
      if (st.tab === 'graph') return await graphTab(pane, st);
      const data = await api(`/api/analytics/${st.tab}${qs(params())}`);
      const fn = { overview, output, impact, topics, funding, people, collaboration, departments }[st.tab];
      await fn(pane, data, st);
      paintIcons(pane);
    } catch (e) {
      pane.innerHTML = empty(e.message, e.status === 403 ? 'Your institution admin controls who sees this view.' : '', 'lock');
      paintIcons(pane);
    }
  };
  const wire = () => {
    $$('[data-scope]', el).forEach((b) => b.onclick = () => { st.scope = b.dataset.scope; if (st.scope === 'me' && st.tab === 'departments') st.tab = 'overview'; draw(); });
    $$('[data-tab]', el).forEach((b) => b.onclick = () => { st.tab = b.dataset.tab; history.replaceState(null, '', `#/analytics/${st.tab}`); draw(); });
    $('#f-dept')?.addEventListener('change', (e) => { st.dept = +e.target.value; draw(); });
    $('#f-y0').onchange = (e) => { st.y0 = +e.target.value; draw(); };
    $('#f-y1').onchange = (e) => { st.y1 = +e.target.value; draw(); };
    $('#f-pend').onchange = (e) => { st.pending = e.target.checked; draw(); };
    $('#exp')?.addEventListener('click', (e) => exportMenu(e.currentTarget, params()));
  };
  await draw();
}

function exportMenu(btn, p) {
  if (btn.parentElement.querySelector('.menu')) { btn.parentElement.querySelector('.menu').remove(); return; }
  const m = document.createElement('div');
  m.className = 'menu';
  m.innerHTML = ['publications', 'projects', 'patents', 'people'].map((k) => `<button class="mi" data-e="${k}">${icon('file-spreadsheet', 'i-sm')}${k[0].toUpperCase() + k.slice(1)} (.csv)</button>`).join('');
  btn.parentElement.appendChild(m);
  paintIcons(m);
  m.querySelectorAll('[data-e]').forEach((b) => b.onclick = async () => {
    m.remove();
    try { await download(`/api/export/${b.dataset.e}.csv${qs({ ...p, pending: undefined })}`, `rice-${b.dataset.e}.csv`); toast('Download started'); } catch (e) { fail(e); }
  });
}

const insightBox = (items) => items?.length ? `<div class="stack swipe" style="gap:8px">${items.map((x, i) => `<a class="insight" href="${x.link}" style="color:var(--ink)">${icon('sparkle', 'i-sm')}<span>${marks(x.text, i)}</span></a>`).join('')}</div>` : '';

async function overview(pane, d, st) {
  const k = d.kpis, t = d.trend;
  const ins = await api(`/api/analytics/insights${qs({ scope: st.scope, dept: st.scope === 'department' ? st.dept : undefined, y0: st.y0, y1: st.y1 })}`).catch(() => ({ insights: [] }));
  pane.innerHTML = `
    <div class="kpis mb">
      ${kpi({ label: 'Publications', value: num(k.publications), delta: k.publications_growth, basis: k.growth_basis, note: `${k.pubs_per_faculty} per faculty`, spark: t.publications })}
      ${kpi({ label: 'Citations', value: num(k.citations), note: `${k.cites_per_paper} per paper`, spark: t.citations })}
      ${kpi({ label: 'h-index · FWCI', value: `${k.h_index}<small>· ${k.fwci ?? '—'}</small>`, note: 'FWCI 1.0 = platform average' })}
      ${kpi({ label: 'Q1 share', value: k.q1_share, unit: '%', note: `${k.open_access_share}% open access` })}
      ${kpi({ label: 'Grants', value: crore(k.funding_lakh), delta: k.funding_growth, basis: k.growth_basis, note: `${k.success_rate}% success`, spark: t.funding })}
      ${kpi({ label: 'Patents', value: num(k.patents), note: `${k.patents_granted} granted`, spark: t.patents })}
    </div>
    <div class="grid g-3-2 mb">
      ${card('Findings', insightBox(ins.insights) || empty('Not enough data for findings yet'), { sub: 'Generated from the numbers on this page — click one to see the evidence.' })}
      ${card('Output mix', '<div class="chart" id="c-kind"></div>')}
    </div>
    <div class="grid g2 mb">
      ${card('Papers per year', '<div class="chart" id="c-pubs"></div>')}
      ${card('Citations to papers from each year', '<div class="chart" id="c-cites"></div>', { sub: 'Recent years have had less time to collect citations.' })}
    </div>
    <div class="grid g2">
      ${card('Journal quality', '<div class="chart short" id="c-q"></div>', { sub: 'Scopus-style quartile of the journal.' })}
      ${card('How far each paper reaches', '<div class="chart short" id="c-col"></div>')}
    </div>`;
  paintIcons(pane);
  const { paintSparks } = await import('../charts.js');
  paintSparks(pane);
  donut($('#c-kind'), { data: d.kinds.map((x) => ({ name: KIND[x.name] || x.name, value: x.value })), center: 'outputs' });
  bars($('#c-pubs'), { categories: t.years, series: [{ name: 'Papers', data: t.publications }] });
  lines($('#c-cites'), { categories: t.years, series: [{ name: 'Citations', data: t.citations, area: true }] });
  bars($('#c-q'), { categories: d.quartiles.map((x) => x.name), series: [{ name: 'Journal papers', data: d.quartiles.map((x) => x.value) }], colors: [PALETTE[2]] });
  bars($('#c-col'), { categories: Object.keys(d.collab).map((x) => CLASS[x]), series: [{ name: 'Papers', data: Object.values(d.collab) }], horizontal: true, colors: [PALETTE[1]] });
}

async function output(pane, d) {
  pane.innerHTML = `
    <div class="grid g2 mb">${card('Outputs by type', '<div class="chart tall" id="c-k"></div>')}${card('Journal papers by quartile', '<div class="chart tall" id="c-qy"></div>')}</div>
    <div class="grid g2 mb">${card('Open-access share', '<div class="chart" id="c-oa"></div>')}${card('Papers per faculty member', '<div class="chart" id="c-pf"></div>', { sub: 'Faculty counted from their joining year.' })}</div>
    ${card('Where the institution publishes', '<div id="t-v"></div>', { sub: 'Top 15 venues in the selected years.' })}`;
  bars($('#c-k'), { categories: d.years, series: Object.entries(d.by_kind).map(([k, v]) => ({ name: KIND[k] || k, data: v })), stack: true });
  bars($('#c-qy'), { categories: d.years, series: Object.entries(d.by_quartile).map(([k, v]) => ({ name: k, data: v })), stack: true, colors: [PALETTE[2], PALETTE[0], PALETTE[6], PALETTE[4]] });
  lines($('#c-oa'), { categories: d.years, series: [{ name: 'Open access', data: d.oa_share, area: true }], percent: true, colors: [PALETTE[1]] });
  lines($('#c-pf'), { categories: d.years, series: [{ name: 'Papers per faculty', data: d.per_faculty }], colors: [PALETTE[3]] });
  table($('#t-v'), { rows: d.top_venues, initialSort: { key: 'count', dir: -1 }, columns: [
    { key: 'venue', label: 'Venue', render: (r) => `<b>${esc(r.venue)}</b>` }, { key: 'kind', label: 'Type', render: (r) => KIND[r.kind] || r.kind },
    { key: 'quartile', label: 'Quartile', render: (r) => quart(r.quartile) || '<span class="muted">—</span>' }, { key: 'count', label: 'Papers', num: true }] });
}

async function impact(pane, d) {
  pane.innerHTML = `
    <div class="kpis mb" style="grid-template-columns:repeat(4,minmax(0,1fr))">
      ${kpi({ label: 'h-index', value: d.h_index })}${kpi({ label: 'i10 papers', value: num(d.i10), note: '10+ citations' })}
      ${kpi({ label: 'Field-weighted impact', value: d.fwci ?? '—', note: '1.0 = RICE average for the same field & year' })}${kpi({ label: 'Uncited', value: d.uncited_share, unit: '%' })}
    </div>
    <div class="grid g2 mb">${card('How citations are spread', '<div class="chart" id="c-h"></div>', { sub: 'Most papers collect a few citations; a few collect many.' })}
      ${card('Field-weighted impact by year', '<div class="chart" id="c-fw"></div>', { sub: 'Above 1.0 means more cited than comparable papers on RICE.' })}</div>
    <div class="grid g2 mb">${card('Citations per paper by quartile', '<div class="chart short" id="c-qc"></div>')}
      ${card('Does open access help?', `<div class="chart short" id="c-oa"></div><div class="muted" style="font-size:12.5px">Average citations per paper: open access ${d.oa_cpp.open} vs ${d.oa_cpp.closed} otherwise.</div>`)}</div>
    ${card('Most-cited papers', `<div class="list">${d.top_papers.map((p) => pubLine(p)).join('') || empty('No papers in range')}</div>`)}`;
  bars($('#c-h'), { categories: d.histogram.map((x) => x.bucket), series: [{ name: 'Papers', data: d.histogram.map((x) => x.count) }] });
  lines($('#c-fw'), { categories: d.by_year.map((x) => x.year), series: [{ name: 'FWCI', data: d.by_year.map((x) => x.fwci) }], colors: [PALETTE[2]] });
  bars($('#c-qc'), { categories: Object.keys(d.quartile_cpp), series: [{ name: 'Citations per paper', data: Object.values(d.quartile_cpp) }], colors: [PALETTE[3]] });
  bars($('#c-oa'), { categories: ['Open access', 'Not open access'], series: [{ name: 'Citations per paper', data: [d.oa_cpp.open, d.oa_cpp.closed] }], horizontal: true, colors: [PALETTE[1]] });
}

async function topics(pane, d) {
  pane.innerHTML = `
    ${card('Topic activity over time', '<div class="chart xl" id="c-hm"></div>', { sub: 'Papers per topic per year — darker means more. Click a cell to find the experts.' })}
    <div class="grid g3 mt">
      ${card('Rising', d.rising.length ? `<div class="list">${d.rising.map((r) => `<div class="it"><div class="body"><a class="ttl" href="#/discover/experts?q=${encodeURIComponent(r.topic)}">${esc(r.topic)}</a>
        <div class="meta">${r.recent} recent vs ${r.earlier} before</div></div><span class="delta up">+${r.growth}%</span></div>`).join('')}</div>` : empty('No topic is rising sharply'))}
      ${card('Cooling', d.declining.length ? `<div class="list">${d.declining.map((r) => `<div class="it"><div class="body"><div class="ttl">${esc(r.topic)}</div>
        <div class="meta">${r.recent} recent vs ${r.earlier} before</div></div><span class="delta down">${r.growth}%</span></div>`).join('')}</div>` : empty('No topic is cooling'))}
      ${card('Who leads the top topics', `<div class="list">${Object.entries(d.leaders).slice(0, 6).map(([t, ls]) => `<div class="it"><div class="body"><div class="ttl">${esc(t)}</div>
        <div class="meta">${ls.map((l) => `<a href="#/people/${l.id}">${esc(l.name)}</a> (${l.count})`).join(', ')}</div></div></div>`).join('')}</div>`)}
    </div>
    <div class="grid g-2-1 mt">${card('UN Sustainable Development Goals', '<div class="chart tall" id="c-sdg"></div>', { sub: 'RICE tags SDGs automatically from titles and keywords.' })}
      ${card('All topics', '<div id="t-t"></div>')}</div>`;
  heatmap($('#c-hm'), { x: d.years, y: d.heat_topics, data: d.heat, onClick: (p) => { location.hash = `#/discover/experts?q=${encodeURIComponent(d.heat_topics[p.value[1]])}`; } });
  bars($('#c-sdg'), { categories: d.sdg.map((s) => `SDG ${s.goal} · ${s.name}`), series: [{ name: 'Papers', data: d.sdg.map((s) => s.count) }], horizontal: true, colors: [PALETTE[2]] });
  table($('#t-t'), { rows: d.topics, pageSize: 10, initialSort: { key: 'count', dir: -1 }, columns: [
    { key: 'topic', label: 'Topic', render: (r) => `<a href="#/discover/experts?q=${encodeURIComponent(r.topic)}">${esc(r.topic)}</a>` },
    { key: 'count', label: 'Papers', num: true }, { key: 'trend', label: 'Trend', render: (r) => `<span class="st ${r.trend === 'rising' ? 'verified' : r.trend === 'declining' ? 'rejected' : 'completed'}">${r.trend}</span>` }] });
}

async function funding(pane, d) {
  pane.innerHTML = `
    <div class="kpis mb" style="grid-template-columns:repeat(4,minmax(0,1fr))">
      ${kpi({ label: 'Sanctioned', value: crore(d.total), note: `${d.projects} projects` })}${kpi({ label: 'Ongoing projects', value: d.ongoing })}
      ${kpi({ label: 'Proposal success rate', value: d.success_rate, unit: '%' })}${kpi({ label: 'Awaiting decision', value: d.submitted, note: 'submitted proposals' })}
    </div>
    <div class="grid g2 mb">${card('Money by agency', '<div class="chart tall" id="c-ag"></div>')}${card('Success rate by agency', '<div class="chart tall" id="c-sr"></div>', { sub: 'Sanctioned ÷ decided proposals.' })}</div>
    ${card('Where the money flows', '<div class="chart xl" id="c-sk"></div>', { sub: 'Sector → agency → department, in ₹ lakh.' })}
    <div class="grid g2 mt">${card('Sanctioned each year by sector', '<div class="chart" id="c-sy"></div>')}${card('Largest grants', `<div class="list">${d.top_projects.map((p) => `<div class="it"><div class="body">
      <div class="ttl">${esc(p.title)}</div><div class="meta"><b class="soft">${esc(p.agency)}</b><span>${esc(p.scheme || '')}</span><span>${p.start_year}–${p.end_year}</span>${p.pi ? `<a href="#/people/${p.pi.id}">${esc(p.pi.name)}</a>` : ''}</div></div>
      <b class="nowrap">${crore(p.amount)}</b></div>`).join('')}</div>`)}</div>`;
  bars($('#c-ag'), { categories: d.by_agency.map((a) => a.agency), series: [{ name: 'Sanctioned', data: d.by_agency.map((a) => a.amount) }], horizontal: true, fmt: crore });
  bars($('#c-sr'), { categories: d.by_agency.map((a) => a.agency), series: [{ name: 'Success rate', data: d.by_agency.map((a) => a.success) }], horizontal: true, percent: true, colors: [PALETTE[2]], fmt: (v) => `${v}%` });
  sankey($('#c-sk'), { ...d.sankey, fmt: (v) => crore(v) });
  bars($('#c-sy'), { categories: d.years, series: Object.entries(d.by_sector_year).map(([k, v]) => ({ name: k[0].toUpperCase() + k.slice(1), data: v })), stack: true, fmt: crore });
}

async function people(pane, d) {
  pane.innerHTML = `
    <div class="kpis mb" style="grid-template-columns:repeat(4,minmax(0,1fr))">
      ${kpi({ label: 'Faculty', value: d.faculty })}${kpi({ label: 'Research scholars', value: d.scholars })}
      ${kpi({ label: 'Output concentration', value: d.gini, note: 'Gini · 0 even, 1 one person' })}${kpi({ label: 'Top-fifth share', value: d.top_share, unit: '%', note: 'of all papers' })}
    </div>
    <div class="grid g2 mb">${card('Papers per faculty member', '<div class="chart" id="c-hi"></div>')}${card('Output by designation', '<div class="chart" id="c-bx"></div>', { sub: 'Box = middle half; line = median.' })}</div>
    <div class="grid g2 mb">${card('Papers with scholars or students as co-authors', '<div class="chart" id="c-ss"></div>')}${card('Supervision load', '<div class="chart" id="c-ml"></div>', { sub: 'Faculty by number of scholars and students they guide.' })}</div>
    <div class="grid g-2-1">${card('Researchers', '<div id="t-p"></div>')}
      ${card(`No verified paper in two years <span class="badge n">${d.inactive.length}</span>`, d.inactive.length ? `<div class="list">${d.inactive.slice(0, 14).map((r) => `<div class="it">${avatar(r, 'sm')}<div class="body">
        <a class="ttl" href="#/people/${r.id}">${esc(r.name)}</a><div class="meta">${esc(r.designation)} · ${esc(r.dept)} · ${r.pubs} papers overall</div></div></div>`).join('')}</div>` : empty('Everyone is publishing', '', 'party-popper'),
        { sub: 'A starting list for mentoring and seed grants — not a judgement.' })}</div>`;
  bars($('#c-hi'), { categories: d.histogram.map((x) => x.bucket), series: [{ name: 'Faculty', data: d.histogram.map((x) => x.count) }] });
  if (d.box.length) boxplot($('#c-bx'), { categories: d.box.map((b) => b.designation.replace(' Professor', ' Prof.')), boxes: d.box.map((b) => b.box) });
  lines($('#c-ss'), { categories: d.student_share.years, series: [{ name: 'Share of papers', data: d.student_share.values, area: true }], percent: true, colors: [PALETTE[1]] });
  bars($('#c-ml'), { categories: d.mentorship.map((m) => `${m.students}`), series: [{ name: 'Faculty', data: d.mentorship.map((m) => m.faculty) }], colors: [PALETTE[3]] });
  table($('#t-p'), { rows: d.rows, pageSize: 12, initialSort: { key: 'citations', dir: -1 }, columns: [
    { key: 'name', label: 'Name', render: (r) => `<a class="who" href="#/people/${r.id}">${avatar(r, 'sm')}<span><span class="nm">${esc(r.name)}</span><br><span class="ds">${esc(r.designation)} · ${esc(r.dept)}</span></span></a>` },
    { key: 'pubs', label: 'Papers', num: true }, { key: 'citations', label: 'Cites', num: true }, { key: 'h_index', label: 'h', num: true },
    { key: 'fwci', label: 'FWCI', num: true, render: (r) => r.fwci ?? '—', sort: (r) => r.fwci ?? -1 }, { key: 'funding', label: 'Grants', num: true, render: (r) => r.funding ? crore(r.funding) : '—' },
    { key: 'students', label: 'Guides', num: true }] });
}

async function collaboration(pane, d) {
  const totalBy = d.years.map((_, i) => Object.values(d.by_class).reduce((a, v) => a + v[i], 0));
  pane.innerHTML = `
    ${card('How far papers reach, year by year', '<div class="chart tall" id="c-cl"></div>', { sub: 'Share of each year\'s papers by widest collaboration.' })}
    <div class="grid g3 mt">${card('Top partner organisations', '<div class="chart tall" id="c-pa"></div>')}${card('International partner countries', '<div class="chart tall" id="c-co"></div>')}
      ${card('RICE institutions you publish with', d.rice_partners.length ? `<div class="list">${d.rice_partners.map((r) => `<div class="it"><div class="body"><a class="ttl" href="#/network/${r.id}">${esc(r.name)}</a></div><b>${r.count}</b></div>`).join('')}</div>` : empty('No joint papers with RICE institutions yet', 'Discover can suggest people to start with.', 'handshake'))}</div>
    ${d.dept_labels.length > 2 ? `<div class="mt">${card('Departments that write together', '<div class="chart xl" id="c-ch"></div>', { sub: 'Line thickness = joint papers between two departments.' })}</div>` : ''}`;
  bars($('#c-cl'), { categories: d.years, stack: true, percent: true, series: Object.entries(d.by_class).map(([k, v]) => ({ name: CLASS[k], data: v.map((x, i) => (totalBy[i] ? Math.round(1000 * x / totalBy[i]) / 10 : 0)) })), fmt: (v) => `${v}%` });
  bars($('#c-pa'), { categories: d.partners.map((x) => x.name), series: [{ name: 'Papers', data: d.partners.map((x) => x.count) }], horizontal: true, colors: [PALETTE[5]] });
  bars($('#c-co'), { categories: d.countries.map((x) => x.name), series: [{ name: 'Co-authors', data: d.countries.map((x) => x.count) }], horizontal: true, colors: [PALETTE[1]] });
  if (d.dept_labels.length > 2) chord($('#c-ch'), { labels: d.dept_labels, matrix: d.dept_matrix });
}

async function departments(pane, d) {
  pane.innerHTML = `${card('Productivity vs impact', '<div class="chart xl" id="c-sc"></div>', { sub: 'Right = more papers per faculty member · up = more citations per paper · bubble = funding.' })}
    <div class="mt">${card('Department scorecard', '<div id="t-d"></div>')}</div>`;
  scatter($('#c-sc'), { data: d.rows.map((r) => ({ x: r.pubs_per_faculty, y: r.cites_per_paper, size: r.funding_lakh, name: r.code + (r.inst !== store.inst?.short ? ` · ${r.inst}` : '') , r })),
    xName: 'Papers per faculty', yName: 'Citations per paper', sizeKey: 'size',
    fmt: (p) => `<b>${esc(p.data.raw.r.name)}</b><br>${p.data.raw.r.pubs_per_faculty} papers / faculty · ${p.data.raw.r.cites_per_paper} cites / paper<br>Grants ${crore(p.data.raw.r.funding_lakh)}` });
  table($('#t-d'), { rows: d.rows, pageSize: 20, initialSort: { key: 'publications', dir: -1 }, columns: [
    { key: 'name', label: 'Department', render: (r) => `<a href="javascript:void 0" data-d="${r.id}"><b>${esc(r.name)}</b></a>` },
    { key: 'faculty', label: 'Faculty', num: true }, { key: 'publications', label: 'Papers', num: true }, { key: 'pubs_per_faculty', label: '/ faculty', num: true },
    { key: 'cites_per_paper', label: 'Cites / paper', num: true }, { key: 'h_index', label: 'h', num: true }, { key: 'fwci', label: 'FWCI', num: true, render: (r) => r.fwci ?? '—' },
    { key: 'q1_share', label: 'Q1', num: true, render: (r) => pct(r.q1_share) }, { key: 'funding_lakh', label: 'Grants', num: true, render: (r) => crore(r.funding_lakh) },
    { key: 'patents', label: 'Patents', num: true }, { key: 'collab_share', label: 'Collab.', num: true, render: (r) => pct(r.collab_share) }] });
  pane.addEventListener('click', (e) => {
    const a = e.target.closest('[data-d]');
    if (a) location.hash = `#/analytics/overview?scope=department&dept=${a.dataset.d}`;
  });
}

async function graphTab(pane, st) {
  const d = await api(`/api/graph-analyses${qs({ y0: st.y0, y1: st.y1 })}`);
  const eng = d.engine_info || {};
  const link = (id, name) => (id ? `<a href="#/people/${id}">${esc(name)}</a>` : esc(name ?? ''));
  const cell = (row, key) => {
    const v = row[key];
    if (key === 'a') return link(row.a_id, v);
    if (key === 'b') return link(row.b_id, v);
    if (key === 'name') return link(row.id, v);
    if (key === 'topic') return `<a href="#/discover/experts?q=${encodeURIComponent(v)}">${esc(v)}</a>`;
    if (Array.isArray(v)) return `<span class="chips">${v.map((x) => `<span class="chip">${esc(x)}</span>`).join('')}</span>`;
    if (typeof v === 'boolean') return v ? 'Yes' : '—';
    return esc(v ?? '—');
  };
  pane.innerHTML = `
    <div class="row between mb"><div class="soft" style="max-width:760px">Questions answered by walking the research graph itself — co-authorship, topics, funders and partners — for ${esc(d.scope)}, ${d.range[0]}–${d.range[1]}.</div>
      <span class="engine ${eng.engine === 'neo4j' ? '' : 'off'}"><span class="dot"></span>${esc(eng.label || '')}</span></div>
    <div class="grid g2">${d.analyses.map((a) => `<section class="card analysis">
      <div class="hd"><h3>${esc(a.title)}</h3><span class="chip mono">${esc(a.uses)}</span><div class="sub">${esc(a.question)}</div></div>
      <div class="bd"><div class="callout" style="padding:10px 12px;margin-bottom:12px;font-size:13px">${icon('lightbulb', 'i-sm')}<span>${esc(a.why)}</span></div>
        ${a.error ? `<div class="callout warn">${icon('alert-triangle')}<span>${esc(a.error)}</span></div>` : a.rows.length ? `<div class="rows tbl-wrap"><table class="tbl"><thead><tr>${a.columns.map(([, l]) => `<th>${esc(l)}</th>`).join('')}</tr></thead>
        <tbody>${a.rows.map((r) => `<tr>${a.columns.map(([k]) => `<td class="${typeof r[k] === 'number' ? 'num' : ''}">${cell(r, k)}</td>`).join('')}</tr>`).join('')}</tbody></table></div>`
        : `<div class="empty" style="padding:18px">${icon('check-circle-2')}<b>Nothing to flag</b><div>No matches for this question in the selected years.</div></div>`}
        <details class="mt"><summary class="muted" style="cursor:pointer;font-size:12.5px;font-weight:700">Show the Cypher</summary><pre class="cypher mt">${esc(a.cypher)}</pre></details>
      </div></section>`).join('')}</div>`;
  paintIcons(pane);
}
export { radar };

import { api, qs, store } from '../api.js';
import { bars, lines, PALETTE, radar } from '../charts.js';
import { $, $$, avatar, card, crore, empty, esc, icon, kpi, num, paintIcons, pubLine, table } from '../ui.js';

const ACCESS = { network: ['Full network', 'Profiles and verified research'], summary: ['Summary only', 'Aggregate numbers for benchmarking'], name: ['Name only', 'This institution keeps its data private'] };

export async function render(el, { parts }) {
  if (parts[1]) return institution(el, +parts[1]);
  const r = await api('/api/network/institutions');
  const tenants = r.rows.filter((x) => !x.external);
  const tracked = r.rows.filter((x) => x.external);
  el.innerHTML = `<div class="ph"><div class="t"><div class="eyebrow">RICE network</div><h1>Network & benchmarks</h1>
      <p class="lead">Institutions on RICE choose how much they share. Sharing is reciprocal: ${esc(store.inst?.short || 'you')} share at <b>${esc(r.own_level)}</b> level, so you see peers at that level at most.</p></div>
      ${store.can('settings.manage') ? `<div class="acts"><a class="btn" href="#/admin/sharing">${icon('sliders-horizontal')}Change sharing</a></div>` : ''}</div>
    <div class="callout mb">${icon('shield-check')}<span>${esc(r.reciprocity)}</span></div>
    ${store.can('network.benchmark') ? `<div id="bench" class="mb"></div>` : ''}
    ${card('Institutions on RICE', `<div class="pgrid">${tenants.map((t) => `<a class="pcard" href="#/network/${t.id}">
      <div class="row" style="flex-wrap:nowrap"><span class="swatch" style="width:34px;height:34px;border-radius:10px;background:${esc(t.brand)};display:grid;place-items:center;color:#fff;font:700 10px var(--f-display)">${esc(t.short.slice(0, 4))}</span>
        <span style="min-width:0"><b>${esc(t.name)}</b>${t.self ? ' <span class="chip acc">You</span>' : ''}<br><span class="muted" style="font-size:12.5px">${esc(t.city || '')}, ${esc(t.state || '')} · est. ${t.established || '—'}</span></span></div>
      <div class="row"><span class="chip">${icon(t.access === 'network' ? 'eye' : t.access === 'summary' ? 'bar-chart-3' : 'eye-off', 'i-sm')}${esc(ACCESS[t.access][0])}</span><span class="chip">shares: ${esc(t.share_level)}</span></div>
      ${t.publications !== undefined ? `<div class="stats"><span><b>${num(t.researchers)}</b>researchers</span><span><b>${num(t.publications)}</b>papers</span><span><b>${t.h_index}</b>h-index</span></div>` : `<div class="muted" style="font-size:12.5px">${esc(ACCESS[t.access][1])}</div>`}</a>`).join('')}</div>`)}
    ${tracked.length ? `<div class="mt">${card(`Tracked externally <span class="badge n">${tracked.length}</span>`, `<div class="pgrid">${tracked.map((t) => `<a class="pcard" href="#/network/${t.id}">
      <div><b>${esc(t.name)}</b><br><span class="muted" style="font-size:12.5px">${esc(t.city || '')}${t.state ? ', ' + esc(t.state) : ''}</span></div>
      <div class="stats"><span><b>${t.researchers}</b>researchers</span><span>${esc(t.source || '')}</span></div></a>`).join('')}</div>`,
      { sub: 'Imported researcher lists (e.g. a SciVal export). RICE shows who is there and links out to Scopus — it does not invent their outputs.' })}</div>` : ''}`;
  paintIcons(el);
  if (store.can('network.benchmark')) bench($('#bench'));
}

async function bench(box) {
  const st = { ids: null, y0: 2019 };
  const draw = async () => {
    const d = await api(`/api/network/benchmark${qs({ ids: st.ids?.join(','), y0: st.y0 })}`);
    st.ids = st.ids || d.institutions.map((i) => i.id);
    const colorOf = Object.fromEntries(d.available.map((a, i) => [a.id, PALETTE[i % PALETTE.length]]));
    box.innerHTML = card('Benchmark', `
      <div class="row mb"><span class="muted" style="font-size:12.5px">Compare</span>${d.available.map((a) => `<button class="chip ${st.ids.includes(a.id) ? 'on' : ''}" data-b="${a.id}" ${a.id === d.self ? 'disabled' : ''}>${esc(a.short)}</button>`).join('')}
        <span class="muted" style="font-size:12.5px;margin-left:12px">Since</span><select class="input sm" id="b-y0" style="width:auto">${[2016, 2019, 2021, 2023].map((y) => `<option ${y === st.y0 ? 'selected' : ''}>${y}</option>`).join('')}</select></div>
      <div class="grid g2"><div class="chart xl" id="c-rd"></div><div id="t-b"></div></div>
      <div class="muted" style="font-size:12px;margin-top:8px">Each axis is scaled so the leader on that axis = 100. The RICE score blends output (35%), impact (20%), Q1 share (15%), patents (15%) and funding (15%), modelled on NIRF's research parameters — an estimate, not an official rank.</div>`,
      { sub: 'Only institutions that share at least summary data with you can be compared.' });
    radar($('#c-rd'), { indicators: d.axes.map((a) => ({ name: a.label, max: 100 })), colors: d.institutions.map((i) => colorOf[i.id]),
      series: d.institutions.map((i) => ({ name: i.short, value: d.axes.map((a) => i.normalised[a.key]), self: i.id === d.self })) });
    table($('#t-b'), { rows: d.institutions, pageSize: 10, initialSort: { key: 'rice_score', dir: -1 }, columns: [
      { key: 'rank', label: '#', num: true }, { key: 'short', label: 'Institution', render: (r) => `<b>${esc(r.short)}</b>${r.id === d.self ? ' <span class="chip acc">You</span>' : ''}` },
      { key: 'rice_score', label: 'RICE score', num: true }, { key: 'output', label: 'Papers / fac.', num: true, render: (r) => r.raw.output, sort: (r) => r.raw.output },
      { key: 'impact', label: 'Cites / paper', num: true, render: (r) => r.raw.impact, sort: (r) => r.raw.impact },
      { key: 'funding', label: '₹L / fac.', num: true, render: (r) => r.raw.funding, sort: (r) => r.raw.funding },
      { key: 'growth', label: '3-yr growth', num: true, render: (r) => `${r.raw.growth}%`, sort: (r) => r.raw.growth }] });
    paintIcons(box);
    $$('[data-b]', box).forEach((b) => b.onclick = () => { const id = +b.dataset.b; st.ids = st.ids.includes(id) ? st.ids.filter((x) => x !== id) : [...st.ids, id]; draw(); });
    $('#b-y0').onchange = (e) => { st.y0 = +e.target.value; draw(); };
  };
  box.innerHTML = '<div class="skel" style="height:420px"></div>';
  try { await draw(); } catch (e) { box.innerHTML = ''; }
}

async function institution(el, id) {
  const d = await api(`/api/network/institution/${id}`);
  const head = `<div class="ph"><div class="t"><div class="eyebrow"><a href="#/network">Network</a> · ${esc(d.external ? 'Tracked externally' : ACCESS[d.access][0])}</div>
    <h1>${esc(d.name)}</h1><p class="lead">${esc(d.tagline || '')}${d.city ? ` — ${esc(d.city)}, ${esc(d.state || '')}` : ''}</p></div></div>`;
  if (d.external) {
    el.innerHTML = head + card(`${d.people.length} researchers`, `<div class="callout mb">${icon('info')}<span>Imported from ${esc(d.source || 'an external list')}. RICE lists who works here and links to their Scopus profile; their outputs live in Scopus.</span></div>
      <div id="t-x"></div>`);
    paintIcons(el);
    table($('#t-x'), { rows: d.people, pageSize: 20, initialSort: { key: 'name', dir: 1 }, columns: [
      { key: 'name', label: 'Researcher', render: (r) => `<span class="who">${avatar(r, 'sm')}<b>${esc(r.name)}</b></span>` },
      { key: 'dept_name', label: 'Group' }, { key: 'interests', label: 'Domain', render: (r) => esc(r.interests.join(', ')) },
      { key: 'scopus_id', label: 'Scopus', render: (r) => (r.scopus_id ? `<a href="https://www.scopus.com/authid/detail.uri?authorId=${esc(r.scopus_id)}" target="_blank" rel="noopener">${esc(r.scopus_id)} ${icon('external-link', 'i-sm')}</a>` : '—') }] });
    return;
  }
  if (d.access === 'name') {
    el.innerHTML = head + empty(`${d.name} keeps its research private`, 'You can see that they are on RICE, nothing more.', 'eye-off');
    paintIcons(el);
    return;
  }
  const k = d.kpis;
  el.innerHTML = head + `
    <div class="kpis mb">${kpi({ label: 'Papers since 2019', value: num(k.publications), delta: k.publications_growth })}${kpi({ label: 'Citations', value: num(k.citations) })}
      ${kpi({ label: 'h-index', value: k.h_index })}${kpi({ label: 'Q1 share', value: k.q1_share, unit: '%' })}${kpi({ label: 'Grants', value: crore(k.funding_lakh) })}${kpi({ label: 'Faculty', value: k.faculty })}</div>
    <div class="grid g2 mb">${card('Papers per year', '<div class="chart" id="c-p"></div>')}${card('Citations to each year\'s papers', '<div class="chart" id="c-c"></div>')}</div>
    ${d.access === 'network' ? `<div class="grid g-2-1">
      ${card('Most-cited researchers', `<div class="list">${(d.top_researchers || []).map((r) => `<div class="it"><a class="who" href="#/people/${r.id}" style="flex:1">${avatar(r, 'sm')}<span><span class="nm">${esc(r.name)}</span><br><span class="ds">${esc(r.designation)} · ${esc(r.dept)}</span></span></a>
        <span class="muted nowrap" style="font-size:12.5px">${r.pubs} papers · ${r.citations} cites</span></div>`).join('')}</div>`)}
      <div class="stack">${card('Research topics', `<div class="chips">${(d.topics || []).map((t) => `<a class="chip ${t.trend === 'rising' ? 'acc' : ''}" href="#/discover/experts?q=${encodeURIComponent(t.topic)}">${esc(t.topic)} · ${t.count}</a>`).join('')}</div>`)}
        ${d.joint ? card(`Joint papers with ${esc(store.inst?.short || 'you')} <span class="badge n">${d.joint.count}</span>`, d.joint.papers.length ? `<div class="list">${d.joint.papers.map((p) => pubLine(p)).join('')}</div>` : empty('No joint papers yet', 'Discover can suggest who to start with.', 'handshake')) : ''}</div></div>`
      : `<div class="callout">${icon('bar-chart-3')}<span>${esc(d.name)} shares summary numbers only, so names and papers are hidden.</span></div>`}`;
  paintIcons(el);
  bars($('#c-p'), { categories: d.trend.years, series: [{ name: 'Papers', data: d.trend.publications }] });
  lines($('#c-c'), { categories: d.trend.years, series: [{ name: 'Citations', data: d.trend.citations, area: true }], colors: [PALETTE[1]] });
}

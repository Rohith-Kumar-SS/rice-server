import { api, qs, store } from '../api.js';
import { ink, mount, OTHER, PALETTE } from '../charts.js';
import { $, $$, avatar, esc, fail, icon, marks, modal, num, paintIcons, toast } from '../ui.js';

const MODES = [
  { k: 'people', label: 'People', ic: 'users', help: 'Who publishes and runs projects with whom' },
  { k: 'departments', label: 'Departments', ic: 'layers', help: 'Which departments write together' },
  { k: 'institutions', label: 'Institutions', ic: 'building-2', help: 'Partner organisations, inside and outside RICE' },
  { k: 'topics', label: 'Topics', ic: 'tags', help: 'Research themes that appear on the same papers' },
  { k: 'mentorship', label: 'Mentorship', ic: 'git-fork', help: 'Supervisors and the scholars they guide' },
];
const SIZE_BY = { degree: 'Collaborators', strength: 'Joint outputs', betweenness: 'Brokerage (betweenness)', pagerank: 'Influence (PageRank)', pubs: 'Publications' };
const ROLE_COLOR = { hod: PALETTE[0], faculty: PALETTE[0], scholar: PALETTE[1], student: PALETTE[2], staff: PALETTE[3] };
const EDGE_KIND = { intra_dept: 'Same department', inter_dept: 'Across departments', cross_inst: 'Across institutions' };

export async function render(el, { query }) {
  const me = store.me;
  const years = me.years;
  const st = {
    mode: query.mode || 'people', scope: query.scope || 'institution', dept: query.dept ? +query.dept : null,
    y0: years[0], y1: years[1], students: true, colorBy: 'community', sizeBy: 'strength', hidden: new Set(),
    data: null, selected: null, ego: query.ego ? +query.ego : null, path: null, focusComm: null,
  };
  if (!store.can('graph.network') && st.scope === 'network') st.scope = 'institution';
  el.innerHTML = `<div class="gx">
    <aside class="gx-side" id="gx-side"></aside>
    <section class="gx-stage"><div class="gx-canvas" id="gx-canvas" role="img" aria-label="Collaboration graph"></div>
      <div class="gx-hud" id="gx-hud"></div>
      <div class="gx-tools no-print">
        <button class="iconbtn" id="z-in" title="Zoom in" aria-label="Zoom in">${icon('zoom-in')}</button>
        <button class="iconbtn" id="z-out" title="Zoom out" aria-label="Zoom out">${icon('zoom-out')}</button>
        <button class="iconbtn" id="z-reset" title="Fit to screen" aria-label="Fit to screen">${icon('maximize')}</button>
        <button class="iconbtn" id="z-png" title="Save as image" aria-label="Save as image">${icon('image-down')}</button>
      </div>
      <div id="gx-detail"></div>
    </section></div>`;
  paintIcons(el);
  let chart = null, zoom = 1, view = null;

  const side = () => {
    const d = st.data;
    const s = d?.summary || {};
    const isPeople = st.mode === 'people' && !st.ego;
    const colorOpts = st.ego ? [] : st.mode === 'people' ? [['community', 'Community'], ['dept', 'Department'], ['inst', 'Institution'], ['role', 'Role']]
      : st.mode === 'topics' ? [['trend', 'Trend'], ['community', 'Cluster']] : [];
    if (st.mode === 'topics' && !['trend', 'community'].includes(st.colorBy)) st.colorBy = 'trend';
    if (st.mode === 'people' && !['community', 'dept', 'inst', 'role'].includes(st.colorBy)) st.colorBy = 'community';
    $('#gx-side').innerHTML = `
      <div><div class="eyebrow" style="margin:0 0 4px">Graph explorer</div>
        <div style="font:600 19px var(--f-display);letter-spacing:-.01em">${st.ego ? 'Knowledge graph' : esc(MODES.find((m) => m.k === st.mode).label)}</div>
        <div class="muted" style="font-size:13px">${st.ego ? 'One researcher, their co-authors, topics, projects and partner organisations.' : esc(MODES.find((m) => m.k === st.mode).help)}</div></div>
      ${st.ego ? `<button class="btn sm" id="ego-back">${icon('arrow-left', 'i-sm')}Back to the full graph</button>` : `
      <div><h4>Lens</h4><div class="seg" style="width:100%">${MODES.map((m) => `<button data-mode="${m.k}" class="${st.mode === m.k ? 'on' : ''}" title="${esc(m.help)}">${icon(m.ic, 'i-sm')}${m.label}</button>`).join('')}</div></div>
      <div><h4>Scope</h4><div class="seg">
        <button data-scope="institution" class="${st.scope === 'institution' ? 'on' : ''}">${esc(store.inst?.short || 'Institution')}</button>
        <button data-scope="department" class="${st.scope === 'department' ? 'on' : ''}">Department</button>
        ${store.can('graph.network') ? `<button data-scope="network" class="${st.scope === 'network' ? 'on' : ''}">RICE network</button>` : ''}</div>
        ${st.scope === 'department' ? `<select class="input sm mt" id="g-dept" style="margin-top:8px">${me.departments.map((x) => `<option value="${x.id}" ${x.id === (st.dept || me.user.dept_id) ? 'selected' : ''}>${esc(x.name)}</option>`).join('')}</select>` : ''}
        ${st.scope === 'network' ? `<div class="muted" style="font-size:12px;margin-top:6px">Includes institutions that share at network level with ${esc(store.inst?.short || 'you')}.</div>` : ''}</div>
      <div><h4>Years</h4><div class="row" style="flex-wrap:nowrap">${ysel('y0', st.y0, years)}<span class="muted">to</span>${ysel('y1', st.y1, years)}</div></div>
      ${isPeople ? `<div class="stack" style="gap:8px"><label class="switch"><input type="checkbox" id="g-stu" ${st.students ? 'checked' : ''}>Include scholars &amp; students</label></div>` : ''}
      ${colorOpts.length ? `<div><h4>Colour by</h4><div class="seg">${colorOpts.map(([k, l]) => `<button data-color="${k}" class="${st.colorBy === k ? 'on' : ''}">${l}</button>`).join('')}</div></div>` : ''}
      ${isPeople ? `<div><h4>Size by</h4><select class="input sm" id="g-size">${Object.entries(SIZE_BY).map(([k, l]) => `<option value="${k}" ${st.sizeBy === k ? 'selected' : ''}>${l}</option>`).join('')}</select></div>` : ''}`}
      <div><h4>Find</h4><input class="input sm" id="g-find" list="g-names" placeholder="Type a name and press Enter"><datalist id="g-names"></datalist></div>
      ${isPeople ? `<div><h4>Shortest path</h4><div class="stack" style="gap:6px">
        <input class="input sm" id="p-a" list="g-names" placeholder="From"><input class="input sm" id="p-b" list="g-names" placeholder="To">
        <div class="row"><button class="btn sm" id="p-go">${icon('route', 'i-sm')}Find path</button>${st.path ? '<button class="btn sm ghost" id="p-clear">Clear</button>' : ''}</div>
        <div id="p-out"></div></div></div>` : ''}
      <div><h4>Legend</h4><div class="gx-legend" id="g-legend"></div></div>
      ${d ? `<div><h4>Reading this graph</h4><div class="stack" style="gap:8px;font-size:13.5px;line-height:1.55">${explain(d).map((x, i) => `<div>${marks(x, i)}</div>`).join('')}</div></div>` : ''}
      ${isPeople && d?.communities?.length ? `<div><h4>Communities</h4><div class="stack" style="gap:6px">${d.communities.slice(0, 8).map((c) => `<div class="comm ${st.focusComm === c.id ? 'on' : ''}" data-comm="${c.id}" style="${st.focusComm === c.id ? 'border-color:var(--accent);background:var(--accent-soft)' : ''}">
        <div class="row between" style="flex-wrap:nowrap"><b style="display:flex;gap:8px;align-items:center"><span class="sw" style="width:10px;height:10px;border-radius:50%;background:${c.id < 8 ? PALETTE[c.id] : OTHER}"></span>${c.size} people</b><span class="muted" style="font-size:12px">${esc(c.depts.join(' · '))}</span></div>
        <div class="muted" style="font-size:12.5px;margin-top:2px">${esc(c.topics.join(', '))}</div>
        <div style="font-size:12.5px;margin-top:2px">Hub: ${esc(c.hub.name)}</div></div>`).join('')}</div></div>
      <div><h4>Brokers</h4><div class="muted" style="font-size:12.5px;margin-bottom:6px">People who connect groups that otherwise wouldn't meet.</div>
        <div class="stack" style="gap:4px">${d.brokers.slice(0, 6).map((b) => `<a class="row" href="javascript:void 0" data-sel="${b.id}" style="flex-wrap:nowrap;color:var(--ink);font-size:13.5px">${avatar(b, 'sm')}<span style="flex:1;min-width:0">${esc(b.name)}<br><span class="muted" style="font-size:12px">${esc(b.dept)} · ${esc(b.inst)}</span></span><span class="mono muted">${b.betweenness}</span></a>`).join('')}</div></div>` : ''}`;
    paintIcons($('#gx-side'));
    wireSide();
  };

  const ysel = (name, v, yrs) => {
    let o = '';
    for (let y = yrs[1]; y >= yrs[0]; y--) o += `<option ${y === v ? 'selected' : ''}>${y}</option>`;
    return `<select class="input sm" id="g-${name}">${o}</select>`;
  };

  const wireSide = () => {
    $$('[data-mode]').forEach((b) => b.onclick = () => { st.mode = b.dataset.mode; st.hidden.clear(); st.selected = null; st.path = null; st.focusComm = null; load(); });
    $$('[data-scope]').forEach((b) => b.onclick = () => { st.scope = b.dataset.scope; st.selected = null; st.path = null; st.focusComm = null; load(); });
    $$('[data-color]').forEach((b) => b.onclick = () => { st.colorBy = b.dataset.color; st.hidden.clear(); draw(); side(); });
    $('#g-dept')?.addEventListener('change', (e) => { st.dept = +e.target.value; load(); });
    $('#g-y0')?.addEventListener('change', (e) => { st.y0 = +e.target.value; load(); });
    $('#g-y1')?.addEventListener('change', (e) => { st.y1 = +e.target.value; load(); });
    $('#g-stu')?.addEventListener('change', (e) => { st.students = e.target.checked; load(); });
    $('#g-size')?.addEventListener('change', (e) => { st.sizeBy = e.target.value; draw(); });
    $('#ego-back')?.addEventListener('click', () => { st.ego = null; st.selected = null; load(); });
    $$('[data-comm]').forEach((c) => c.onclick = () => { st.focusComm = st.focusComm === +c.dataset.comm ? null : +c.dataset.comm; draw(); side(); });
    $$('[data-sel]').forEach((a) => a.onclick = () => select(+a.dataset.sel, true));
    const names = $('#g-names');
    if (names && st.data) names.innerHTML = st.data.nodes.slice(0, 2000).map((n) => `<option value="${esc(n.name)}">`).join('');
    const find = $('#g-find');
    if (find) find.onkeydown = (e) => {
      if (e.key !== 'Enter') return;
      const q = find.value.trim().toLowerCase();
      const n = st.data.nodes.find((x) => x.name.toLowerCase() === q) || st.data.nodes.find((x) => x.name.toLowerCase().includes(q));
      if (n) select(n.id, true); else toast('No one by that name in this graph', 'err');
    };
    $('#p-go')?.addEventListener('click', findPath);
    $('#p-clear')?.addEventListener('click', () => { st.path = null; draw(); side(); });
    legend();
  };

  const byName = (nm) => st.data.nodes.find((x) => x.name.toLowerCase() === nm.trim().toLowerCase());
  const findPath = async () => {
    const a = byName($('#p-a').value), b = byName($('#p-b').value);
    if (!a || !b) return toast('Pick both people from the list', 'err');
    try {
      const r = await api(`/api/graph-path${qs({ a: a.id, b: b.id, scope: st.scope === 'network' ? 'network' : 'institution' })}`);
      if (r.error) { $('#p-out').innerHTML = `<div class="muted" style="font-size:13px">${esc(r.error)}</div>`; return; }
      st.path = r;
      draw();
      side();
      $('#p-a').value = a.name; $('#p-b').value = b.name;
      $('#p-out').innerHTML = `<div style="font-size:13px"><b>${r.hops} step${r.hops === 1 ? '' : 's'}</b> apart</div>
        <div class="stack" style="gap:4px;margin-top:6px">${r.path.map((p, i) => `<div style="font-size:12.5px"><b>${esc(p.name)}</b> <span class="muted">${esc(p.dept)} · ${esc(p.inst)}</span>
        ${r.steps[i] ? `<div class="muted" style="padding-left:10px;border-left:2px solid var(--line-2);margin:3px 0 3px 4px">${r.steps[i].example ? `via “${esc(r.steps[i].example.title)}” (${r.steps[i].example.year})` : 'via a joint project'}</div>` : ''}</div>`).join('')}</div>`;
    } catch (e) { fail(e); }
  };

  // ── colour & size ─────────────────────────────────────────────────────────
  const catOf = (n) => {
    if (st.ego) return { key: n.kind, label: { person: 'Researcher', topic: 'Topic', project: 'Project', org: 'Partner organisation' }[n.kind] };
    switch (st.mode) {
      case 'people':
        if (st.colorBy === 'community') return { key: 'c' + n.community, label: `Community ${n.community + 1}`, idx: n.community };
        if (st.colorBy === 'dept') return { key: n.dept, label: n.dept_name || n.dept };
        if (st.colorBy === 'inst') return { key: n.inst, label: n.inst };
        return { key: n.role === 'hod' ? 'faculty' : n.role, label: { faculty: 'Faculty', scholar: 'Scholar', student: 'Student', staff: 'Staff' }[n.role === 'hod' ? 'faculty' : n.role] };
      case 'institutions': return n.kind === 'rice' ? { key: 'rice', label: 'RICE institution' } : (n.country && n.country !== 'India') ? { key: 'intl', label: 'International partner' } : { key: 'nat', label: 'Indian partner' };
      case 'departments': return { key: n.inst, label: n.inst };
      case 'topics': return st.colorBy === 'trend' ? { key: n.trend, label: { rising: 'Rising', steady: 'Steady', declining: 'Declining' }[n.trend] } : { key: 'c' + n.community, label: `Cluster ${n.community + 1}`, idx: n.community };
      case 'mentorship': return { key: n.role === 'hod' ? 'faculty' : n.role, label: n.students ? 'Supervisor' : { scholar: 'PhD scholar', student: 'Student', faculty: 'Faculty' }[n.role === 'hod' ? 'faculty' : n.role] || n.role };
      default: return { key: 'n', label: 'Node' };
    }
  };
  let colorMap = {};
  const buildColors = () => {
    colorMap = {};
    const counts = {};
    st.data.nodes.forEach((n) => { const c = catOf(n); counts[c.key] = counts[c.key] || { ...c, n: 0 }; counts[c.key].n++; });
    const fixed = { rising: PALETTE[2], steady: PALETTE[0], declining: PALETTE[4], rice: PALETTE[0], nat: PALETTE[5], intl: PALETTE[1],
      person: PALETTE[0], topic: PALETTE[2], project: PALETTE[3], org: PALETTE[1], faculty: PALETTE[0], scholar: PALETTE[1], student: PALETTE[2], staff: PALETTE[3] };
    const cats = Object.values(counts).sort((a, b) => (a.idx ?? 99) - (b.idx ?? 99) || b.n - a.n);
    let i = 0;
    cats.forEach((c) => {
      if (fixed[c.key] && !c.key.startsWith('c')) c.color = fixed[c.key];
      else if (c.idx !== undefined) c.color = c.idx < PALETTE.length ? PALETTE[c.idx] : OTHER;
      else c.color = i < PALETTE.length ? PALETTE[i++] : OTHER;
      colorMap[c.key] = c;
    });
    return cats;
  };
  const sizeOf = (n, max) => {
    if (st.ego) return n.focus ? 46 : n.kind === 'person' ? 12 + Math.sqrt(n.degree) * 3 : n.kind === 'topic' ? 16 : 13;
    let v;
    if (st.mode === 'people') v = st.sizeBy === 'pubs' ? n.pubs : n[st.sizeBy];
    else if (st.mode === 'topics') v = n.count;
    else if (st.mode === 'mentorship') v = n.students + 0.6;
    else v = n.pubs;
    return 6 + 34 * Math.sqrt(Math.max(0, v || 0) / (max || 1));
  };

  const legend = () => {
    const box = $('#g-legend');
    if (!box || !st.data) return;
    const cats = Object.values(colorMap).sort((a, b) => b.n - a.n).slice(0, 12);
    box.innerHTML = cats.map((c) => `<div class="lg ${st.hidden.has(c.key) ? 'off' : ''}" data-cat="${esc(c.key)}" role="button" tabindex="0"><span class="sw" style="background:${c.color}"></span>${esc(c.label)}<span class="c">${c.n}</span></div>`).join('')
      + (st.mode === 'people' && !st.ego ? `<div class="muted" style="font-size:12px;margin-top:6px">Lines: <span style="color:${PALETTE[1]}">━</span> across institutions · <span style="color:${PALETTE[0]}">━</span> across departments · <span style="color:${ink().line2}">━</span> same department</div>` : '');
    $$('[data-cat]', box).forEach((x) => x.onclick = () => { st.hidden.has(x.dataset.cat) ? st.hidden.delete(x.dataset.cat) : st.hidden.add(x.dataset.cat); draw(); legend(); });
  };

  // ── draw ──────────────────────────────────────────────────────────────────
  const draw = () => {
    const d = st.data;
    if (!d) return;
    buildColors();
    const k = ink();
    const visible = d.nodes.filter((n) => !st.hidden.has(catOf(n).key));
    const vis = new Set(visible.map((n) => n.id));
    const pathIds = new Set(st.path ? st.path.path.map((p) => p.id) : []);
    const metricMax = Math.max(...visible.map((n) => (st.mode === 'people' ? (st.sizeBy === 'pubs' ? n.pubs : n[st.sizeBy]) : st.mode === 'topics' ? n.count : st.mode === 'mentorship' ? n.students + 0.6 : n.pubs) || 0), 1);
    const ranked = [...visible].sort((a, b) => sizeOf(b, metricMax) - sizeOf(a, metricMax));
    const labelSet = new Set(ranked.slice(0, st.ego ? 80 : st.mode === 'people' ? 18 : st.mode === 'mentorship' ? 12 : 60).map((n) => n.id));
    const dim = (n) => (st.path && !pathIds.has(n.id)) || (st.focusComm !== null && n.community !== st.focusComm);
    const nodes = visible.map((n) => {
      const c = colorMap[catOf(n).key];
      const faded = dim(n);
      return {
        id: String(n.id), name: n.name, x: n.x, y: n.y, raw: n, symbolSize: sizeOf(n, metricMax),
        itemStyle: { color: c.color, opacity: faded ? 0.12 : 1, borderColor: n.focus || pathIds.has(n.id) || n.id === st.selected ? '#FFE45C' : k.card, borderWidth: n.focus || pathIds.has(n.id) || n.id === st.selected ? 4 : 1.5 },
        label: { show: !faded && (labelSet.has(n.id) || pathIds.has(n.id) || n.focus || n.id === st.selected || st.mode === 'departments' || st.mode === 'institutions' && n.kind === 'rice'),
          formatter: st.mode === 'departments' ? n.label : st.mode === 'institutions' ? n.short : (n.name.length > 26 ? n.name.slice(0, 24) + '…' : n.name) },
      };
    });
    const edgeColor = (e) => (st.mode === 'people' || st.mode === 'departments') ? (e.kind === 'cross_inst' ? PALETTE[1] : e.kind === 'inter_dept' ? PALETTE[0] : k.line2) : k.line2;
    const pathEdges = new Set();
    if (st.path) st.path.path.forEach((p, i) => { if (i) { pathEdges.add(`${st.path.path[i - 1].id}|${p.id}`); pathEdges.add(`${p.id}|${st.path.path[i - 1].id}`); } });
    const wmax = Math.max(...d.edges.map((e) => e.weight), 1);
    const links = d.edges.filter((e) => vis.has(e.source) && vis.has(e.target)).map((e) => {
      const onPath = pathEdges.has(`${e.source}|${e.target}`);
      const faded = (st.path && !onPath) || (st.focusComm !== null && !(byId[e.source]?.community === st.focusComm && byId[e.target]?.community === st.focusComm));
      return { source: String(e.source), target: String(e.target), value: e.weight, raw: e,
        lineStyle: { color: onPath ? '#E8A400' : edgeColor(e), width: onPath ? 4 : 0.6 + 3.2 * Math.sqrt(e.weight / wmax), opacity: faded ? 0.04 : (e.kind === 'intra_dept' ? 0.45 : 0.6), curveness: st.mode === 'mentorship' ? 0 : 0.12 } };
    });
    const option = {
      animationDurationUpdate: 500,
      tooltip: { backgroundColor: k.card, borderColor: k.line2, textStyle: { color: k.t1, fontSize: 12.5 }, extraCssText: 'border-radius:12px;box-shadow:0 12px 30px -12px rgba(20,32,74,.35);',
        formatter: (p) => p.dataType === 'edge' ? edgeTip(p.data.raw) : nodeTip(p.data.raw) },
      series: [{
        type: 'graph', layout: 'none', roam: true, zoom, center: view, scaleLimit: { min: 0.2, max: 12 }, data: nodes, links, draggable: false,
        edgeSymbol: st.mode === 'mentorship' ? ['none', 'arrow'] : ['none', 'none'], edgeSymbolSize: 6,
        label: { position: 'right', fontSize: 11.5, color: k.t1, fontFamily: 'Hanken Grotesk', fontWeight: 600, textBorderColor: k.card, textBorderWidth: 3 },
        labelLayout: { hideOverlap: true },
        emphasis: { focus: 'adjacency', label: { show: true }, lineStyle: { opacity: 0.9 } },
        blur: { itemStyle: { opacity: 0.12 }, lineStyle: { opacity: 0.03 } },
      }],
    };
    if (!chart) {
      chart = mount($('#gx-canvas'), option);
      chart.on('click', (p) => { if (p.dataType === 'node') select(p.data.raw.id); });
      chart.getZr().on('click', (e) => { if (!e.target) { st.selected = null; $('#gx-detail').innerHTML = ''; } });
      chart.on('graphRoam', () => { const o = chart.getOption().series[0]; zoom = o.zoom; view = o.center; });
    } else {
      chart.setOption(option, { replaceMerge: ['series'] });
    }
    hud();
  };
  let byId = {};

  const nodeTip = (n) => {
    if (!n) return '';
    if (st.ego) return `<b>${esc(n.name)}</b><br>${esc({ person: n.inst, topic: 'Topic', project: n.agency, org: 'Partner organisation' }[n.kind] || '')}`;
    if (st.mode === 'people' || st.mode === 'mentorship') return `<b>${esc(n.name)}</b><br>${esc(n.designation || '')} · ${esc(n.dept)} · ${esc(n.inst)}<br>${st.mode === 'people' ? `${n.degree} collaborators · ${n.pubs} papers${n.bridge ? '<br><b>Bridge</b> — links otherwise separate groups' : ''}` : `${n.students} supervisees`}`;
    if (st.mode === 'topics') return `<b>${esc(n.name)}</b><br>${n.count} papers · ${n.trend}${n.trend === 'rising' ? ` (+${n.growth}%)` : ''}`;
    if (st.mode === 'institutions') return `<b>${esc(n.name)}</b><br>${n.kind === 'rice' ? 'On RICE' : esc(n.country || 'Partner')} · ${n.pubs} papers`;
    return `<b>${esc(n.name)}</b><br>${esc(n.inst)} · ${n.pubs} papers`;
  };
  const edgeTip = (e) => {
    const a = byId[e.source], b = byId[e.target];
    const head = `<b>${esc(a?.name || '')}</b> ↔ <b>${esc(b?.name || '')}</b>`;
    if (st.mode === 'people') return `${head}<br>${e.pubs} joint paper${e.pubs === 1 ? '' : 's'}${e.projects ? ` · ${e.projects} joint project${e.projects === 1 ? '' : 's'}` : ''}<br><span style="color:${ink().t3}">${EDGE_KIND[e.kind] || ''}</span>`;
    if (st.mode === 'mentorship') return `${esc(a?.name || '')} supervises ${esc(b?.name || '')}`;
    return `${head}<br>${e.weight} shared paper${e.weight === 1 ? '' : 's'}`;
  };

  const hud = () => {
    const s = st.data.summary;
    const pills = [['nodes', s.nodes], ['links', s.edges]];
    if (s.communities !== undefined) pills.push(['communities', s.communities]);
    if (s.modularity !== undefined) pills.push(['modularity', s.modularity]);
    if (s.avg_path !== undefined) pills.push(['avg. steps apart', s.avg_path]);
    if (s.avg_clustering !== undefined) pills.push(['clustering', s.avg_clustering]);
    if (s.cross_inst) pills.push(['cross-institution links', s.cross_inst]);
    if (s.supervisors) pills.push(['supervisors', s.supervisors]);
    if (s.coauthors !== undefined) pills.push(['co-authors', s.coauthors]);
    const eng = st.data.engine_info || {};
    $('#gx-hud').innerHTML = pills.map(([l, v]) => `<span class="stat-pill"><b>${typeof v === 'number' ? num(v) : v}</b>${l}</span>`).join('')
      + `<span class="stat-pill">${esc(st.scope === 'network' ? 'RICE network' : st.scope === 'department' ? 'Department' : store.inst?.short || '')} · ${st.y0}–${st.y1}</span>`
      + `<button class="stat-pill" id="eng-pill" style="cursor:pointer;display:inline-flex;gap:6px;align-items:center" title="${esc(eng.note || 'Show the Cypher behind this view')}">
          <span style="width:8px;height:8px;border-radius:50%;background:${st.data.engine === 'neo4j' ? '#12A66A' : '#C99400'}"></span>${esc(eng.label || st.data.engine || '')}
          ${st.data.cypher ? `${icon('code-2', 'i-sm')}` : ''}</button>`;
    paintIcons($('#gx-hud'));
    $('#eng-pill').onclick = () => showCypher(st.data);
  };

  // ── selection & detail ────────────────────────────────────────────────────
  const select = (id, center = false) => {
    const n = byId[id];
    if (!n) return;
    st.selected = id;
    if (center) { zoom = Math.max(zoom, 2.2); view = [n.x, n.y]; }
    draw();
    const nb = st.data.edges.filter((e) => e.source === id || e.target === id).map((e) => ({ e, o: byId[e.source === id ? e.target : e.source] })).filter((x) => x.o).sort((a, b) => b.e.weight - a.e.weight);
    let body = '';
    const isPerson = st.ego ? n.kind === 'person' : (st.mode === 'people' || st.mode === 'mentorship');
    const pid = st.ego ? n.ref : n.id;
    if (isPerson) {
      const person = st.ego ? null : n;
      body = `<div class="row" style="flex-wrap:nowrap;gap:12px">${avatar(n, 'lg')}<div style="min-width:0"><div style="font:600 17px var(--f-display)">${esc(n.name)}</div>
        <div class="muted" style="font-size:13px">${esc([n.designation, n.dept_name || n.dept, n.inst].filter(Boolean).join(' · '))}</div>
        ${n.bridge ? '<span class="chip acc" style="margin-top:6px">Bridge — links otherwise separate groups</span>' : ''}</div></div>`;
      if (person && st.mode === 'people') {
        body += `<div class="metric-grid mt">${[['Collaborators', n.degree], ['Joint outputs', n.strength], ['Brokerage', n.betweenness], ['Influence', n.pagerank], ['Clustering', n.clustering], ['Core level', n.core]].map(([k2, v]) =>
          `<div class="metric"><div class="k">${k2}</div><div class="v">${v}</div></div>`).join('')}</div>
          <div class="muted" style="font-size:12px;margin-top:6px">Community ${n.community + 1} · ${n.pubs} papers in total</div>`;
      }
    } else {
      const sub = st.ego ? ({ topic: 'Research topic', project: `Project · ${n.agency || ''}`, org: 'Partner organisation' }[n.kind] || '')
        : st.mode === 'topics' ? `${n.count} papers · ${n.trend}` : `${n.inst || n.country || ''} · ${n.pubs} papers`;
      body = `<div style="font:600 17px var(--f-display)">${esc(n.name)}</div><div class="muted" style="font-size:13px">${esc(sub)}</div>`;
    }
    body += `<h4 class="mt" style="font-size:11px;letter-spacing:.09em;text-transform:uppercase;color:var(--ink-3);margin:16px 0 6px">Strongest links</h4>
      <div class="stack" style="gap:2px">${nb.slice(0, 10).map(({ e, o }) => `<a href="javascript:void 0" data-hop="${o.id}" class="row between" style="flex-wrap:nowrap;padding:5px 6px;border-radius:8px;color:var(--ink);font-size:13.5px">
        <span style="min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">${esc(o.name)} <span class="muted" style="font-size:12px">${esc(o.inst && st.mode === 'people' ? o.inst : '')}</span></span>
        <span class="mono muted">${st.mode === 'people' ? `${e.pubs}p${e.projects ? ` ${e.projects}j` : ''}` : e.weight}</span></a>`).join('') || '<div class="muted">No links in this view.</div>'}</div>
      <div class="row mt">${isPerson
        ? `<a class="btn sm primary" href="#/people/${pid}">${icon('user', 'i-sm')}Profile</a>${!st.ego || n.ref !== st.ego ? `<button class="btn sm" data-ego="${pid}">${icon('orbit', 'i-sm')}Knowledge graph</button>` : ''}` : ''}
        ${(st.mode === 'topics' && !st.ego) || (st.ego && n.kind === 'topic') ? `<a class="btn sm primary" href="#/discover/experts?q=${encodeURIComponent(n.name)}">${icon('radar', 'i-sm')}Experts on this</a>` : ''}
        ${st.ego && n.kind === 'project' ? `<a class="btn sm" href="#/repository?tab=projects&q=${encodeURIComponent(n.name.slice(0, 40))}">${icon('flask-conical', 'i-sm')}Open project</a>` : ''}
        ${st.mode === 'institutions' && n.kind === 'rice' ? `<a class="btn sm primary" href="#/network/${n.ref}">${icon('building-2', 'i-sm')}Institution page</a>` : ''}
        ${st.mode === 'people' && !st.ego ? `<button class="btn sm ghost" data-pfrom="${esc(n.name)}">${icon('route', 'i-sm')}Path from here</button>` : ''}</div>`;
    $('#gx-detail').innerHTML = `<div class="gx-detail"><div class="row between" style="padding:12px 14px 0"><span class="eyebrow" style="margin:0">${esc(st.ego ? n.kind : st.mode === 'people' ? 'Researcher' : st.mode.replace(/s$/, ''))}</span>
      <button class="iconbtn" id="d-x" aria-label="Close details" style="width:30px;height:30px">${icon('x', 'i-sm')}</button></div><div style="padding:8px 16px 16px">${body}</div></div>`;
    paintIcons($('#gx-detail'));
    $('#d-x').onclick = () => { st.selected = null; $('#gx-detail').innerHTML = ''; draw(); };
    $$('[data-hop]').forEach((a) => a.onclick = () => select(isNaN(+a.dataset.hop) ? a.dataset.hop : +a.dataset.hop, true));
    $$('[data-ego]').forEach((b) => b.onclick = () => { st.ego = +b.dataset.ego; st.selected = null; st.path = null; st.focusComm = null; st.hidden.clear(); load(); });
    $$('[data-pfrom]').forEach((b) => b.onclick = () => { const i = $('#p-a'); if (i) { i.value = b.dataset.pfrom; $('#p-b').focus(); } });
  };

  // ── load ──────────────────────────────────────────────────────────────────
  const load = async () => {
    $('#gx-detail').innerHTML = '';
    $('#gx-hud').innerHTML = '<span class="stat-pill"><b>…</b>building the graph</span>';
    try {
      if (st.ego) {
        st.data = await api(`/api/graph-ego/${st.ego}`);
      } else {
        const params = { scope: st.scope, y0: st.y0, y1: st.y1 };
        if (st.scope === 'department') params.dept = st.dept || me.user.dept_id || me.departments[0]?.id;
        if (st.mode === 'people') params.students = st.students ? 1 : 0;
        if (st.mode === 'people' && !st.students) params.students = 'false';
        st.data = await api(`/api/graph/${st.mode}${qs(params)}`);
      }
      byId = Object.fromEntries(st.data.nodes.map((n) => [n.id, n]));
      zoom = 1; view = null;
      if (chart) { chart.dispose(); chart = null; }
      if (!st.data.nodes.length) {
        $('#gx-canvas').innerHTML = `<div class="empty" style="padding-top:20vh">${icon('share-2')}<b>No links in this view yet</b><div>Widen the years, or add co-authored research.</div></div>`;
        paintIcons($('#gx-canvas'));
        side(); hud();
        return;
      }
      $('#gx-canvas').innerHTML = '';
      draw();
      side();
      if (st.ego) select(`p${st.ego}`);
    } catch (e) {
      fail(e);
      $('#gx-hud').innerHTML = `<span class="stat-pill">${esc(e.message)}</span>`;
      side();
    }
  };

  $('#z-in').onclick = () => { zoom *= 1.35; chart?.setOption({ series: [{ zoom }] }); };
  $('#z-out').onclick = () => { zoom /= 1.35; chart?.setOption({ series: [{ zoom }] }); };
  $('#z-reset').onclick = () => { zoom = 1; view = null; st.focusComm = null; draw(); side(); };
  $('#z-png').onclick = () => {
    if (!chart) return;
    const a = document.createElement('a');
    a.href = chart.getDataURL({ pixelRatio: 2, backgroundColor: getComputedStyle(document.documentElement).getPropertyValue('--paper').trim() });
    a.download = `rice-${st.mode}-graph.png`;
    a.click();
  };
  side();
  await load();
}

function showCypher(d) {
  const algos = d.algorithms || [];
  modal({
    title: d.engine === 'neo4j' ? 'How Neo4j built this view' : 'Graph engine',
    wide: true,
    body: d.engine === 'neo4j'
      ? `<p class="soft" style="margin-top:0">${esc((d.engine_info || {}).label || 'Neo4j')} ran ${d.cypher?.length || 0} Cypher quer${(d.cypher?.length || 0) === 1 ? 'y' : 'ies'}
          ${algos.length ? ` and ${algos.length} Graph Data Science algorithms on an in-memory projection` : ''}. Every query is filtered to the institutions you're allowed to see.</p>
         ${algos.length ? `<div class="chips mb">${algos.map((a) => `<span class="chip acc mono">${esc(a)}</span>`).join('')}</div>` : ''}
         ${(d.cypher || []).map((q) => `<pre class="cypher">${esc(q)}</pre>`).join('')}`
      : `<div class="callout warn">${icon('alert-triangle')}<span>Neo4j isn't connected, so RICE is using its in-memory engine (NetworkX) — same metrics, computed in Python.
         ${esc((d.engine_info || {}).note || '')}</span></div>`,
    actions: [{ label: 'Close', cls: 'primary' }],
  });
}

function explain(d) {
  const s = d.summary || {};
  const out = [];
  if (d.mode === 'people') {
    out.push(`{{${num(s.nodes)} people|yellow}} linked by ${num(s.edges)} collaborations form {{${s.communities} communities|blue}}${s.modularity >= 0.5 ? ', and they keep mostly to themselves' : ''} (modularity ${s.modularity}).`);
    if (s.avg_path) out.push(`Any two connected people are on average {{${s.avg_path} steps|green}} apart; the farthest pair is about ${s.diameter_est}.`);
    if (s.bridges) out.push(`{{${s.bridges} people|pink}} are bridges: remove any one of them and part of the network is cut off.`);
    const tot = (s.intra_dept || 0) + (s.inter_dept || 0) + (s.cross_inst || 0);
    if (tot) out.push(`${Math.round(100 * (s.inter_dept || 0) / tot)}% of links cross departments${s.cross_inst ? ` and {{${Math.round(100 * s.cross_inst / tot)}%|orange}} cross institutions` : ''}.`);
  } else if (d.mode === 'topics') {
    const rising = d.nodes.filter((n) => n.trend === 'rising').sort((a, b) => b.count - a.count);
    out.push(`{{${s.nodes} topics|yellow}} grouped into ${s.communities} clusters of themes that share papers.`);
    if (rising.length) out.push(`Rising: {{${rising.slice(0, 3).map((n) => n.name).join(', ')}|green}}.`);
  } else if (d.mode === 'institutions') {
    out.push(`{{${s.rice} RICE institutions|yellow}} and the ${s.external} partner organisations they publish with most.`);
  } else if (d.mode === 'departments') {
    const top = [...d.edges].sort((a, b) => b.weight - a.weight)[0];
    const by = Object.fromEntries(d.nodes.map((n) => [n.id, n]));
    if (top) out.push(`Strongest pairing: {{${by[top.source]?.label} + ${by[top.target]?.label}|blue}} with ${top.weight} joint papers.`);
    const lonely = d.nodes.filter((n) => n.degree <= 1).map((n) => n.label);
    if (lonely.length) out.push(`Few links out: {{${lonely.slice(0, 4).join(', ')}|pink}}.`);
  } else if (d.mode === 'mentorship') {
    out.push(`{{${s.supervisors} supervisors|yellow}} guide on average {{${s.avg_load} scholars or students|blue}} each.`);
  } else if (d.mode === 'ego') {
    out.push(`{{${s.coauthors} co-authors|yellow}} plus the topics, projects and organisations around this researcher.`);
  }
  return out;
}

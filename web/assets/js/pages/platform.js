import { api, setViewInst, store } from '../api.js';
import { reloadMe, go } from '../app.js';
import { bars, PALETTE } from '../charts.js';
import { $, $$, card, crore, empty, esc, fail, icon, kpi, modal, num, paintIcons, status, table, timeAgo, toast } from '../ui.js';

export async function render(el) {
  if (store.me.user.role !== 'platform_admin') { el.innerHTML = empty('For the RICE platform team only', '', 'lock'); paintIcons(el); return; }
  const [d, g] = await Promise.all([api('/api/platform/overview'), api('/api/graph-engine')]);
  const k = d.network.kpis;
  const waiting = d.onboarding.filter((o) => o.status === 'new');
  el.innerHTML = `<div class="ph"><div class="t"><div class="eyebrow">RICE platform</div><h1>Tenants & onboarding</h1>
      <p class="lead">Every subscribed institution, how they use RICE, and the campuses waiting to join. You can view any tenant as its admin would.</p></div>
      <div class="acts"><button class="btn primary" id="new-t">${icon('plus')}New institution</button></div></div>
    <div class="kpis mb">${kpi({ label: 'Institutions', value: d.tenants.length, note: `${d.tracked} tracked externally`, icon: 'building-2' })}
      ${kpi({ label: 'Researchers', value: num(k.researchers), icon: 'users' })}${kpi({ label: 'Verified papers', value: num(k.publications), icon: 'file-text', spark: d.network.trend.publications })}
      ${kpi({ label: 'Citations', value: num(k.citations), icon: 'quote' })}${kpi({ label: 'Grants tracked', value: crore(k.funding_lakh), icon: 'landmark' })}
      ${kpi({ label: 'Onboarding requests', value: waiting.length, icon: 'inbox' })}</div>
    <div class="grid g-2-1 mb">${card('Subscribed institutions', '<div id="tt"></div>')}
      ${card(`Asked to join <span class="badge ${waiting.length ? '' : 'n'}">${waiting.length}</span>`, d.onboarding.length ? `<div class="list">${d.onboarding.map((o) => `<div class="it"><div class="body">
        <div class="ttl">${esc(o.inst_name)}</div><div class="meta"><span>${esc(o.city || '')}${o.state ? ', ' + esc(o.state) : ''}</span><span>${esc(o.size || '')}</span><span>${timeAgo(o.created_at)}</span></div>
        <div class="meta">${esc(o.contact_name)} · ${esc(o.contact_role || '')}</div>${o.message ? `<p class="soft" style="margin:6px 0 0;font-size:13.5px">${esc(o.message)}</p>` : ''}</div>
        <div class="stack" style="gap:6px;align-items:flex-end">${o.status === 'new' ? `<button class="btn xs good" data-onb="${o.id}">Set up</button><button class="btn xs bad" data-dec="${o.id}">Decline</button>` : status(o.status)}</div></div>`).join('')}</div>`
        : empty('No requests yet', 'Requests from the public sign-in page land here.', 'inbox'))}</div>
    <div class="grid g2 mb">${card('Research score across the network', '<div class="chart tall" id="c-rank"></div>', { sub: 'RICE score (NIRF-style blend), since 2019. An estimate, not an official rank.' })}
      ${card('Graph database', graphCard(g), { actions: `<button class="btn sm" id="resync">${icon('refresh-cw', 'i-sm')}Rebuild graph</button>` })}</div>`;
  paintIcons(el);
  const { paintSparks } = await import('../charts.js');
  paintSparks(el);
  const b = d.benchmark.institutions;
  bars($('#c-rank'), { categories: b.map((x) => x.short), series: [{ name: 'RICE score', data: b.map((x) => x.rice_score) }], colors: [PALETTE[0]] });
  table($('#tt'), { rows: d.tenants, pageSize: 12, columns: [
    { key: 'name', label: 'Institution', render: (t) => `<span class="row" style="flex-wrap:nowrap"><span class="swatch" style="width:14px;height:14px;border-radius:4px;background:${esc(t.brand)}"></span><b>${esc(t.name)}</b></span><span class="muted" style="font-size:12px">${esc(t.city || '')}${t.is_demo ? ' · demo' : ''}</span>` },
    { key: 'plan', label: 'Plan', render: (t) => `<select class="input sm" data-plan="${t.id}" style="width:auto">${['Campus', 'Research+', 'Enterprise'].map((p) => `<option ${p === t.plan ? 'selected' : ''}>${p}</option>`).join('')}</select>` },
    { key: 'status', label: 'Status', render: (t) => `<select class="input sm" data-status="${t.id}" style="width:auto">${['active', 'trial', 'suspended'].map((p) => `<option ${p === t.status ? 'selected' : ''}>${p}</option>`).join('')}</select>` },
    { key: 'share_level', label: 'Shares', render: (t) => `<span class="chip">${esc(t.share_level)}</span>` },
    { key: 'members', label: 'Members', num: true }, { key: 'active_30d', label: 'Active 30d', num: true }, { key: 'publications', label: 'Papers', num: true },
    { key: 'x', label: '', nosort: true, render: (t) => `<button class="btn xs" data-view="${t.id}">View as admin</button>` }] });
  $('#tt').addEventListener('change', async (e) => {
    const p = e.target.closest('[data-plan]'), s = e.target.closest('[data-status]');
    try {
      if (p) { await api(`/api/platform/tenants/${p.dataset.plan}`, { method: 'PATCH', body: { plan: p.value } }); toast('Plan updated'); }
      if (s) { await api(`/api/platform/tenants/${s.dataset.status}`, { method: 'PATCH', body: { status: s.value } }); toast(s.value === 'suspended' ? 'Suspended — members are locked out' : 'Status updated'); }
    } catch (err) { fail(err); }
  });
  $('#tt').addEventListener('click', async (e) => {
    const v = e.target.closest('[data-view]');
    if (!v) return;
    setViewInst(v.dataset.view);
    await reloadMe();
    go('#/');
  });
  $$('[data-dec]', el).forEach((x) => x.onclick = async () => { try { await api(`/api/platform/onboarding/${x.dataset.dec}/decline`, { method: 'POST' }); toast('Declined'); render(el); } catch (err) { fail(err); } });
  $$('[data-onb]', el).forEach((x) => x.onclick = () => newTenant(el, d.onboarding.find((o) => o.id === +x.dataset.onb)));
  $('#new-t').onclick = () => newTenant(el, null);
  $('#resync').onclick = async (e) => {
    e.target.disabled = true;
    try { const r = await api('/api/platform/graph-resync', { method: 'POST' }); toast(`Graph rebuilt in ${(r.sync_ms / 1000).toFixed(1)} s`); render(el); } catch (err) { fail(err); e.target.disabled = false; }
  };
}

function graphCard(g) {
  if (g.engine !== 'neo4j') {
    return `<div class="callout warn">${icon('alert-triangle')}<span><b>Neo4j is not connected</b> — graphs run on the in-memory engine (NetworkX). ${esc(g.error || g.state || '')}<br>
      Start it with <span class="mono">python tools/neo4j_ctl.py start</span>; RICE reconnects by itself.</span></div>`;
  }
  const nodes = Object.entries(g.counts?.nodes || {}).sort((a, b) => b[1] - a[1]);
  const rels = Object.entries(g.counts?.relationships || {}).sort((a, b) => b[1] - a[1]);
  return `<div class="row mb"><span class="engine"><span class="dot"></span>${esc(g.label)}</span><span class="muted" style="font-size:12.5px">${esc(g.uri)} · last rebuilt ${esc(g.synced_at || '—')} in ${g.sync_ms ? (g.sync_ms / 1000).toFixed(1) + ' s' : '—'}</span></div>
    <div class="grid g2" style="gap:12px"><div><div class="eyebrow">Nodes · ${num(g.counts?.total_nodes)}</div>${nodes.map(([l, n]) => `<div class="row between" style="font-size:13px;padding:3px 0"><span class="mono">:${esc(l)}</span><b>${num(n)}</b></div>`).join('')}</div>
      <div><div class="eyebrow">Relationships · ${num(g.counts?.total_relationships)}</div>${rels.map(([l, n]) => `<div class="row between" style="font-size:13px;padding:3px 0"><span class="mono">${esc(l)}</span><b>${num(n)}</b></div>`).join('')}</div></div>
    <div class="row mt"><a class="btn sm" href="${esc(g.browser)}" target="_blank" rel="noopener">${icon('external-link', 'i-sm')}Open Neo4j Browser</a>
      <span class="muted" style="font-size:12px">User <span class="mono">neo4j</span>; password in <span class="mono">data/neo4j.secret</span> on the server.</span></div>`;
}

function newTenant(el, req) {
  const short = req ? req.inst_name.split(/\s+/).filter((w) => /^[A-Z]/.test(w)).map((w) => w[0]).join('').slice(0, 6) : '';
  return modal({
    title: req ? `Set up ${req.inst_name}` : 'New institution', wide: true,
    body: `<div class="form-grid">
      <label class="field wide"><span>Institution name</span><input class="input" name="name" value="${esc(req?.inst_name || '')}"></label>
      <label class="field"><span>Short code</span><input class="input" name="short" value="${esc(short)}" maxlength="10"></label>
      <label class="field"><span>Type</span><select class="input" name="kind">${['College', 'University', 'Institute'].map((k) => `<option ${req?.kind === k ? 'selected' : ''}>${k}</option>`).join('')}</select></label>
      <label class="field"><span>City</span><input class="input" name="city" value="${esc(req?.city || '')}"></label>
      <label class="field"><span>State</span><input class="input" name="state" value="${esc(req?.state || '')}"></label>
      <label class="field"><span>Plan</span><select class="input" name="plan"><option>Campus</option><option>Research+</option><option>Enterprise</option></select></label>
      <label class="field"><span>Brand colour</span><input type="color" name="brand" value="#2B59FF" style="height:40px;width:60px;border:0;background:none"></label>
      <label class="field"><span>Admin name</span><input class="input" name="admin_name" value="${esc(req?.contact_name || '')}"></label>
      <label class="field"><span>Admin email</span><input class="input" name="admin_email" value="${esc(req?.contact_email || '')}"></label>
      <label class="field wide"><span>Departments to start with</span><input class="input" name="departments" value="CSE, ECE, MECH, CIVIL, MGMT"><small>Codes: CSE, AIDS, CYS, ECE, EEE, MECH, CIVIL, CHEM, PHY, MATH, BIO, MGMT, ENV. The admin can add more later.</small></label></div>`,
    actions: [{ label: 'Cancel', cls: 'ghost' }, {
      label: 'Create workspace', cls: 'primary', run: async (ov) => {
        const g = (n) => ov.querySelector(`[name=${n}]`).value.trim();
        const r = await api('/api/platform/tenants', { method: 'POST', body: { name: g('name'), short: g('short'), kind: g('kind'), city: g('city'), state: g('state'), plan: g('plan'), brand: g('brand'),
          admin_name: g('admin_name'), admin_email: g('admin_email'), departments: g('departments').split(',').map((x) => x.trim().toUpperCase()).filter(Boolean), onboarding_id: req?.id || null } });
        await modal({ title: 'Workspace created', body: `<p>${esc(r.message)}</p><p class="muted" style="font-size:13px">Temporary admin password — shown once:</p><pre class="cypher" style="font-size:15px">${esc(r.temp_password)}</pre>`, actions: [{ label: 'Done', cls: 'primary' }] });
        await reloadMe();
        render(el);
      },
    }],
  });
}

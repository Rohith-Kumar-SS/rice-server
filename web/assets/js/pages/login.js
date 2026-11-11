import { api } from '../api.js';
import { logo, signedIn } from '../app.js';
import { PALETTE, mount, ink } from '../charts.js';
import { $, $$, esc, fail, formData, icon, num, paintIcons, toast } from '../ui.js';

const PERSONA_ICON = { platform: 'building-2', inst_admin: 'shield-check', hod: 'layers', faculty: 'graduation-cap', scholar: 'microscope', student: 'book-open', partner: 'briefcase', peer_admin: 'globe-2' };

let root = document;
export async function render(el) {
  root = el;
  let land = { stats: {}, institutions: [], personas: [] };
  const slow = setTimeout(() => {
    el.innerHTML = `<div class="l-hero" style="min-height:100vh;align-items:center;justify-content:center;text-align:center">${logo(56)}
      <h1 style="max-width:none;margin-top:8px">Waking up RICE…</h1>
      <p class="lead">The demo server sleeps when nobody is using it. The first visit can take up to a minute — this page will load by itself.</p>
      <div class="skel" style="height:8px;width:240px;margin-top:10px"></div></div>`;
  }, 2500);
  try { land = await api('/api/public/landing'); } catch (e) { fail(e); }
  clearTimeout(slow);
  const s = land.stats;
  el.innerHTML = `<div class="landing">
    <section class="l-hero">
      <div class="row" style="gap:12px">${logo(42)}<div><div style="font:700 24px var(--f-display);letter-spacing:.02em">RICE</div>
        <div class="muted" style="font-size:12.5px;font-weight:700">Research Intelligence &amp; Collaboration Engine</div></div></div>
      <h1>Every paper, project and person — in one <mark class="hl yellow" style="--i:0">living graph</mark>.</h1>
      <p class="lead">RICE turns a campus's scattered research records into a verified collaboration graph, plain-language analysis and
        NAAC- and NIRF-ready reports. Each institution runs its own space, decides who sees what, and chooses how much to share with peers.</p>
      <div class="l-graph" id="hero-graph" aria-hidden="true"></div>
      <div class="l-stats">
        <div><b>${num(s.institutions)}</b><span>institutions on RICE</span></div>
        <div><b>${num(s.researchers)}</b><span>researchers connected</span></div>
        <div><b>${num(s.publications)}</b><span>verified publications</span></div>
        <div><b>₹${num(s.funding_crore)} cr</b><span>grants tracked</span></div>
        <div><b>${num(s.tracked)}</b><span>institutions tracked externally</span></div>
      </div>
    </section>
    <section class="l-panel">
      <div class="tabs" role="tablist">
        <button class="on" data-tab="signin">Sign in</button>
        <button data-tab="join">Join your institution</button>
        <button data-tab="bring">Bring RICE to your campus</button>
      </div>
      <div id="pane"></div>
    </section></div>`;
  paintIcons(el);
  $('.l-hero h1', el).classList.add('swipe');
  heroGraph($('#hero-graph', el));
  const panes = { signin: () => signin(land), join: () => join(land), bring };
  $$('[data-tab]', el).forEach((b) => b.onclick = () => {
    $$('[data-tab]', el).forEach((x) => x.classList.toggle('on', x === b));
    panes[b.dataset.tab]();
  });
  signin(land);
}

function signin(land) {
  const pane = root.querySelector('#pane');
  pane.innerHTML = `
    <h2 style="font:600 22px var(--f-display);margin:6px 0 4px">Welcome back</h2>
    <p class="soft" style="margin:0 0 18px">Sign in with the account your institution created for you.</p>
    <form id="lf" class="stack" style="gap:12px">
      <label class="field"><span>Email</span><input class="input" name="email" type="email" autocomplete="username" required></label>
      <label class="field"><span>Password</span><input class="input" name="password" type="password" autocomplete="current-password" required></label>
      <button class="btn primary" type="submit">Sign in</button>
    </form>
    ${land.personas.length ? `<div class="mt2"><div class="row between"><b>Explore as a demo role</b><span class="demo-ribbon">${icon('flask-conical', 'i-sm')}Fictional demo data</span></div>
      <p class="muted" style="font-size:13px;margin:4px 0 12px">Six fictional institutions, generated data. Each role sees only what its institution allows.</p>
      <div class="stack" style="gap:8px">${land.personas.map((p) => `<button class="persona" data-p="${p.key}">
        <span class="av" style="--h:${{ platform: 225, inst_admin: 260, hod: 160, faculty: 210, scholar: 30, student: 330, partner: 190, peer_admin: 140 }[p.key]}">${icon(PERSONA_ICON[p.key] || 'user', 'i-sm')}</span>
        <span><b>${esc(p.title)}</b><span>${esc(p.blurb)}</span></span><span class="go">${icon('arrow-right')}</span></button>`).join('')}</div></div>` : ''}
    ${land.institutions.some((i) => i.showcase) ? `<div class="mt2 muted" style="font-size:13px">Public showcases: ${land.institutions.filter((i) => i.showcase).map((i) => `<a href="#/showcase/${esc(i.short)}">${esc(i.name)}</a>`).join(', ')}</div>` : ''}`;
  paintIcons(pane);
  $('#lf').onsubmit = async (e) => {
    e.preventDefault();
    try {
      const r = await api('/api/auth/login', { method: 'POST', body: formData(e.target) });
      await signedIn(r.token);
    } catch (err) { fail(err); }
  };
  $$('[data-p]', pane).forEach((b) => b.onclick = async () => {
    b.disabled = true;
    try {
      const r = await api('/api/auth/demo', { method: 'POST', body: { persona: b.dataset.p } });
      await signedIn(r.token);
    } catch (err) { fail(err); b.disabled = false; }
  });
}

function join(land) {
  const pane = root.querySelector('#pane');
  pane.innerHTML = `
    <h2 style="font:600 22px var(--f-display);margin:6px 0 4px">Ask to join</h2>
    <p class="soft" style="margin:0 0 18px">Your institution admin approves every account and decides your role.</p>
    <form id="jf" class="form-grid">
      <label class="field wide"><span>Institution</span><select class="input" name="institution_id" required>
        <option value="">Choose…</option>${land.institutions.map((i) => `<option value="${i.id}">${esc(i.name)} — ${esc(i.city)}</option>`).join('')}</select></label>
      <label class="field"><span>Department</span><select class="input" name="dept_id"><option value="">Choose institution first</option></select></label>
      <label class="field"><span>I am a</span><select class="input" name="role">
        <option value="faculty">Faculty member</option><option value="scholar" selected>Research scholar</option><option value="student">Student</option><option value="staff">Research staff</option></select></label>
      <label class="field wide"><span>Full name</span><input class="input" name="name" required></label>
      <label class="field"><span>Email</span><input class="input" name="email" type="email" required></label>
      <label class="field"><span>Password</span><input class="input" name="password" type="password" minlength="8" required><small>At least 8 characters</small></label>
      <label class="field wide"><span>Research interests</span><input class="input" name="interests" placeholder="e.g. Federated Learning; Edge Computing"><small>Separate with semicolons. These drive your collaborator suggestions.</small></label>
      <div class="wide"><button class="btn primary" type="submit">Send request</button></div>
    </form>`;
  const f = $('#jf');
  f.institution_id.onchange = async () => {
    const id = f.institution_id.value;
    f.dept_id.innerHTML = '<option value="">Loading…</option>';
    if (!id) return;
    const d = await api(`/api/public/institutions/${id}/departments`);
    f.dept_id.innerHTML = `<option value="">Choose…</option>${d.map((x) => `<option value="${x.id}">${esc(x.name)}</option>`).join('')}`;
  };
  f.onsubmit = async (e) => {
    e.preventDefault();
    const d = formData(f);
    try {
      const r = await api('/api/auth/signup', { method: 'POST', body: { ...d, institution_id: +d.institution_id, dept_id: d.dept_id ? +d.dept_id : null,
        interests: d.interests.split(';').map((x) => x.trim()).filter(Boolean) } });
      pane.innerHTML = `<div class="empty">${icon('mail-check')}<b>Request sent</b><div>${esc(r.message)}</div></div>`;
      paintIcons(pane);
    } catch (err) { fail(err); }
  };
}

function bring() {
  const pane = root.querySelector('#pane');
  pane.innerHTML = `
    <h2 style="font:600 22px var(--f-display);margin:6px 0 4px">RICE for your institution</h2>
    <p class="soft" style="margin:0 0 14px">No analytics team needed. Upload your faculty list or SciVal export and RICE builds the graph,
      the dashboards and the accreditation reports for you.</p>
    <div class="grid g3 mb" style="gap:10px">
      ${[['Campus', 'Graph, analytics, NAAC pack'], ['Research+', 'Adds benchmarking & expert finder across the network'], ['Enterprise', 'Multi-campus, API access, custom reports']].map(([n, d]) =>
        `<div class="card flat tint" style="padding:12px"><b>${n}</b><div class="muted" style="font-size:12.5px;line-height:1.4;margin-top:4px">${d}</div></div>`).join('')}
    </div>
    <form id="of" class="form-grid">
      <label class="field wide"><span>Institution name</span><input class="input" name="inst_name" required></label>
      <label class="field"><span>City</span><input class="input" name="city"></label>
      <label class="field"><span>State</span><input class="input" name="state"></label>
      <label class="field"><span>Type</span><select class="input" name="kind"><option>College</option><option>University</option><option>Institute</option></select></label>
      <label class="field"><span>Size</span><input class="input" name="size" placeholder="e.g. 120 faculty"></label>
      <label class="field"><span>Your name</span><input class="input" name="contact_name" required></label>
      <label class="field"><span>Your role</span><input class="input" name="contact_role" placeholder="IQAC coordinator"></label>
      <label class="field wide"><span>Work email</span><input class="input" name="contact_email" type="email" required></label>
      <label class="field wide"><span>What do you need most?</span><textarea class="input" name="message" placeholder="NAAC reports, collaboration discovery, benchmarking…"></textarea></label>
      <div class="wide"><button class="btn primary" type="submit">Request a workspace</button></div>
    </form>`;
  $('#of').onsubmit = async (e) => {
    e.preventDefault();
    try {
      const r = await api('/api/public/onboarding', { method: 'POST', body: formData(e.target) });
      toast(r.message);
      pane.innerHTML = `<div class="empty">${icon('rocket')}<b>Request received</b><div>${esc(r.message)}</div></div>`;
      paintIcons(pane);
    } catch (err) { fail(err); }
  };
}

function heroGraph(el) {
  // A small, deterministic illustrative network — three departments and the bridges between them.
  let seed = 7;
  const rnd = () => ((seed = (seed * 16807) % 2147483647) / 2147483647);
  const groups = 5, nodes = [], links = [];
  for (let g = 0; g < groups; g++) {
    for (let i = 0; i < 9; i++) nodes.push({ id: `${g}-${i}`, g, value: 1 + Math.floor(rnd() * 6) });
  }
  nodes.forEach((n, i) => {
    nodes.forEach((m, j) => {
      if (j <= i) return;
      const p = n.g === m.g ? 0.32 : 0.025;
      if (rnd() < p) links.push({ source: n.id, target: m.id });
    });
  });
  const k = ink();
  mount(el, {
    animationDurationUpdate: 1500,
    series: [{
      type: 'graph', layout: 'force', roam: false, draggable: true,
      force: { repulsion: 120, edgeLength: [30, 70], gravity: 0.08, friction: 0.2 },
      data: nodes.map((n) => ({ id: n.id, symbolSize: 8 + n.value * 3.2, itemStyle: { color: PALETTE[n.g], borderColor: k.card, borderWidth: 2 } })),
      links, lineStyle: { color: k.line2, width: 1.2, opacity: 0.9 }, emphasis: { focus: 'adjacency' },
    }],
  });
}

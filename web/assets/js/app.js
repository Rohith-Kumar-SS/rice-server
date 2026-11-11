// Boot, router, app shell, command palette, notifications, themes.
import { api, setToken, setViewInst, store } from './api.js';
import { disposeAll } from './charts.js';
import { $, $$, avatar, debounce, esc, fail, icon, initials, paintIcons, timeAgo, toast } from './ui.js';

const ROUTES = {
  '': 'dashboard', home: 'dashboard', graph: 'graph', analytics: 'analytics', discover: 'discover', people: 'people',
  repository: 'repository', opportunities: 'opportunities', collaborate: 'collaborate', network: 'network',
  approvals: 'approvals', reports: 'reports', admin: 'admin', platform: 'platform', account: 'account',
};
const PUBLIC = { login: 'login', showcase: 'showcase' };

export const THEMES = [
  { key: 'marker', name: 'Marker', sw: '#2B59FF' }, { key: 'paddy', name: 'Paddy', sw: '#11845B' },
  { key: 'lagoon', name: 'Lagoon', sw: '#0A84A3' }, { key: 'coral', name: 'Coral', sw: '#DE3F5B' },
  { key: 'iris', name: 'Iris', sw: '#6A4CF0' }, { key: 'campus', name: 'Campus colours', sw: null },
];

function mix(hex, other, w) {
  const a = hex.match(/\w\w/g).map((x) => parseInt(x, 16));
  const b = other.match(/\w\w/g).map((x) => parseInt(x, 16));
  return '#' + a.map((v, i) => Math.round(v * w + b[i] * (1 - w)).toString(16).padStart(2, '0')).join('');
}
export function applyTheme(key) {
  const root = document.documentElement;
  ['--accent', '--accent-2', '--accent-soft', '--grid'].forEach((v) => root.style.removeProperty(v));
  if (key === 'campus' && store.inst?.brand) {
    const b = store.inst.brand;
    root.dataset.theme = 'marker';
    root.style.setProperty('--accent', b);
    root.style.setProperty('--accent-2', mix(b, '#000000', 0.78));
    root.style.setProperty('--accent-soft', mix(b, '#ffffff', 0.12));
    root.style.setProperty('--grid', b + '14');
  } else {
    root.dataset.theme = key === 'campus' ? 'marker' : key;
  }
  try { localStorage.setItem('rice.theme', key); } catch (e) { /* ignore */ }
}
const currentTheme = () => { try { return localStorage.getItem('rice.theme') || 'marker'; } catch (e) { return 'marker'; } };

export function parseHash() {
  const h = location.hash.replace(/^#\/?/, '');
  const [path, query = ''] = h.split('?');
  const parts = path.split('/').filter(Boolean);
  return { parts, query: Object.fromEntries(new URLSearchParams(query)) };
}
export const go = (hash) => { if (location.hash === hash) route(); else location.hash = hash; };

async function loadMe() {
  store.me = await api('/api/me');
  store.inst = store.me.inst;
  store.perms = new Set(store.me.perms);
}

function navItems() {
  const c = (p) => store.can(p);
  const role = store.me.user.role;
  const researcher = !['external', 'platform_admin'].includes(role);
  return [
    { h: 'Workspace' },
    { k: '', label: 'Home', ic: 'sun' },
    c('graph.institution') && { k: 'graph', label: 'Graph explorer', ic: 'share-2' },
    (c('analytics.institution') || c('analytics.department') || researcher) && { k: 'analytics', label: 'Analytics', ic: 'line-chart' },
    c('discover.experts') && { k: 'discover', label: 'Discover', ic: 'radar' },
    researcher && { k: 'repository', label: 'Research records', ic: 'library' },
    { k: 'opportunities', label: 'Opportunities', ic: 'megaphone' },
    (c('collab.request') || researcher) && { k: 'collaborate', label: 'Collaboration', ic: 'handshake', badge: 'collab' },
    { h: role === 'platform_admin' ? 'Institution in view' : 'Institution' },
    role !== 'external' && { k: 'people', label: 'People', ic: 'users' },
    { k: 'network', label: 'Network & benchmarks', ic: 'globe-2' },
    (c('outputs.verify') || c('people.manage')) && { k: 'approvals', label: 'Approvals', ic: 'badge-check', badge: 'approvals' },
    c('reports.view') && { k: 'reports', label: 'Reports', ic: 'file-bar-chart' },
    (c('people.manage') || c('settings.manage')) && { k: 'admin', label: 'Admin console', ic: 'shield-check' },
    role === 'platform_admin' && { h: 'RICE platform' },
    role === 'platform_admin' && { k: 'platform', label: 'Tenants & onboarding', ic: 'building-2' },
  ].filter(Boolean);
}

let taskCounts = {};
async function refreshCounts() {
  try {
    const d = await api('/api/dashboard');
    taskCounts = {};
    d.tasks.forEach((t) => {
      if (['verify', 'join', 'opportunity'].includes(t.kind)) taskCounts.approvals = (taskCounts.approvals || 0) + t.count;
      if (t.kind === 'collab') taskCounts.collab = t.count;
    });
    $$('.nav [data-badge]').forEach((el) => {
      const n = taskCounts[el.dataset.badge];
      el.innerHTML = n ? `<span class="badge">${n}</span>` : '';
    });
    return d;
  } catch (e) { return null; }
}

function shell() {
  const u = store.me.user;
  const inst = store.inst;
  const tenantBlock = store.me.tenants.length
    ? `<label class="tenant" title="Switch institution in view"><span class="dot" style="background:${esc(inst?.brand || '#2B59FF')}">${esc((inst?.short || '').slice(0, 4))}</span>
        <span style="min-width:0;flex:1"><select id="tenant-pick" aria-label="Institution in view">${store.me.tenants.map((t) =>
          `<option value="${t.id}" ${t.id === inst?.id ? 'selected' : ''}>${esc(t.short)} — ${esc(t.name)}</option>`).join('')}</select>
        <span class="m">Viewing as platform team</span></span></label>`
    : inst ? `<div class="tenant"><span class="dot" style="background:${esc(inst.brand)}">${esc(inst.short.slice(0, 4))}</span>
        <span style="min-width:0"><span class="n">${esc(inst.name)}</span><br><span class="m">${esc(inst.city || '')} · ${esc(inst.plan)} plan</span></span></div>` : '';
  $('#app').innerHTML = `<div class="shell">
    <aside class="side" id="side">
      <a class="brand" href="#/">${logo(34)}<span><span class="word">RICE</span><div class="sub">Research Intelligence &amp;<br>Collaboration Engine</div></span></a>
      ${tenantBlock}
      <nav class="nav" aria-label="Main">${navItems().map((n) => n.h ? `<div class="nav-h">${n.h}</div>` :
        `<a href="#/${n.k}" data-k="${n.k}">${icon(n.ic)}<span>${n.label}</span>${n.badge ? `<span class="badge-slot" data-badge="${n.badge}" style="margin-left:auto"></span>` : ''}</a>`).join('')}</nav>
      <a class="me" href="#/account">${avatar(u, 'sm')}<span class="who"><b>${esc(u.name)}</b><span>${esc(u.role_label)}</span></span>${icon('settings-2', 'i-sm')}</a>
    </aside>
    <div class="main">
      <header class="top">
        <button class="iconbtn burger" id="burger" aria-label="Open menu">${icon('menu')}</button>
        <div class="ask" id="ask" role="button" tabindex="0" aria-label="Ask RICE — search people, papers, projects, topics">${icon('search')}<span>Ask RICE — people, papers, topics, institutions…</span><kbd>Ctrl K</kbd></div>
        <div class="spacer"></div>
        ${store.can('outputs.create') && u.role !== 'platform_admin' ? `<button class="btn primary sm" id="quick-add">${icon('plus')}<span>Add research</span></button>` : ''}
        <div style="position:relative"><button class="iconbtn" id="theme-btn" aria-label="Theme">${icon('palette')}</button></div>
        <div style="position:relative"><button class="iconbtn" id="bell" aria-label="Notifications">${icon('bell')}${store.me.unread ? '<span class="pip"></span>' : ''}</button></div>
        <button class="iconbtn" id="signout" aria-label="Sign out" title="Sign out">${icon('log-out')}</button>
      </header>
      <main class="view" id="view"></main>
    </div></div>`;
  paintIcons($('#app'));
  $('#ask').onclick = openPalette;
  $('#ask').onkeydown = (e) => { if (e.key === 'Enter') openPalette(); };
  $('#burger').onclick = () => $('#side').classList.toggle('open');
  $('#signout').onclick = () => { setToken(null); setViewInst(null); store.me = null; location.hash = '#/login'; route(); };
  $('#bell').onclick = (e) => toggleNotifications(e.currentTarget);
  $('#theme-btn').onclick = (e) => toggleThemes(e.currentTarget);
  $('#quick-add')?.addEventListener('click', async () => { const m = await import('./pages/repository.js'); m.addPublication(() => route()); });
  const tp = $('#tenant-pick');
  if (tp) tp.onchange = async () => { setViewInst(tp.value); await loadMe(); shell(); route(); };
  refreshCounts();
}

export function logo(size = 32) {
  return `<svg width="${size}" height="${size}" viewBox="0 0 64 64" aria-hidden="true"><rect width="64" height="64" rx="16" fill="var(--accent)"/>
    <g transform="rotate(-35 32 32)"><ellipse cx="32" cy="32" rx="13" ry="23" fill="none" stroke="#fff" stroke-width="4"/></g>
    <path d="M25 38 38 25M25 38l11 2M38 25l-2 15" stroke="#fff" stroke-width="2.4" stroke-linecap="round"/>
    <g fill="#FFE45C" stroke="#fff" stroke-width="2"><circle cx="25" cy="38" r="5"/><circle cx="38" cy="25" r="5"/><circle cx="36" cy="40" r="3.6"/></g></svg>`;
}

function closeMenus() { $$('.menu').forEach((m) => m.remove()); }
document.addEventListener('mousedown', (e) => { if (!e.target.closest('.menu') && !e.target.closest('#bell') && !e.target.closest('#theme-btn')) closeMenus(); });

function toggleThemes(btn) {
  if (btn.parentElement.querySelector('.menu')) return closeMenus();
  closeMenus();
  const cur = currentTheme();
  const m = document.createElement('div');
  m.className = 'menu';
  m.innerHTML = `<div class="nav-h" style="padding:6px 10px">Bright themes</div>${THEMES.map((t) => `<button class="mi" data-t="${t.key}">
    <span class="swatch" style="background:${t.sw || store.inst?.brand || '#2B59FF'}"></span>${t.name}${t.key === 'campus' ? ` <span class="muted" style="font-size:12px">· ${esc(store.inst?.short || '')}</span>` : ''}
    ${cur === t.key ? `<span style="margin-left:auto">${icon('check', 'i-sm')}</span>` : ''}</button>`).join('')}`;
  btn.parentElement.appendChild(m);
  paintIcons(m);
  m.querySelectorAll('[data-t]').forEach((b) => b.onclick = () => { applyTheme(b.dataset.t); closeMenus(); route(); });
}

async function toggleNotifications(btn) {
  if (btn.parentElement.querySelector('.menu')) return closeMenus();
  closeMenus();
  const m = document.createElement('div');
  m.className = 'menu';
  m.style.width = '360px';
  m.innerHTML = '<div class="skel" style="height:80px"></div>';
  btn.parentElement.appendChild(m);
  try {
    const rows = await api('/api/notifications');
    m.innerHTML = `<div class="row between" style="padding:6px 10px"><b>Notifications</b></div>${rows.length ? rows.slice(0, 12).map((n) =>
      `<a class="notif ${n.read ? '' : 'unread'}" href="${esc(n.link || '#/')}">${icon({ collab: 'handshake', verify: 'badge-check', join: 'user-plus', citation: 'quote', match: 'sparkles', report: 'file-bar-chart', opportunity: 'megaphone', onboarding: 'building-2', coauthor: 'users', role: 'shield', welcome: 'party-popper' }[n.kind] || 'bell', 'i-sm')}
      <span><span>${esc(n.text)}</span><br><span class="muted" style="font-size:12px">${timeAgo(n.created_at)}</span></span></a>`).join('') : '<div class="empty" style="padding:20px">You are all caught up.</div>'}`;
    paintIcons(m);
    m.querySelectorAll('a').forEach((a) => a.addEventListener('click', closeMenus));
    if (rows.some((r) => !r.read)) { await api('/api/notifications/read', { method: 'POST' }); btn.querySelector('.pip')?.remove(); }
  } catch (e) { m.innerHTML = `<div class="empty">${esc(e.message)}</div>`; }
}

// ── Ask RICE command palette ─────────────────────────────────────────────────
const COMMANDS = () => navItems().filter((n) => !n.h).map((n) => ({ label: `Go to ${n.label}`, href: `#/${n.k}`, ic: n.ic }));
function openPalette() {
  if ($('.palette')) return;
  const ov = document.createElement('div');
  ov.className = 'overlay';
  ov.innerHTML = `<div class="palette" role="dialog" aria-label="Ask RICE"><div class="q-in">${icon('sparkles')}<input id="pq" placeholder="Try “federated learning”, a name, or an institution" autocomplete="off"><kbd class="mono muted">Esc</kbd></div><div class="res" id="pres"></div></div>`;
  document.body.appendChild(ov);
  paintIcons(ov);
  const input = $('#pq', ov), res = $('#pres', ov);
  let sel = 0;
  const close = () => { ov.remove(); document.removeEventListener('keydown', onKey); };
  const opts = () => $$('.opt', res);
  const highlight = () => opts().forEach((o, i) => o.classList.toggle('sel', i === sel));
  const onKey = (e) => {
    if (e.key === 'Escape') close();
    if (e.key === 'ArrowDown') { sel = Math.min(sel + 1, opts().length - 1); highlight(); e.preventDefault(); }
    if (e.key === 'ArrowUp') { sel = Math.max(sel - 1, 0); highlight(); e.preventDefault(); }
    if (e.key === 'Enter') { const o = opts()[sel]; if (o) { location.hash = o.getAttribute('href'); close(); } }
  };
  document.addEventListener('keydown', onKey);
  ov.addEventListener('mousedown', (e) => { if (e.target === ov) close(); });
  const drawCommands = (q) => {
    const cmds = COMMANDS().filter((c) => !q || c.label.toLowerCase().includes(q.toLowerCase())).slice(0, 8);
    return cmds.length ? `<div class="grp">Go to</div>${cmds.map((c) => `<a class="opt" href="${c.href}">${icon(c.ic, 'i-sm')}${esc(c.label)}</a>`).join('')}` : '';
  };
  const draw = async (q) => {
    sel = 0;
    if (q.length < 2) { res.innerHTML = drawCommands(q) + `<div class="grp">Try</div>${['Large Language Models', 'Battery Management Systems', 'Remote Sensing & GIS', 'Post-Quantum Cryptography'].map((t) =>
      `<a class="opt" href="#/discover/experts?q=${encodeURIComponent(t)}">${icon('radar', 'i-sm')}Experts in ${esc(t)}</a>`).join('')}`; paintIcons(res); highlight(); return; }
    try {
      const r = await api('/api/search?q=' + encodeURIComponent(q));
      let html = '';
      if (r.people?.length) html += `<div class="grp">People</div>${r.people.map((p) => `<a class="opt" href="#/people/${p.id}">${avatar(p, 'sm')}<span><b>${esc(p.name)}</b> <span class="muted">${esc(p.designation || '')}</span></span><span class="x">${esc(p.dept)} · ${esc(p.inst)}</span></a>`).join('')}`;
      if (r.topics?.length) html += `<div class="grp">Topics</div>${r.topics.map((t) => `<a class="opt" href="#/discover/experts?q=${encodeURIComponent(t.topic)}">${icon('tag', 'i-sm')}${esc(t.topic)}<span class="x">${t.people} researchers</span></a>`).join('')}`;
      if (r.publications?.length) html += `<div class="grp">Publications</div>${r.publications.map((p) => `<a class="opt" href="#/repository?q=${encodeURIComponent(p.title.slice(0, 40))}">${icon('file-text', 'i-sm')}<span style="min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">${esc(p.title)}</span><span class="x">${p.year} · ${p.citations} cites</span></a>`).join('')}`;
      if (r.projects?.length) html += `<div class="grp">Projects</div>${r.projects.map((p) => `<a class="opt" href="#/repository?tab=projects&q=${encodeURIComponent(p.title.slice(0, 40))}">${icon('flask-conical', 'i-sm')}<span style="min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">${esc(p.title)}</span><span class="x">${esc(p.agency)}</span></a>`).join('')}`;
      if (r.institutions?.length) html += `<div class="grp">Institutions</div>${r.institutions.map((i) => `<a class="opt" href="#/network/${i.id}">${icon('building-2', 'i-sm')}${esc(i.name)}<span class="x">${esc(i.city || '')}${i.external ? ' · tracked' : ''}</span></a>`).join('')}`;
      if (r.departments?.length) html += `<div class="grp">Departments</div>${r.departments.map((d) => `<a class="opt" href="#/analytics/overview?scope=department&dept=${d.id}">${icon('layers', 'i-sm')}${esc(d.name)}</a>`).join('')}`;
      html += `<div class="grp">Ask</div><a class="opt" href="#/discover/experts?q=${encodeURIComponent(q)}">${icon('radar', 'i-sm')}Find experts on “${esc(q)}”</a>`;
      html += drawCommands(q);
      res.innerHTML = html;
      paintIcons(res);
      highlight();
      res.querySelectorAll('a').forEach((a) => a.addEventListener('click', close));
    } catch (e) { res.innerHTML = `<div class="empty">${esc(e.message)}</div>`; }
  };
  input.addEventListener('input', debounce(() => draw(input.value.trim()), 180));
  draw('');
  input.focus();
}
document.addEventListener('keydown', (e) => {
  if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'k' && store.me) { e.preventDefault(); openPalette(); }
});

// ── router ───────────────────────────────────────────────────────────────────
let cleanup = null;
let renderSeq = 0;
export async function route() {
  const { parts, query } = parseHash();
  const head = parts[0] || '';
  disposeAll();
  if (cleanup) { try { cleanup(); } catch (e) { /* ignore */ } cleanup = null; }
  const seq = ++renderSeq;

  if (PUBLIC[head]) {
    if (head === 'login' && store.token) {
      try { await loadMe(); location.hash = '#/'; return; } catch (e) { setToken(null); }
    }
    const mod = await import(`./pages/${PUBLIC[head]}.js`);
    if (seq !== renderSeq) return;
    $('#app').innerHTML = '<div id="view"></div>';
    cleanup = await mod.render($('#view'), { parts, query });
    if (seq !== renderSeq) return;
    paintIcons($('#app'));
    return;
  }
  if (!store.token) { location.hash = '#/login'; return; }
  if (!store.me) {
    try {
      await loadMe();
      applyTheme(currentTheme());
    } catch (e) {
      setToken(null); location.hash = '#/login'; return;
    }
  }
  if (!$('#side')) shell();
  const page = ROUTES[head];
  $$('.nav a').forEach((a) => a.classList.toggle('on', a.dataset.k === (head === 'home' ? '' : head)));
  $('#side')?.classList.remove('open');
  const view = $('#view');
  if (!page) { view.className = 'view'; view.innerHTML = `<div class="empty">${icon('compass')}<b>Page not found</b><a href="#/">Back to home</a></div>`; paintIcons(view); return; }
  view.className = page === 'graph' ? 'view full' : 'view';
  view.innerHTML = '<div class="loading"><div class="skel" style="height:64px;width:40%"></div><div class="skel" style="height:120px"></div><div class="skel" style="height:300px"></div></div>';
  try {
    const mod = await import(`./pages/${page}.js`);
    if (seq !== renderSeq) return;
    cleanup = await mod.render(view, { parts, query, refreshCounts });
    if (seq !== renderSeq) return;
    paintIcons(view);
    window.scrollTo({ top: 0 });
  } catch (e) {
    if (seq !== renderSeq) return;
    console.error(e);
    view.innerHTML = `<div class="empty">${icon('lock')}<b>${esc(e.message || 'Something went wrong')}</b><div>${e.status === 403 ? 'Your institution admin controls access to this area.' : 'Try again, or go back home.'}</div><div class="mt"><a class="btn" href="#/">Back to home</a></div></div>`;
    paintIcons(view);
  }
}

export async function signedIn(token) {
  setToken(token);
  setViewInst(null);
  store.me = null;
  await loadMe();
  applyTheme(currentTheme());
  $('#app').innerHTML = '';
  location.hash = '#/';
  route();
}
export async function reloadMe() { await loadMe(); shell(); }

window.addEventListener('hashchange', route);
window.addEventListener('unhandledrejection', (e) => { if (e.reason?.message) fail(e.reason); });
route();
export { toast, initials };

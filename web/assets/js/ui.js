// UI kit: escaping, formatting, small components, overlays.
import { store } from './api.js';

export const esc = (v) => String(v ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
export const $ = (sel, root = document) => root.querySelector(sel);
export const $$ = (sel, root = document) => [...root.querySelectorAll(sel)];
export const icon = (name, cls = '') => `<i data-lucide="${name}" class="${cls}"></i>`;
export function paintIcons(root) {
  if (window.lucide) window.lucide.createIcons({ attrs: { 'stroke-width': 1.9 }, nameAttr: 'data-lucide', root });
}

const nf = new Intl.NumberFormat('en-IN');
export const num = (n) => (n === null || n === undefined || Number.isNaN(n) ? '—' : nf.format(n));
export function compact(n) {
  if (n === null || n === undefined) return '—';
  if (Math.abs(n) >= 1e5) return (n / 1e5).toFixed(n >= 1e6 ? 0 : 1).replace(/\.0$/, '') + ' L';
  if (Math.abs(n) >= 1e3) return (n / 1e3).toFixed(1).replace(/\.0$/, '') + 'k';
  return nf.format(n);
}
export const crore = (lakh) => (lakh >= 100 ? `₹${(lakh / 100).toFixed(lakh >= 1000 ? 1 : 2).replace(/\.?0+$/, '')} cr` : `₹${(+lakh).toFixed(1).replace(/\.0$/, '')} L`);
export const pct = (v) => (v === null || v === undefined ? '—' : `${v}%`);
export function initials(name) {
  const p = String(name || '?').replace(/^(Dr|Prof)\.?\s+/i, '').split(/\s+/).filter(Boolean);
  return ((p[0]?.[0] || '') + (p.length > 1 ? p[p.length - 1][0] : '')).toUpperCase();
}
export function avatar(p, size = '') {
  const hue = p.hue ?? (Array.from(String(p.name || '')).reduce((a, c) => a + c.charCodeAt(0), 0) % 360);
  return `<span class="av ${size}" style="--h:${hue}" aria-hidden="true">${esc(initials(p.name))}</span>`;
}
export function who(p, { link = true, sub } = {}) {
  const s = sub ?? [p.designation, p.dept, p.inst].filter(Boolean).join(' · ');
  const inner = `${avatar(p)}<span style="min-width:0"><span class="nm">${esc(p.name)}</span><br><span class="ds">${esc(s)}</span></span>`;
  return link && p.id ? `<a class="who" href="#/people/${p.id}">${inner}</a>` : `<span class="who">${inner}</span>`;
}
export const status = (s) => `<span class="st ${esc(s)}">${esc(String(s).replace('_', ' '))}</span>`;
export const quart = (q) => (q ? `<span class="q ${q}">${q}</span>` : '');
export const chip = (t, cls = '') => `<span class="chip ${cls}">${esc(t)}</span>`;
export const roleLabel = (r) => (store.me?.roles?.[r]) || r;

// "{{value|tone}}" → highlighter mark
export function marks(text, i0 = 0) {
  let i = i0;
  return esc(text).replace(/\{\{(.+?)\|(\w+)\}\}/g, (_, v, tone) => `<mark class="hl ${tone}" style="--i:${i++}">${v}</mark>`);
}

export function timeAgo(ts) {
  if (!ts) return '';
  const d = new Date(ts.replace(' ', 'T') + (ts.endsWith('Z') ? '' : 'Z'));
  const s = (Date.now() - d.getTime()) / 1000;
  if (s < 60) return 'just now';
  if (s < 3600) return `${Math.round(s / 60)} min ago`;
  if (s < 86400) return `${Math.round(s / 3600)} h ago`;
  if (s < 86400 * 30) return `${Math.round(s / 86400)} d ago`;
  return d.toLocaleDateString('en-IN', { day: 'numeric', month: 'short', year: 'numeric' });
}
export function daysLeft(dateStr) {
  const d = new Date(dateStr + 'T23:59:59');
  return Math.ceil((d - new Date()) / 86400000);
}
export const fmtDate = (s) => new Date(s + 'T00:00:00').toLocaleDateString('en-IN', { day: 'numeric', month: 'short', year: 'numeric' });

export function kpi({ label, value, unit = '', delta, note, icon: ic, spark, basis }) {
  const d = delta === null || delta === undefined ? '' :
    `<span class="delta ${delta >= 0 ? 'up' : 'down'}" title="${esc(basis || 'Year on year')}">${delta >= 0 ? '▲' : '▼'} ${Math.abs(delta)}%</span>`;
  return `<div class="kpi ${spark ? 'has-spark' : ''}">
    <div class="l">${ic ? icon(ic, 'i-sm') : ''}${esc(label)}</div>
    <div class="v">${value}${unit ? `<small>${esc(unit)}</small>` : ''}</div>
    <div class="d">${d}${note ? `<span>${esc(note)}</span>` : ''}</div>
    ${spark ? `<div class="spark" data-spark='${JSON.stringify(spark)}'></div>` : ''}
  </div>`;
}

export function card(title, body, { actions = '', sub = '', cls = '', id = '' } = {}) {
  return `<section class="card ${cls}" ${id ? `id="${id}"` : ''}>
    <div class="hd"><h3>${title}</h3>${actions}${sub ? `<div class="sub">${sub}</div>` : ''}</div>
    <div class="bd">${body}</div></section>`;
}

export function empty(title, text = '', ic = 'sprout', action = '') {
  return `<div class="empty">${icon(ic)}<b>${esc(title)}</b>${text ? `<div>${esc(text)}</div>` : ''}${action ? `<div class="mt">${action}</div>` : ''}</div>`;
}

export function skeleton(rows = 3) {
  return `<div class="loading">${'<div class="skel" style="height:110px"></div>'.repeat(rows)}</div>`;
}

export function toast(msg, kind = '') {
  const el = document.createElement('div');
  el.className = `toast ${kind}`;
  el.innerHTML = `${icon(kind === 'err' ? 'alert-circle' : 'check-circle-2')}<span>${esc(msg)}</span>`;
  $('#toasts').appendChild(el);
  paintIcons(el);
  setTimeout(() => { el.style.opacity = '0'; el.style.transition = 'opacity .3s'; }, 3600);
  setTimeout(() => el.remove(), 4000);
}
export const fail = (e) => toast(e.message || String(e), 'err');

export function modal({ title, body, actions = [], wide = false, onMount }) {
  return new Promise((resolve) => {
    const ov = document.createElement('div');
    ov.className = 'overlay';
    ov.innerHTML = `<div class="modal ${wide ? 'wide' : ''}" role="dialog" aria-modal="true" aria-label="${esc(title)}">
      <div class="mh"><h3>${esc(title)}</h3><button class="iconbtn" data-x aria-label="Close">${icon('x')}</button></div>
      <div class="mb">${body}</div>
      <div class="mf">${actions.map((a, i) => `<button class="btn ${a.cls || ''}" data-a="${i}">${a.label}</button>`).join('')}</div></div>`;
    document.body.appendChild(ov);
    paintIcons(ov);
    const close = (v) => { ov.remove(); document.removeEventListener('keydown', onKey); resolve(v); };
    const onKey = (e) => { if (e.key === 'Escape') close(null); };
    document.addEventListener('keydown', onKey);
    ov.addEventListener('mousedown', (e) => { if (e.target === ov) close(null); });
    ov.querySelector('[data-x]').onclick = () => close(null);
    ov.querySelectorAll('[data-a]').forEach((b) => {
      b.onclick = async () => {
        const a = actions[+b.dataset.a];
        if (!a.run) return close(a.value ?? null);
        b.disabled = true;
        try {
          const v = await a.run(ov);
          if (v !== false) close(v ?? true);
        } catch (e) { fail(e); } finally { b.disabled = false; }
      };
    });
    const first = ov.querySelector('input, select, textarea');
    if (first) setTimeout(() => first.focus(), 30);
    if (onMount) onMount(ov);
  });
}

export const confirmBox = (title, text, label = 'Confirm', cls = 'primary') =>
  modal({ title, body: `<p class="soft" style="margin:0">${esc(text)}</p>`, actions: [{ label: 'Cancel', cls: 'ghost', value: false }, { label, cls, value: true }] });

export function formData(root) {
  const o = {};
  root.querySelectorAll('[name]').forEach((el) => {
    if (el.type === 'checkbox') o[el.name] = el.checked;
    else if (el.type === 'number') o[el.name] = el.value === '' ? null : +el.value;
    else o[el.name] = el.value.trim();
  });
  return o;
}

export const debounce = (fn, ms = 250) => { let t; return (...a) => { clearTimeout(t); t = setTimeout(() => fn(...a), ms); }; };

// Sortable, paginated table from column specs: {key, label, num, render, sort}
export function table(el, { columns, rows, pageSize = 15, empty: emptyMsg = 'Nothing here yet.', initialSort }) {
  let sortKey = initialSort?.key, dir = initialSort?.dir || -1, page = 0;
  const draw = () => {
    let data = rows.slice();
    if (sortKey) {
      const col = columns.find((c) => c.key === sortKey);
      const get = col?.sort || ((r) => r[sortKey]);
      data.sort((a, b) => { const x = get(a), y = get(b); return (x > y ? 1 : x < y ? -1 : 0) * dir; });
    }
    const pages = Math.max(1, Math.ceil(data.length / pageSize));
    page = Math.min(page, pages - 1);
    const slice = data.slice(page * pageSize, (page + 1) * pageSize);
    el.innerHTML = rows.length ? `<div class="tbl-wrap"><table class="tbl"><thead><tr>${columns.map((c) =>
      `<th class="${c.num ? 'num' : ''}" ${c.nosort ? '' : `data-sort="${c.key}"`}>${esc(c.label)}${sortKey === c.key ? (dir > 0 ? ' ↑' : ' ↓') : ''}</th>`).join('')}</tr></thead>
      <tbody>${slice.map((r) => `<tr>${columns.map((c) => `<td class="${c.num ? 'num' : ''}">${c.render ? c.render(r) : esc(r[c.key] ?? '')}</td>`).join('')}</tr>`).join('')}</tbody></table></div>
      ${pages > 1 ? `<div class="pager"><span>${page * pageSize + 1}–${Math.min(data.length, (page + 1) * pageSize)} of ${num(data.length)}</span>
      <span class="row"><button class="btn xs" data-p="-1" ${page ? '' : 'disabled'}>Previous</button><button class="btn xs" data-p="1" ${page < pages - 1 ? '' : 'disabled'}>Next</button></span></div>` : ''}`
      : empty(emptyMsg, '', 'inbox');
    el.querySelectorAll('th[data-sort]').forEach((th) => th.onclick = () => {
      if (sortKey === th.dataset.sort) dir = -dir; else { sortKey = th.dataset.sort; dir = columns.find((c) => c.key === sortKey)?.num ? -1 : 1; }
      draw();
    });
    el.querySelectorAll('[data-p]').forEach((b) => b.onclick = () => { page += +b.dataset.p; draw(); });
    paintIcons(el);
  };
  draw();
  return { redraw: draw };
}

export function pubLine(p, { actions = '' } = {}) {
  const authors = p.authors || [];
  const names = authors.slice(0, 6).map((a) => (a.id ? `<a href="#/people/${a.id}">${esc(a.name)}</a>` : esc(a.name))).join(', ') + (authors.length > 6 ? ` +${authors.length - 6}` : '');
  return `<div class="it"><div class="body">
    <div class="ttl">${esc(p.title)}</div>
    <div class="meta"><span>${names}</span></div>
    <div class="meta"><b class="soft">${esc(p.venue || '')}</b><span>${p.year}</span>${quart(p.quartile)}${p.open_access ? '<span class="oa">OA</span>' : ''}
      <span>${icon('quote', 'i-sm')} ${num(p.citations)}</span>${p.status && p.status !== 'verified' ? status(p.status) : ''}
      ${p.doi ? `<span class="mono muted">${esc(p.doi)}</span>` : ''}</div></div>${actions}</div>`;
}

export function yearsSelect(name, value, years, cls = 'input sm') {
  const opts = [];
  for (let y = years[1]; y >= years[0]; y--) opts.push(`<option ${+value === y ? 'selected' : ''}>${y}</option>`);
  return `<select class="${cls}" name="${name}" style="width:auto">${opts.join('')}</select>`;
}

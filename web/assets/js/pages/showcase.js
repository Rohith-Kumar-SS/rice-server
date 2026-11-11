import { api } from '../api.js';
import { logo } from '../app.js';
import { bars, lines, PALETTE } from '../charts.js';
import { $, card, crore, empty, esc, icon, kpi, num, paintIcons, pubLine } from '../ui.js';

export async function render(el, { parts }) {
  let d;
  try { d = await api(`/api/public/showcase/${encodeURIComponent(parts[1] || '')}`); } catch (e) {
    el.innerHTML = `<div class="view">${empty(e.message, '', 'eye-off', '<a class="btn" href="#/login">Go to RICE</a>')}</div>`;
    paintIcons(el);
    return;
  }
  const i = d.institution, k = d.kpis;
  document.title = `${i.name} — research on RICE`;
  el.innerHTML = `<div class="l-hero" style="min-height:auto;padding:28px 40px 34px;border-bottom:1px solid var(--line)">
      <div class="row between"><a class="row" href="#/login" style="color:var(--ink);gap:10px">${logo(30)}<b style="font:700 17px var(--f-display)">RICE</b></a><a class="btn sm" href="#/login">Sign in</a></div>
      <div class="row" style="gap:16px;margin-top:10px"><span style="width:56px;height:56px;border-radius:16px;background:${esc(i.brand)};display:grid;place-items:center;color:#fff;font:700 15px var(--f-display)">${esc(i.short)}</span>
        <div><div class="eyebrow" style="margin:0">Public research showcase · ${esc(i.city)}, ${esc(i.state)} · est. ${i.established}</div><h1 style="font:600 34px/1.1 var(--f-display);letter-spacing:-.02em;margin:4px 0 0">${esc(i.name)}</h1></div></div>
      <p class="lead">${esc(i.tagline || '')}</p></div>
    <div class="view">
      <div class="kpis mb">${kpi({ label: 'Papers since 2019', value: num(k.publications) })}${kpi({ label: 'Citations', value: num(k.citations) })}${kpi({ label: 'h-index', value: k.h_index })}
        ${kpi({ label: 'Q1 journal share', value: k.q1_share, unit: '%' })}${kpi({ label: 'Research grants', value: crore(k.funding_lakh) })}${kpi({ label: 'Patents', value: k.patents })}</div>
      <div class="grid g2 mb">${card('Papers per year', '<div class="chart" id="s-p"></div>')}${card('Sustainable Development Goals', '<div class="chart" id="s-g"></div>')}</div>
      <div class="grid g-2-1">${card('Most-cited recent work', `<div class="list">${d.papers.map((p) => pubLine(p)).join('')}</div>`)}
        <div class="stack">${card('Research areas', `<div class="chips">${d.topics.map((t) => `<span class="chip ${t.trend === 'rising' ? 'acc' : ''}">${esc(t.topic)} · ${t.count}</span>`).join('')}</div>`)}
        ${card('Departments', `<div class="chips">${d.departments.map((x) => `<span class="chip">${esc(x.name)}</span>`).join('')}</div>`)}
        <div class="callout">${icon('sparkles')}<span>Published with RICE — the research intelligence & collaboration engine. ${esc(i.short)} chose to make this page public.</span></div></div></div></div>`;
  paintIcons(el);
  bars($('#s-p'), { categories: d.trend.years, series: [{ name: 'Papers', data: d.trend.publications }] });
  bars($('#s-g'), { categories: d.sdg.map((s) => `SDG ${s.goal}`), series: [{ name: 'Papers', data: d.sdg.map((s) => s.count) }], colors: [PALETTE[2]] });
}
export { lines };

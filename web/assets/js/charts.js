// ECharts helpers. Categorical colours follow the entity in a fixed order (validated for CVD with
// legends + tooltips as secondary encoding). Text always wears ink tokens, never series colour.
export const PALETTE = ['#2B6CE8', '#F07B1D', '#12A66A', '#7A5CFA', '#E23D8E', '#0E9BB0', '#C99400', '#D9434A'];
export const OTHER = '#B4BCCD';
export const SEQ = ['#E7EEFF', '#BCD0FF', '#86A9FA', '#4F7FF0', '#2B59D9', '#173BA6'];

const live = new Set();
const css = (v) => getComputedStyle(document.documentElement).getPropertyValue(v).trim();
export const ink = () => ({ t1: css('--ink'), t2: css('--ink-2'), t3: css('--ink-3'), line: css('--line'), line2: css('--line-2'), card: css('--card'), accent: css('--accent') });

export function mount(el, option) {
  if (!el || !window.echarts) return null;
  const prev = window.echarts.getInstanceByDom(el);
  if (prev) { prev.dispose(); live.delete(prev); }
  const ch = window.echarts.init(el, null, { renderer: 'canvas' });
  ch.setOption(option);
  const ro = new ResizeObserver(() => ch.resize());
  ro.observe(el);
  ch.__ro = ro;
  live.add(ch);
  return ch;
}
export function disposeAll() {
  live.forEach((c) => { try { c.__ro?.disconnect(); c.dispose(); } catch (e) { /* gone */ } });
  live.clear();
}

export function base(extra = {}) {
  const k = ink();
  return {
    color: PALETTE,
    textStyle: { fontFamily: 'Hanken Grotesk, Segoe UI, sans-serif', color: k.t2 },
    animationDuration: 600,
    tooltip: {
      backgroundColor: k.card, borderColor: k.line2, borderWidth: 1, padding: [8, 12],
      textStyle: { color: k.t1, fontSize: 12.5 }, extraCssText: 'border-radius:12px;box-shadow:0 12px 30px -12px rgba(20,32,74,.35);',
    },
    grid: { left: 8, right: 12, top: 36, bottom: 6, containLabel: true },
    ...extra,
  };
}
const axisStyle = () => {
  const k = ink();
  return {
    axisLine: { lineStyle: { color: k.line2 } }, axisTick: { show: false },
    axisLabel: { color: k.t3, fontSize: 11.5 }, splitLine: { lineStyle: { color: k.line, type: [4, 4] } },
  };
};
const legend = (show = true) => ({ show, top: 0, left: 0, icon: 'roundRect', itemWidth: 12, itemHeight: 8, itemGap: 14, textStyle: { color: ink().t2, fontSize: 12 } });

export function bars(el, { categories, series, stack = false, horizontal = false, fmt, colors, legendShow, percent = false, onClick }) {
  const ax = axisStyle();
  const cat = { type: 'category', data: categories, ...ax, splitLine: { show: false } };
  const val = { type: 'value', ...ax, axisLabel: { ...ax.axisLabel, formatter: percent ? '{value}%' : undefined } };
  const radius = horizontal ? [0, 4, 4, 0] : [4, 4, 0, 0];
  const ch = mount(el, base({
    color: colors || PALETTE,
    legend: legend(legendShow ?? series.length > 1),
    grid: { left: 8, right: 16, top: series.length > 1 ? 34 : 14, bottom: 4, containLabel: true },
    tooltip: { ...base().tooltip, trigger: 'axis', axisPointer: { type: 'shadow', shadowStyle: { color: 'rgba(43,89,255,.06)' } },
      valueFormatter: fmt },
    xAxis: horizontal ? val : cat,
    yAxis: horizontal ? { ...cat, inverse: true } : val,
    series: series.map((s, i) => ({
      type: 'bar', name: s.name, data: s.data, stack: stack ? 'a' : undefined, barMaxWidth: horizontal ? 18 : 26,
      itemStyle: { borderRadius: stack && i < series.length - 1 ? 0 : radius, borderColor: ink().card, borderWidth: stack ? 1 : 0, color: s.color },
      emphasis: { focus: 'series' },
    })),
  }));
  if (onClick && ch) ch.on('click', onClick);
  return ch;
}

export function lines(el, { categories, series, area = false, fmt, percent = false, colors, yMin }) {
  const ax = axisStyle();
  return mount(el, base({
    color: colors || PALETTE,
    legend: legend(series.length > 1),
    grid: { left: 8, right: 16, top: series.length > 1 ? 34 : 14, bottom: 4, containLabel: true },
    tooltip: { ...base().tooltip, trigger: 'axis', axisPointer: { type: 'line', lineStyle: { color: ink().line2 } }, valueFormatter: fmt || (percent ? (v) => `${v}%` : undefined) },
    xAxis: { type: 'category', data: categories, boundaryGap: false, ...ax, splitLine: { show: false } },
    yAxis: { type: 'value', min: yMin, ...ax, axisLabel: { ...ax.axisLabel, formatter: percent ? '{value}%' : undefined } },
    series: series.map((s) => ({
      type: 'line', name: s.name, data: s.data, smooth: 0.25, symbol: 'circle', symbolSize: 8, showSymbol: false,
      lineStyle: { width: 2 }, emphasis: { focus: 'series' }, stack: s.stack,
      areaStyle: area || s.area ? { opacity: 0.12 } : undefined, itemStyle: s.color ? { color: s.color } : undefined,
      endLabel: series.length > 1 && series.length <= 4 ? { show: true, formatter: '{a}', color: ink().t2, fontSize: 11.5, distance: 6 } : undefined,
    })),
  }));
}

export function donut(el, { data, fmt, center = 'Total', colors }) {
  const total = data.reduce((a, d) => a + d.value, 0);
  return mount(el, base({
    color: colors || PALETTE,
    tooltip: { ...base().tooltip, trigger: 'item', valueFormatter: fmt },
    legend: { ...legend(), orient: 'vertical', top: 'middle', left: '58%', right: 4,
      textStyle: { ...legend().textStyle, width: Math.max(80, (el.clientWidth || 300) * 0.4 - 30), overflow: 'truncate' },
      tooltip: { show: true },
      formatter: (n) => { const d = data.find((x) => x.name === n); return `${n}  ${d ? Math.round(100 * d.value / (total || 1)) : 0}%`; } },
    title: { text: fmt ? fmt(total) : total.toLocaleString('en-IN'), subtext: center, left: '28%', top: '40%', textAlign: 'center',
      textStyle: { fontFamily: 'Unbounded', fontSize: 18, color: ink().t1, fontWeight: 600 }, subtextStyle: { color: ink().t3, fontSize: 11.5 } },
    series: [{ type: 'pie', radius: ['56%', '80%'], center: ['29%', '50%'], data, label: { show: false }, padAngle: 1.5,
      itemStyle: { borderColor: ink().card, borderWidth: 2, borderRadius: 4 } }],
  }));
}

export function heatmap(el, { x, y, data, onClick }) {
  const max = Math.max(1, ...data.map((d) => d[2]));
  const ch = mount(el, base({
    tooltip: { ...base().tooltip, formatter: (p) => `<b>${y[p.value[1]]}</b><br>${x[p.value[0]]}: ${p.value[2]} papers` },
    grid: { left: 8, right: 10, top: 6, bottom: 34, containLabel: true },
    xAxis: { type: 'category', data: x, ...axisStyle(), splitLine: { show: false }, splitArea: { show: false } },
    yAxis: { type: 'category', data: y, ...axisStyle(), splitLine: { show: false }, axisLabel: { color: ink().t2, fontSize: 11.5, width: 170, overflow: 'truncate' } },
    visualMap: { min: 0, max, calculable: false, orient: 'horizontal', left: 'center', bottom: 0, itemWidth: 10, itemHeight: 120,
      inRange: { color: SEQ }, textStyle: { color: ink().t3, fontSize: 11 } },
    series: [{ type: 'heatmap', data, itemStyle: { borderColor: ink().card, borderWidth: 2, borderRadius: 4 },
      emphasis: { itemStyle: { borderColor: ink().t1, borderWidth: 1 } } }],
  }));
  if (onClick && ch) ch.on('click', onClick);
  return ch;
}

export function sankey(el, { nodes, links, fmt }) {
  return mount(el, base({
    tooltip: { ...base().tooltip, trigger: 'item', valueFormatter: fmt },
    series: [{
      type: 'sankey', data: nodes, links, left: 4, right: 120, top: 8, bottom: 8, nodeGap: 9, nodeWidth: 12, draggable: false,
      emphasis: { focus: 'adjacency' }, lineStyle: { color: 'gradient', opacity: 0.28, curveness: 0.5 },
      label: { color: ink().t1, fontSize: 11.5 }, itemStyle: { borderWidth: 0, borderRadius: 3 },
      levels: [{ depth: 0, itemStyle: { color: PALETTE[3] } }, { depth: 1, itemStyle: { color: PALETTE[0] } }, { depth: 2, itemStyle: { color: PALETTE[2] } }],
    }],
  }));
}

export function radar(el, { indicators, series, colors }) {
  const k = ink();
  return mount(el, base({
    color: colors || PALETTE,
    legend: { ...legend(), bottom: 0, top: 'auto' },
    tooltip: { ...base().tooltip, trigger: 'item' },
    radar: { indicator: indicators, radius: '66%', center: ['50%', '48%'], splitNumber: 4,
      axisName: { color: k.t2, fontSize: 11.5 }, splitLine: { lineStyle: { color: k.line } },
      splitArea: { areaStyle: { color: ['transparent'] } }, axisLine: { lineStyle: { color: k.line } } },
    series: [{ type: 'radar', symbolSize: 6, data: series.map((s) => ({ ...s, lineStyle: { width: 2 }, areaStyle: { opacity: s.self ? 0.18 : 0.04 } })) }],
  }));
}

export function chord(el, { labels, matrix, colors }) {
  const nodes = labels.map((l, i) => ({ name: l, value: matrix[i].reduce((a, b) => a + b, 0),
    symbolSize: 10 + Math.sqrt(matrix[i].reduce((a, b) => a + b, 0)) * 2.2, itemStyle: { color: (colors || PALETTE)[i % PALETTE.length] } }));
  const links = [];
  matrix.forEach((row, i) => row.forEach((v, j) => { if (j > i && v > 0) links.push({ source: labels[i], target: labels[j], value: v, lineStyle: { width: Math.min(10, 0.6 + Math.sqrt(v) * 0.9) } }); }));
  return mount(el, base({
    tooltip: { ...base().tooltip, formatter: (p) => (p.dataType === 'edge' ? `${p.data.source} ↔ ${p.data.target}: <b>${p.data.value}</b> joint papers` : `<b>${p.name}</b>: ${p.value} cross-department papers`) },
    series: [{ type: 'graph', layout: 'circular', circular: { rotateLabel: true }, data: nodes, links, roam: false,
      label: { show: true, position: 'right', color: ink().t1, fontSize: 11.5 },
      lineStyle: { color: 'source', curveness: 0.3, opacity: 0.35 }, emphasis: { focus: 'adjacency', lineStyle: { opacity: 0.8 } } }],
  }));
}

export function scatter(el, { data, xName, yName, sizeKey = 'size', fmt }) {
  const ax = axisStyle();
  const maxS = Math.max(1, ...data.map((d) => d[sizeKey] || 1));
  return mount(el, base({
    grid: { left: 16, right: 24, top: 18, bottom: 30, containLabel: true },
    tooltip: { ...base().tooltip, trigger: 'item', formatter: fmt },
    xAxis: { type: 'value', name: xName, nameLocation: 'middle', nameGap: 26, nameTextStyle: { color: ink().t3, fontSize: 11.5 }, ...ax },
    yAxis: { type: 'value', name: yName, nameTextStyle: { color: ink().t3, fontSize: 11.5 }, ...ax },
    series: [{ type: 'scatter', data: data.map((d, i) => ({ value: [d.x, d.y], name: d.name, raw: d,
      symbolSize: 10 + 34 * Math.sqrt((d[sizeKey] || 1) / maxS), itemStyle: { color: PALETTE[i % PALETTE.length], opacity: 0.8, borderColor: ink().card, borderWidth: 2 } })),
      label: { show: true, formatter: (p) => p.name, position: 'top', color: ink().t2, fontSize: 11 } }],
  }));
}

export function boxplot(el, { categories, boxes, fmt }) {
  const ax = axisStyle();
  return mount(el, base({
    grid: { left: 8, right: 16, top: 14, bottom: 4, containLabel: true },
    tooltip: { ...base().tooltip, trigger: 'item', formatter: (p) => `<b>${p.name}</b><br>min ${p.data[1]} · median ${p.data[3]} · max ${p.data[5]}` },
    xAxis: { type: 'category', data: categories, ...ax, splitLine: { show: false } },
    yAxis: { type: 'value', ...ax, name: 'papers', nameTextStyle: { color: ink().t3, fontSize: 11 } },
    series: [{ type: 'boxplot', data: boxes, itemStyle: { color: '#E7EEFF', borderColor: PALETTE[0], borderWidth: 1.6 }, boxWidth: [18, 46] }],
  }));
}

export function spark(el, data, color) {
  return mount(el, {
    animation: false, grid: { left: 0, right: 0, top: 2, bottom: 2 },
    xAxis: { type: 'category', show: false, data: data.map((_, i) => i), boundaryGap: false },
    yAxis: { type: 'value', show: false, min: (v) => v.min - (v.max - v.min) * 0.15 },
    series: [{ type: 'line', data, smooth: 0.3, symbol: 'none', lineStyle: { width: 1.8, color: color || ink().accent },
      areaStyle: { color: color || ink().accent, opacity: 0.1 } }],
  });
}

export function paintSparks(root) {
  root.querySelectorAll('[data-spark]').forEach((el) => {
    try { spark(el, JSON.parse(el.dataset.spark)); } catch (e) { /* skip */ }
  });
}

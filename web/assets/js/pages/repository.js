import { api, qs, store } from '../api.js';
import { $, $$, card, confirmBox, crore, debounce, empty, esc, fail, icon, modal, num, paintIcons, pubLine, quart, status, toast } from '../ui.js';

const KINDS = { journal: 'Journal', conference: 'Conference', chapter: 'Book chapter', book: 'Book', preprint: 'Preprint' };

export async function render(el, { query, refreshCounts }) {
  const st = { tab: query.tab || 'publications', q: query.q || '', mine: query.mine === '1', status: query.status || '', kind: '', quartile: '', page: 1 };
  const verifier = store.can('outputs.verify');
  el.innerHTML = `<div class="ph"><div class="t"><div class="eyebrow">${esc(store.inst?.name || '')}</div><h1>Research records</h1>
      <p class="lead">The verified record of the institution's research. ${store.inst?.require_verification ? 'New entries wait for your HoD or the research cell to verify them before they count in reports.' : 'Records count as soon as they are added.'}</p></div>
      <div class="acts">${store.can('outputs.create') ? `<button class="btn" id="orcid">${icon('cloud-download')}Import from ORCID</button><button class="btn primary" id="add">${icon('plus')}Add</button>` : ''}</div></div>
    <nav class="tabs">${[['publications', 'Publications', 'file-text'], ['projects', 'Projects & grants', 'flask-conical'], ['patents', 'Patents', 'lightbulb']].map(([k, l, ic]) =>
      `<a href="javascript:void 0" data-tab="${k}" class="${st.tab === k ? 'on' : ''}">${icon(ic, 'i-sm')}${l}</a>`).join('')}</nav>
    <div class="filters">
      <span class="row grow" style="flex-wrap:nowrap">${icon('search')}<input class="input sm" id="q" value="${esc(st.q)}" placeholder="Title, keyword or author" style="border:0;box-shadow:none"></span>
      <div class="seg"><button data-mine="0" class="${st.mine ? '' : 'on'}">Institution</button><button data-mine="1" class="${st.mine ? 'on' : ''}">Mine</button></div>
      <select class="input sm" id="status" style="width:auto"><option value="">Any status</option><option value="verified">Verified</option><option value="pending">Pending</option><option value="rejected">Returned</option></select>
      <span id="extra"></span>
    </div><div id="list"></div>`;
  paintIcons(el);
  $('#status').value = st.status;

  const extra = () => {
    $('#extra').innerHTML = st.tab === 'publications' ? `<span class="row"><select class="input sm" id="kind" style="width:auto"><option value="">All types</option>${Object.entries(KINDS).map(([k, v]) => `<option value="${k}" ${st.kind === k ? 'selected' : ''}>${v}</option>`).join('')}</select>
      <select class="input sm" id="quartile" style="width:auto"><option value="">Any quartile</option>${['Q1', 'Q2', 'Q3', 'Q4'].map((q) => `<option ${st.quartile === q ? 'selected' : ''}>${q}</option>`).join('')}</select></span>` : '';
    $('#kind')?.addEventListener('change', (e) => { st.kind = e.target.value; st.page = 1; load(); });
    $('#quartile')?.addEventListener('change', (e) => { st.quartile = e.target.value; st.page = 1; load(); });
  };

  const verifyBtns = (entity, r) => r.can_verify ? `<div class="row" style="flex-wrap:nowrap"><button class="btn xs good" data-v="${entity}:${r.id}:verified">Verify</button><button class="btn xs bad" data-v="${entity}:${r.id}:rejected">Return</button></div>` : '';
  const load = async () => {
    const list = $('#list');
    list.innerHTML = '<div class="skel" style="height:300px"></div>';
    try {
      if (st.tab === 'publications') {
        const r = await api(`/api/publications${qs({ q: st.q, mine: st.mine ? 1 : '', status: st.status, kind: st.kind, quartile: st.quartile, page: st.page, size: 20 })}`);
        list.innerHTML = card(`${num(r.total)} publications`, r.rows.length ? `<div class="list">${r.rows.map((p) => pubLine(p, { actions: `<div class="stack" style="gap:6px;align-items:flex-end">
            ${p.status !== 'verified' ? status(p.status) : ''}${verifyBtns('publication', p)}
            ${p.can_edit && p.status !== 'verified' ? `<button class="btn xs ghost" data-del="${p.id}">${icon('trash-2', 'i-sm')}Delete</button>` : ''}</div>` })).join('')}</div>
          <div class="pager"><span>Page ${r.page} of ${Math.max(1, Math.ceil(r.total / r.size))}</span><span class="row"><button class="btn xs" data-pg="-1" ${r.page > 1 ? '' : 'disabled'}>Previous</button><button class="btn xs" data-pg="1" ${r.page * r.size < r.total ? '' : 'disabled'}>Next</button></span></div>`
          : empty('No publications match', st.mine ? 'Add your first one, or import from ORCID.' : 'Try clearing a filter.', 'file-text'),
          { actions: `<span class="chips">${Object.entries(r.facets.status).map(([k, v]) => `<span class="chip">${v} ${esc(k)}</span>`).join('')}</span>` });
      } else if (st.tab === 'projects') {
        const r = await api(`/api/projects${qs({ q: st.q, mine: st.mine ? 1 : '', status: st.status, page: st.page, size: 20 })}`);
        list.innerHTML = card(`${num(r.total)} projects · ${crore(r.amount)} sanctioned`, r.rows.length ? `<div class="list">${r.rows.map((j) => `<div class="it"><div class="body">
            <div class="ttl">${esc(j.title)}</div>
            <div class="meta"><b class="soft">${esc(j.agency)}</b><span>${esc(j.scheme || '')}</span><span>${j.start_year}–${j.end_year}</span>${status(j.stage)}${j.status !== 'verified' ? status(j.status) : ''}</div>
            <div class="meta">${j.members.map((m) => `<a href="#/people/${m.id}">${esc(m.name)}</a> <span class="muted">(${esc(m.role)}${m.inst !== store.inst?.short ? ' · ' + esc(m.inst) : ''})</span>`).join(', ')}</div></div>
            <div class="stack" style="gap:6px;align-items:flex-end"><b class="nowrap">${crore(j.amount)}</b>${verifyBtns('project', j)}</div></div>`).join('')}</div>
          <div class="pager"><span>Page ${r.page}</span><span class="row"><button class="btn xs" data-pg="-1" ${r.page > 1 ? '' : 'disabled'}>Previous</button><button class="btn xs" data-pg="1" ${r.page * r.size < r.total ? '' : 'disabled'}>Next</button></span></div>`
          : empty('No projects match', '', 'flask-conical'));
      } else {
        const r = await api(`/api/patents${qs({ q: st.q, mine: st.mine ? 1 : '', status: st.status })}`);
        list.innerHTML = card(`${num(r.total)} patents`, r.rows.length ? `<div class="list">${r.rows.map((x) => `<div class="it"><div class="body"><div class="ttl">${esc(x.title)}</div>
            <div class="meta"><span class="mono">${esc(x.number || '')}</span><span>${x.year}</span>${status(x.stage)}${x.status !== 'verified' ? status(x.status) : ''}
            <span>${x.inventors.map((i) => `<a href="#/people/${i.id}">${esc(i.name)}</a>`).join(', ')}</span></div></div>${verifyBtns('patent', x)}</div>`).join('')}</div>` : empty('No patents match', '', 'lightbulb'));
      }
      paintIcons(list);
      $$('[data-pg]', list).forEach((b) => b.onclick = () => { st.page += +b.dataset.pg; load(); window.scrollTo({ top: 0, behavior: 'smooth' }); });
      $$('[data-v]', list).forEach((b) => b.onclick = async () => {
        const [entity, id, decision] = b.dataset.v.split(':');
        let note = '';
        if (decision === 'rejected') {
          const r = await modal({ title: 'Return this record', body: '<label class="field"><span>Tell the author what to fix</span><textarea class="input" name="note"></textarea></label>',
            actions: [{ label: 'Cancel', cls: 'ghost' }, { label: 'Return to author', cls: 'bad', run: (ov) => ov.querySelector('[name=note]').value.trim() || ' ' }] });
          if (!r) return;
          note = r.trim();
        }
        try { await api(`/api/verify/${entity}/${id}`, { method: 'POST', body: { decision, note } }); toast(decision === 'verified' ? 'Verified' : 'Returned to the author'); refreshCounts?.(); load(); } catch (e) { fail(e); }
      });
      $$('[data-del]', list).forEach((b) => b.onclick = async () => {
        if (!(await confirmBox('Delete this publication?', 'It will be removed from RICE. This cannot be undone.', 'Delete', 'bad'))) return;
        try { await api(`/api/publications/${b.dataset.del}`, { method: 'DELETE' }); toast('Deleted'); load(); } catch (e) { fail(e); }
      });
    } catch (e) { list.innerHTML = empty(e.message, '', 'lock'); paintIcons(list); }
  };

  $$('[data-tab]', el).forEach((b) => b.onclick = () => { st.tab = b.dataset.tab; st.page = 1; $$('[data-tab]', el).forEach((x) => x.classList.toggle('on', x === b)); extra(); load(); });
  $$('[data-mine]', el).forEach((b) => b.onclick = () => { st.mine = b.dataset.mine === '1'; st.page = 1; $$('[data-mine]', el).forEach((x) => x.classList.toggle('on', x === b)); load(); });
  $('#q').oninput = debounce((e) => { st.q = e.target.value; st.page = 1; load(); }, 250);
  $('#status').onchange = (e) => { st.status = e.target.value; st.page = 1; load(); };
  $('#add')?.addEventListener('click', () => (st.tab === 'projects' ? addProject : st.tab === 'patents' ? addPatent : addPublication)(load));
  $('#orcid')?.addEventListener('click', () => importOrcid(load));
  extra();
  await load();
}

let peopleCache = null;
async function peopleList() {
  if (!peopleCache) peopleCache = (await api('/api/people?size=3000')).rows;
  return peopleCache;
}
const peopleOptions = (rows) => `<datalist id="ppl">${rows.map((p) => `<option value="${esc(p.name)}">${esc(p.designation || '')} · ${esc(p.dept || '')}</option>`).join('')}</datalist>`;

export async function addPublication(done) {
  const rows = await peopleList();
  const me = store.me.user;
  await modal({
    title: 'Add a publication', wide: true,
    body: `${peopleOptions(rows)}<div class="form-grid">
      <label class="field wide"><span>Title</span><input class="input" name="title" required></label>
      <label class="field"><span>Type</span><select class="input" name="kind">${Object.entries(KINDS).map(([k, v]) => `<option value="${k}">${v}</option>`).join('')}</select></label>
      <label class="field"><span>Year</span><input class="input" name="year" type="number" value="${new Date().getFullYear()}"></label>
      <label class="field"><span>Journal / conference</span><input class="input" name="venue"></label>
      <label class="field"><span>Quartile</span><select class="input" name="quartile"><option value="">Not ranked</option><option>Q1</option><option>Q2</option><option>Q3</option><option>Q4</option></select></label>
      <label class="field"><span>DOI</span><input class="input" name="doi" placeholder="10.xxxx/…"></label>
      <label class="field"><span>Citations so far</span><input class="input" name="citations" type="number" value="0"></label>
      <label class="field wide"><span>Co-authors from your institution</span><input class="input" name="co" list="ppl" placeholder="Type a name, press Enter"><small>Added: <span id="co-list">${esc(me.name)} (you)</span></small></label>
      <label class="field wide"><span>Other co-authors</span><textarea class="input" name="ext" style="min-height:60px" placeholder="One per line: Name, Affiliation, Country"></textarea></label>
      <label class="field wide"><span>Keywords</span><input class="input" name="keywords" placeholder="Separate with semicolons"><small>RICE tags UN SDGs automatically from the title and keywords.</small></label>
      <label class="check"><input type="checkbox" name="open_access">Open access</label>
      <label class="check"><input type="checkbox" name="internal">Visible inside the institution only</label></div>`,
    onMount: (ov) => {
      const co = [{ person_id: me.id, name: me.name }];
      const inp = ov.querySelector('[name=co]');
      const add = () => {
        const p = rows.find((x) => x.name.toLowerCase() === inp.value.trim().toLowerCase());
        if (p && !co.some((c) => c.person_id === p.id)) { co.push({ person_id: p.id, name: p.name }); ov.querySelector('#co-list').textContent = co.map((c) => c.name).join(', '); }
        inp.value = '';
      };
      inp.addEventListener('keydown', (e) => { if (e.key === 'Enter') { e.preventDefault(); add(); } });
      inp.addEventListener('change', add);
      ov.__co = co;
    },
    actions: [{ label: 'Cancel', cls: 'ghost' }, {
      label: 'Add publication', cls: 'primary', run: async (ov) => {
        const g = (n) => ov.querySelector(`[name=${n}]`);
        const ext = g('ext').value.split('\n').map((l) => l.split(',').map((x) => x.trim())).filter((x) => x[0]).map(([name, affil, country]) => ({ name, affil: affil || null, country: country || null }));
        const body = { title: g('title').value.trim(), kind: g('kind').value, year: +g('year').value, venue: g('venue').value.trim(), quartile: g('quartile').value || null,
          doi: g('doi').value.trim() || null, citations: +g('citations').value || 0, keywords: g('keywords').value.split(';').map((x) => x.trim()).filter(Boolean),
          open_access: g('open_access').checked, visibility: g('internal').checked ? 'internal' : 'public',
          authors: [...ov.__co.map((c) => ({ person_id: c.person_id })), ...ext] };
        if (body.title.length < 5) throw new Error('Add the full title.');
        const r = await api('/api/publications', { method: 'POST', body });
        toast(r.status === 'pending' ? 'Added — waiting for verification' : 'Added and verified');
        done?.();
      },
    }],
  });
}

async function addProject(done) {
  const rows = await peopleList();
  const me = store.me;
  await modal({
    title: 'Add a project or grant', wide: true,
    body: `${peopleOptions(rows)}<div class="form-grid">
      <label class="field wide"><span>Project title</span><input class="input" name="title"></label>
      <label class="field"><span>Funding agency</span><select class="input" name="agency">${me.agencies.map((a) => `<option>${esc(a)}</option>`).join('')}</select></label>
      <label class="field"><span>Scheme</span><input class="input" name="scheme" placeholder="e.g. Core Research Grant"></label>
      <label class="field"><span>Amount (₹ lakh)</span><input class="input" name="amount" type="number" step="0.1"></label>
      <label class="field"><span>Stage</span><select class="input" name="stage"><option value="submitted">Submitted — awaiting decision</option><option value="ongoing" selected>Sanctioned — ongoing</option><option value="completed">Completed</option><option value="not_funded">Not funded</option></select></label>
      <label class="field"><span>Start year</span><input class="input" name="start_year" type="number" value="${new Date().getFullYear()}"></label>
      <label class="field"><span>End year</span><input class="input" name="end_year" type="number" value="${new Date().getFullYear() + 2}"></label>
      <label class="field wide"><span>Co-PIs and members</span><input class="input" name="co" list="ppl" placeholder="Type a name, press Enter"><small>Team: <span id="co-list">${esc(me.user.name)} (PI)</span></small></label>
      <label class="field wide"><span>Keywords</span><input class="input" name="keywords" placeholder="Separate with semicolons"></label></div>`,
    onMount: (ov) => {
      const team = [{ person_id: me.user.id, role: 'PI', name: me.user.name }];
      const inp = ov.querySelector('[name=co]');
      const add = () => {
        const p = rows.find((x) => x.name.toLowerCase() === inp.value.trim().toLowerCase());
        if (p && !team.some((c) => c.person_id === p.id)) { team.push({ person_id: p.id, role: p.role === 'scholar' ? 'Scholar' : 'Co-PI', name: p.name }); ov.querySelector('#co-list').textContent = team.map((c) => `${c.name} (${c.role})`).join(', '); }
        inp.value = '';
      };
      inp.addEventListener('keydown', (e) => { if (e.key === 'Enter') { e.preventDefault(); add(); } });
      inp.addEventListener('change', add);
      ov.__team = team;
    },
    actions: [{ label: 'Cancel', cls: 'ghost' }, {
      label: 'Add project', cls: 'primary', run: async (ov) => {
        const g = (n) => ov.querySelector(`[name=${n}]`);
        const r = await api('/api/projects', { method: 'POST', body: { title: g('title').value.trim(), agency: g('agency').value, scheme: g('scheme').value.trim(), amount: +g('amount').value || 0,
          stage: g('stage').value, start_year: +g('start_year').value, end_year: +g('end_year').value, keywords: g('keywords').value.split(';').map((x) => x.trim()).filter(Boolean),
          members: ov.__team.map((t) => ({ person_id: t.person_id, role: t.role })) } });
        toast(r.status === 'pending' ? 'Added — waiting for verification' : 'Added and verified');
        done?.();
      },
    }],
  });
}

async function addPatent(done) {
  await modal({
    title: 'Add a patent',
    body: `<div class="form-grid"><label class="field wide"><span>Title</span><input class="input" name="title"></label>
      <label class="field"><span>Stage</span><select class="input" name="stage"><option value="filed">Filed</option><option value="published">Published</option><option value="granted">Granted</option></select></label>
      <label class="field"><span>Year</span><input class="input" name="year" type="number" value="${new Date().getFullYear()}"></label>
      <label class="field wide"><span>Application / patent number</span><input class="input" name="number"></label>
      <label class="field wide"><span>Keywords</span><input class="input" name="keywords" placeholder="Separate with semicolons"></label></div>`,
    actions: [{ label: 'Cancel', cls: 'ghost' }, {
      label: 'Add patent', cls: 'primary', run: async (ov) => {
        const g = (n) => ov.querySelector(`[name=${n}]`);
        const r = await api('/api/patents', { method: 'POST', body: { title: g('title').value.trim(), stage: g('stage').value, year: +g('year').value, number: g('number').value.trim(),
          keywords: g('keywords').value.split(';').map((x) => x.trim()).filter(Boolean) } });
        toast(r.status === 'pending' ? 'Added — waiting for verification' : 'Added and verified');
        done?.();
      },
    }],
  });
}

async function importOrcid(done) {
  const orcid = store.me.user.orcid || '';
  await modal({
    title: 'Import your publications from ORCID', wide: true,
    body: `<p class="soft" style="margin-top:0">RICE looks up your works in OpenAlex using your ORCID iD. You pick which ones to add; they go through normal verification.</p>
      <div class="row" style="flex-wrap:nowrap"><input class="input" id="oid" value="${esc(orcid)}" placeholder="0000-0002-1825-0097"><button class="btn" id="look">Look up</button></div>
      <div id="works" class="mt"></div>`,
    onMount: (ov) => {
      ov.querySelector('#look').onclick = async () => {
        const out = ov.querySelector('#works');
        out.innerHTML = '<div class="skel" style="height:160px"></div>';
        try {
          const r = await api('/api/me/openalex', { method: 'POST', body: { orcid: ov.querySelector('#oid').value.trim() } });
          ov.__works = r.works;
          out.innerHTML = r.works.length ? `<div class="list" style="max-height:380px;overflow:auto">${r.works.map((w) => `<label class="it" style="cursor:pointer"><input type="checkbox" data-w="${w.index}" ${w.duplicate ? 'disabled' : 'checked'} style="margin-top:4px">
            <div class="body"><div class="ttl">${esc(w.title)}</div><div class="meta"><span>${esc(w.venue || '')}</span><span>${w.year}</span><span>${w.citations} cites</span>${w.duplicate ? '<span class="st completed">already in RICE</span>' : ''}</div></div></label>`).join('')}</div>`
            : empty('No works found for this ORCID', '', 'search-x');
          paintIcons(out);
        } catch (e) { out.innerHTML = `<div class="callout warn">${icon('alert-triangle')}<span>${esc(e.message)}</span></div>`; paintIcons(out); }
      };
    },
    actions: [{ label: 'Cancel', cls: 'ghost' }, {
      label: 'Import selected', cls: 'primary', run: async (ov) => {
        const pick = [...ov.querySelectorAll('[data-w]:checked')].map((x) => +x.dataset.w);
        if (!pick.length) throw new Error('Look up your ORCID and tick at least one work.');
        const r = await api('/api/me/openalex', { method: 'POST', body: { orcid: ov.querySelector('#oid').value.trim(), commit: true, pick } });
        toast(`Imported ${r.added} works${r.status === 'pending' ? ' — waiting for verification' : ''}`);
        done?.();
      },
    }],
  });
}
export { quart };

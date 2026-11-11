import { api, store } from '../api.js';
import { $$, card, empty, esc, fail, icon, modal, paintIcons, status, timeAgo, toast, who } from '../ui.js';

export function requestCollab(person, topic = '') {
  return modal({
    title: `Collaborate with ${person.name}`,
    body: `<div class="stack" style="gap:12px">
      <div class="callout">${icon('info')}<span>${esc(person.name)} (${esc(person.inst || '')}) gets a notification and can accept or decline.
        Your message is visible only to them.</span></div>
      <label class="field"><span>Topic</span><input class="input" name="topic" value="${esc(topic)}"></label>
      <label class="field"><span>Message</span><textarea class="input" name="message" placeholder="What would you like to do together — a paper, a proposal, co-supervision?"></textarea></label></div>`,
    actions: [{ label: 'Cancel', cls: 'ghost' }, {
      label: 'Send request', cls: 'primary', run: async (ov) => {
        const message = ov.querySelector('[name=message]').value.trim();
        if (message.length < 10) throw new Error('Write a short message (at least 10 characters).');
        await api('/api/collab', { method: 'POST', body: { to: person.id, topic: ov.querySelector('[name=topic]').value.trim(), message } });
        toast(`Request sent to ${person.name}`);
      },
    }],
  });
}

export async function render(el, { refreshCounts }) {
  const draw = async () => {
    const { rows } = await api('/api/collab');
    const inc = rows.filter((r) => r.direction === 'incoming');
    const out = rows.filter((r) => r.direction === 'outgoing');
    const item = (r) => `<div class="it"><div class="body">
        ${r.other ? who(r.other, { sub: `${r.other.designation || ''} · ${r.other.dept || ''} · ${r.other.inst_name || ''}` }) : '<b>Removed account</b>'}
        <div class="mt" style="margin-top:10px"><span class="chip acc">${esc(r.topic || 'General')}</span> <span class="muted" style="font-size:12.5px">${timeAgo(r.created_at)}</span></div>
        <p style="margin:8px 0 0">${esc(r.message)}</p></div>
        <div class="stack" style="gap:6px;align-items:flex-end">${status(r.status)}
        ${r.direction === 'incoming' && r.status === 'pending' ? `<div class="row"><button class="btn sm good" data-acc="${r.id}">Accept</button><button class="btn sm bad" data-dec="${r.id}">Decline</button></div>` : ''}</div></div>`;
    el.innerHTML = `<div class="ph"><div class="t"><div class="eyebrow">Collaboration</div><h1>Requests</h1>
      <p class="lead">Researchers across RICE institutions can ask to work with you. Accepted requests show up as planned links in your network.</p></div>
      <div class="acts">${store.can('discover.experts') ? `<a class="btn primary" href="#/discover">${icon('radar')}Find collaborators</a>` : ''}</div></div>
      <div class="grid g2">${card(`Incoming <span class="badge n">${inc.filter((r) => r.status === 'pending').length}</span>`, inc.length ? `<div class="list">${inc.map(item).join('')}</div>` : empty('No requests yet', 'When someone asks to collaborate, it lands here.', 'inbox'))}
      ${card('Sent by you', out.length ? `<div class="list">${out.map(item).join('')}</div>` : empty('You have not sent any requests', 'Use Discover to find people working on your topics.', 'send'))}</div>`;
    paintIcons(el);
    $$('[data-acc],[data-dec]', el).forEach((b) => b.onclick = async () => {
      try {
        const accept = !!b.dataset.acc;
        await api(`/api/collab/${b.dataset.acc || b.dataset.dec}/respond`, { method: 'POST', body: { accept } });
        toast(accept ? 'Accepted — they have been notified' : 'Declined');
        refreshCounts?.();
        draw();
      } catch (e) { fail(e); }
    });
  };
  await draw();
}

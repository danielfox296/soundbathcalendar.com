/* Admin overlay (CAL-40) — the live site, editable when the admin is the one
 * looking at it.
 *
 * WHY THIS CAN EXIST AT ALL. The site is static (GitHub Pages), but the admin
 * service is a sibling host: soundbathcalendar.com and
 * admin.soundbathcalendar.com share a registrable domain, so a fetch between
 * them is same-SITE and only cross-ORIGIN. The admin's 30-day `ss_admin`
 * cookie is httpOnly + SameSite=Lax, and Lax rides same-site requests — so the
 * browser proves who you are without this file ever holding a token, and
 * without the cookie being loosened to SameSite=None. The service allows
 * exactly one credentialed CORS origin (this one).
 *
 * WHAT A VISITOR GETS: nothing. Not a request, not a byte of admin UI. The
 * probe is opt-in (see LATCH) and every write is 401'd without the cookie, so
 * the worst case for a stranger who forces the latch on is one 401.
 *
 * WHAT THE PAGE CAN HONESTLY DO. Saving writes to the database immediately,
 * but this page is a build artifact — the visible HTML only catches up when the
 * site rebuilds (the service dispatches that automatically, ~2 min). So an edit
 * repaints what it safely can and SAYS the rest is coming. Pretending the whole
 * page re-rendered would be the lie; a card that quietly disagrees with the
 * database is worse than one that admits it is stale.
 */
(function () {
  'use strict';

  var LATCH = 'sbc_admin';          // localStorage flag; ?admin=1 sets it, ?admin=0 clears
  // typeof, not ||: an explicit '' (same-origin, how a local harness points
  // this at a stub) is a real answer, and || would discard it.
  var API = typeof window.SBC_ADMIN_ORIGIN === 'string'
    ? window.SBC_ADMIN_ORIGIN
    : 'https://admin.soundbathcalendar.com';

  /* ---- opt-in ---------------------------------------------------------- */
  // Deliberately NOT a probe on every pageview: an anonymous visitor must cost
  // the admin service zero requests. Turn it on once per browser with
  // ?admin=1; ?admin=0 turns it back off.
  var store;
  try { store = window.localStorage; } catch (e) { return; }   // private mode → no overlay
  if (/[?&]admin=1(&|$)/.test(location.search)) store.setItem(LATCH, '1');
  if (/[?&]admin=0(&|$)/.test(location.search)) store.removeItem(LATCH);
  if (store.getItem(LATCH) !== '1') return;

  /* ---- tiny DOM helpers ------------------------------------------------ */
  function el(tag, cls, text) {
    var n = document.createElement(tag);
    if (cls) n.className = cls;
    // textContent, never innerHTML: listing strings are third-party scrape
    // data, and this file is the one place they'd meet a parser.
    if (text != null) n.textContent = text;
    return n;
  }

  function api(path, opts) {
    opts = opts || {};
    return fetch(API + path, {
      method: opts.method || 'GET',
      credentials: 'include',
      headers: opts.body ? { 'content-type': 'application/json' } : undefined,
      body: opts.body ? JSON.stringify(opts.body) : undefined
    }).then(function (res) {
      return res.json().catch(function () { return {}; }).then(function (json) {
        if (!res.ok) throw Object.assign(new Error(json.error || 'request_failed'), {
          status: res.status, code: json.error
        });
        return json;
      });
    });
  }

  /* ---- styles ---------------------------------------------------------- */
  // Kept in this file rather than styles.css: the overlay is admin chrome, not
  // site design, and it must never ship a byte of weight to a visitor.
  var CSS = [
    '.sbc-adm-btn{position:absolute;top:.5rem;right:.5rem;z-index:6;font:600 .68rem/1 var(--font-display,system-ui);',
    'letter-spacing:.09em;text-transform:uppercase;padding:.4rem .55rem;cursor:pointer;',
    'background:var(--signal,#B93A2B);color:#fff;border:0;border-radius:2px;opacity:.85}',
    '.sbc-adm-btn:hover{opacity:1}',
    '[data-event-id]{position:relative}',
    '.sbc-adm-stale{outline:2px dashed var(--signal,#B93A2B);outline-offset:3px}',
    '.sbc-adm-gone{opacity:.35;filter:grayscale(1)}',
    '.sbc-adm-bar{position:fixed;left:0;bottom:0;z-index:9998;display:flex;gap:.75rem;align-items:center;',
    'background:var(--ink,#352F5C);color:#fff;font:600 .72rem/1 var(--font-display,system-ui);',
    'letter-spacing:.08em;text-transform:uppercase;padding:.55rem .8rem}',
    '.sbc-adm-bar a,.sbc-adm-bar button{color:#fff;background:none;border:0;text-decoration:underline;',
    'cursor:pointer;font:inherit;padding:0}',
    '.sbc-adm-veil{position:fixed;inset:0;z-index:9999;background:rgba(0,0,0,.55);display:flex;',
    'align-items:flex-start;justify-content:center;overflow:auto;padding:2rem 1rem}',
    '.sbc-adm-modal{background:var(--paper,#F5F2ED);color:var(--ink,#352F5C);max-width:38rem;width:100%;',
    'padding:1.25rem;font-family:var(--font-body,system-ui)}',
    '.sbc-adm-modal h2{font:700 1.1rem/1.2 var(--font-display,system-ui);margin:0 0 .75rem}',
    '.sbc-adm-modal label{display:block;font-size:.72rem;letter-spacing:.08em;text-transform:uppercase;',
    'margin:.7rem 0 .2rem;opacity:.75}',
    '.sbc-adm-modal input,.sbc-adm-modal textarea,.sbc-adm-modal select{width:100%;padding:.45rem .5rem;',
    'font:inherit;font-size:.95rem;border:1px solid var(--field-line,#8a86a0);background:#fff;color:inherit}',
    '.sbc-adm-tags{display:flex;flex-wrap:wrap;gap:.15rem .9rem;margin:.2rem 0 .4rem}',
    '.sbc-adm-tags label{display:inline-flex;align-items:center;gap:.3rem;margin:0;text-transform:none;',
    'letter-spacing:0;font-size:.8rem;opacity:1}',
    '.sbc-adm-tags input{width:auto}',
    '.sbc-adm-axis{font-size:.65rem;letter-spacing:.1em;text-transform:uppercase;opacity:.6;margin-top:.5rem}',
    '.sbc-adm-row{display:flex;gap:.5rem;flex-wrap:wrap;align-items:center;margin-top:1rem}',
    '.sbc-adm-row button{font:600 .8rem/1 var(--font-display,system-ui);padding:.55rem .8rem;cursor:pointer;',
    'border:1px solid var(--ink,#352F5C);background:var(--ink,#352F5C);color:var(--paper,#F5F2ED)}',
    '.sbc-adm-row button.ghost{background:none;color:var(--ink,#352F5C)}',
    '.sbc-adm-row button.danger{background:none;border-color:var(--signal,#B93A2B);color:var(--signal,#B93A2B)}',
    '.sbc-adm-msg{margin-top:.6rem;font-size:.85rem;min-height:1.2em}',
    '.sbc-adm-toast{position:fixed;left:50%;bottom:3.2rem;transform:translateX(-50%);z-index:9999;',
    'background:var(--ink,#352F5C);color:#fff;padding:.6rem .9rem;font:600 .8rem/1.3 var(--font-display,system-ui);',
    'max-width:26rem;text-align:center}'
  ].join('');

  function injectCss() {
    var s = el('style');
    s.textContent = CSS;
    document.head.appendChild(s);
  }

  function toast(text) {
    // One at a time: a lingering older toast reads as the verdict on the
    // action you just took.
    var prev = document.querySelector('.sbc-adm-toast');
    if (prev) prev.remove();
    var t = el('div', 'sbc-adm-toast', text);
    document.body.appendChild(t);
    setTimeout(function () { t.remove(); }, 5000);
  }

  /* ---- the editor ------------------------------------------------------ */
  var FIELDS = [
    ['name', 'Event name', 'text'],
    ['starts_at', 'Date & time (Denver)', 'datetime-local'],
    ['venue', 'Venue', 'text'],
    ['address', 'Address', 'text'],
    ['neighborhood', 'Neighborhood (Denver only)', 'text'],
    ['price', 'Price', 'text'],
    ['ticket_url', 'Ticket URL', 'text'],
    ['image_url', 'Image URL', 'text'],
    ['facilitator', 'Facilitator', 'text'],
    ['description', 'Description (factual)', 'textarea'],
    ['note', 'Your note (renders on the card)', 'textarea']
  ];

  function openEditor(id, card) {
    var veil = el('div', 'sbc-adm-veil');
    var modal = el('div', 'sbc-adm-modal');
    veil.appendChild(modal);
    modal.appendChild(el('h2', null, 'Loading…'));
    document.body.appendChild(veil);

    // Click the veil (never the modal) to dismiss; Esc too.
    veil.addEventListener('click', function (e) { if (e.target === veil) close(); });
    function onKey(e) { if (e.key === 'Escape') close(); }
    document.addEventListener('keydown', onKey);
    function close() {
      document.removeEventListener('keydown', onKey);
      veil.remove();
    }

    api('/admin/api/events/' + encodeURIComponent(id)).then(function (data) {
      modal.textContent = '';
      modal.appendChild(el('h2', null, data.event.name));
      modal.appendChild(el('p', 'sbc-adm-axis', data.event.operator + ' · ' + data.event.status));

      var inputs = {};
      FIELDS.forEach(function (f) {
        modal.appendChild(el('label', null, f[1]));
        var input = el(f[2] === 'textarea' ? 'textarea' : 'input');
        if (f[2] !== 'textarea') input.type = f[2];
        if (f[2] === 'textarea') input.rows = 2;
        input.value = data.event[f[0]] || '';
        modal.appendChild(input);
        inputs[f[0]] = input;
      });

      // City is a closed list — the service rejects anything off it.
      modal.appendChild(el('label', null, 'City'));
      var city = el('select');
      (data.cities || []).forEach(function (c) {
        var o = el('option', null, c);
        o.value = c;
        if (c === data.event.city) o.selected = true;
        city.appendChild(o);
      });
      modal.appendChild(city);

      // Tags, grouped by axis, pre-checked from the row.
      var current = {};
      (data.event.tags || []).forEach(function (t) { current[t] = true; });
      var boxes = [];
      modal.appendChild(el('label', null, 'Tags'));
      (data.tag_axes || []).forEach(function (axis) {
        modal.appendChild(el('div', 'sbc-adm-axis', axis.label));
        var wrap = el('div', 'sbc-adm-tags');
        axis.tags.forEach(function (t) {
          var lab = el('label');
          var box = el('input');
          box.type = 'checkbox';
          box.value = t.slug;
          box.checked = !!current[t.slug];
          lab.appendChild(box);
          lab.appendChild(document.createTextNode(t.label));
          wrap.appendChild(lab);
          boxes.push(box);
        });
        modal.appendChild(wrap);
      });

      var msg = el('p', 'sbc-adm-msg');
      var actions = el('div', 'sbc-adm-row');
      var save = el('button', null, 'Save');
      var cancel = el('button', 'ghost', 'Cancel');
      var pull = el('button', 'ghost', 'Take off the site');
      var reject = el('button', 'danger', 'Reject…');
      var del = el('button', 'danger', 'Delete…');
      [save, cancel, pull, reject, del].forEach(function (b) { actions.appendChild(b); });
      modal.appendChild(actions);
      modal.appendChild(msg);

      cancel.addEventListener('click', close);

      save.addEventListener('click', function () {
        save.disabled = true;
        msg.textContent = 'Saving…';
        var body = { city: city.value, tags: boxes.filter(function (b) { return b.checked; })
          .map(function (b) { return b.value; }) };
        FIELDS.forEach(function (f) { body[f[0]] = inputs[f[0]].value; });
        body.source_url = data.event.source_url || '';
        api('/admin/api/events/' + encodeURIComponent(id), { method: 'POST', body: body })
          .then(function () {
            close();
            repaint(card, body);
            toast(inputs.name.value + ' saved. This page is a build artifact, so it '
              + 'catches up on the next rebuild (~2 min).');
          })
          .catch(function (err) {
            save.disabled = false;
            msg.textContent = err.code === 'duplicate_event'
              ? 'Those details already belong to another listing.'
              : err.code === 'unknown_city'
                ? 'That city is not one of the four sections.'
                : 'Could not save (' + (err.code || err.message) + ').';
          });
      });

      function act(action, extra, confirmText) {
        if (confirmText && !window.confirm(confirmText)) return;
        msg.textContent = 'Working…';
        var body = { action: action };
        if (extra) body.rejection_note = extra;
        api('/admin/api/events/' + encodeURIComponent(id) + '/action', { method: 'POST', body: body })
          .then(function () {
            close();
            if (card) card.classList.add('sbc-adm-gone');
            toast('Off the calendar. The page catches up on the next rebuild (~2 min).');
          })
          .catch(function (err) { msg.textContent = 'Failed (' + (err.code || err.message) + ').'; });
      }

      // Un-approve first and unqualified: it is the reversible one.
      pull.addEventListener('click', function () { act('unapprove'); });
      reject.addEventListener('click', function () {
        var why = window.prompt('Why? (kept forever, so the pulls never bring it back)');
        if (why === null) return;
        act('reject', why);
      });
      del.addEventListener('click', function () {
        act('delete', null, 'Delete this listing entirely? No tombstone, so a later pull may find it again. Reject instead if you want it gone for good.');
      });
    }).catch(function (err) {
      modal.textContent = '';
      modal.appendChild(el('h2', null, err.status === 404
        ? 'That listing is gone.'
        : 'Could not load it (' + (err.code || err.message) + ').'));
      var row = el('div', 'sbc-adm-row');
      var ok = el('button', 'ghost', 'Close');
      ok.addEventListener('click', close);
      row.appendChild(ok);
      modal.appendChild(row);
    });
  }

  /* Repaint only what this page can repaint honestly: the visible name, and a
   * dashed outline saying the rest of the card is now behind the database. */
  function repaint(card, body) {
    if (!card) return;
    var name = card.querySelector('.cal-row__name a, .cal-row__name, h1');
    if (name && body.name) name.textContent = body.name;
    card.classList.add('sbc-adm-stale');
  }

  /* ---- mount ----------------------------------------------------------- */
  function mount() {
    injectCss();

    var bar = el('div', 'sbc-adm-bar');
    bar.appendChild(el('span', null, 'Admin'));
    var link = el('a', null, 'Full admin');
    link.href = API + '/admin/calendar';
    bar.appendChild(link);
    var off = el('button', null, 'Turn off');
    off.addEventListener('click', function () {
      store.removeItem(LATCH);
      location.reload();
    });
    bar.appendChild(off);
    document.body.appendChild(bar);

    var targets = document.querySelectorAll('[data-event-id]');
    Array.prototype.forEach.call(targets, function (card) {
      var btn = el('button', 'sbc-adm-btn', 'Edit');
      btn.setAttribute('aria-label', 'Edit this listing');
      // The whole card is a stretched link surface — stop the click before it
      // navigates to the event page.
      btn.addEventListener('click', function (e) {
        e.preventDefault();
        e.stopPropagation();
        openEditor(card.getAttribute('data-event-id'), card);
      });
      card.appendChild(btn);
    });

    if (!targets.length) bar.appendChild(el('span', null, 'no listings here'));
  }

  // One credentialed probe, only for a browser that opted in. A 401 (not logged
  // in, or the session expired) simply means no overlay — the page stays a
  // perfectly ordinary public page.
  api('/admin/auth/me')
    .then(function () {
      if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', mount);
      } else {
        mount();
      }
    })
    .catch(function () { /* not signed in — nothing to do, and nothing to say */ });
})();

// Calendar filters — progressive enhancement (Track B B.5 + CAL-01 tags +
// CAL-05 near-me distance sort).
//
// With JS blocked, the filter bar stays hidden (via its `hidden` attribute) and
// every row shows: the page is fully usable. With JS, this reveals the bar and
// filters rows by area + free/donation + tags, then hides any band whose rows
// all fall away (so no empty "This weekend" heading is left behind) and shows a
// no-results line when nothing matches. Rows carry data-city / data-free /
// data-tags; the [hidden] display:none is enforced in styles.css since .cal-row
// is display:grid.
//
// Tag semantics: OR across the selected tags — a row passes when it carries AT
// LEAST ONE checked tag (the forgiving "show me gong baths or crystal bowls"
// reading). Area and free/donation still AND with the tag result.
//
// Near-me (CAL-05): a "Sort by distance" toggle (revealed only when rows carry
// coordinates) asks for the visitor's location, then flattens the temporal
// bands into a single "Nearest first" list with a distance chip on each located
// row. Toggling off restores the date-ordered bands. Denial / no-geolocation
// degrades to the default date order with a short inline note.
//
// Bands-as-filters (CAL-16): with JS, the temporal jump links (Today/Tonight ·
// This weekend · …) double as single-select filter chips — tap one to show only
// that window, tap it again to clear. Each row records its band id up front
// (before near-me ever moves DOM nodes), so the band filter keeps working
// inside the flat "Nearest first" list, and the jump-nav now stays visible in
// near mode (the chips are filters there, not jumps). The FAQ link carries no
// data-band and keeps its plain jump behaviour; with JS off every link is a
// plain in-page anchor, unchanged.
//
// Clear-all + off-screen indicator (CAL-UX-10): a "Clear filters" button in
// the bar (revealed only while any filter or the near-me sort is active)
// resets every facet at once. Below the rail breakpoint the bar is inline and
// scrolls away, so a fixed "Filters on · Clear" chip surfaces whenever
// filters are active AND the bar is off-viewport — otherwise a filtered-down
// list reads as a quiet page with sound baths missing. The no-results line is
// an aria-live status region so the empty state is announced, not just shown.
(function () {
  'use strict';
  var bar = document.querySelector('[data-cal-filters]');
  if (!bar) return;
  bar.hidden = false;

  var citySel = bar.querySelector('[data-filter-city]');
  var freeChk = bar.querySelector('[data-filter-free]');
  var tagChks = [].slice.call(bar.querySelectorAll('[data-filter-tag]'));
  var noResults = document.querySelector('[data-cal-noresults]');
  var noResultsText = noResults ? noResults.textContent : '';
  var rows = [].slice.call(document.querySelectorAll('.cal-row'));
  var bands = [].slice.call(document.querySelectorAll('.cal-band'));
  var jump = document.querySelector('.cal-jump');

  // CAL-16 bands-as-filters. Record each row's band id NOW, while every row
  // still sits inside its original band — near-me reparents rows later.
  var bandChips = jump
    ? [].slice.call(jump.querySelectorAll('a[data-band]')) : [];
  var bandFilter = '';
  function bandOf(el) {
    for (var n = el.parentNode; n && n !== document; n = n.parentNode) {
      if (n.classList && n.classList.contains('cal-band')) return n.id || '';
    }
    return '';
  }
  rows.forEach(function (r) { r._bandId = bandOf(r); });

  function selectedTags() {
    var out = [];
    tagChks.forEach(function (chk) {
      if (chk.checked) out.push(chk.getAttribute('data-filter-tag'));
    });
    return out;
  }

  function rowHasAnyTag(row, wanted) {
    if (wanted.length === 0) return true;
    var have = (row.getAttribute('data-tags') || '').split(' ');
    for (var i = 0; i < wanted.length; i++) {
      if (have.indexOf(wanted[i]) !== -1) return true;
    }
    return false;
  }

  function apply() {
    var city = citySel ? citySel.value : '';
    var freeOnly = freeChk ? freeChk.checked : false;
    var tags = selectedTags();

    rows.forEach(function (row) {
      var okCity = !city || row.getAttribute('data-city') === city;
      var okFree = !freeOnly || row.getAttribute('data-free') === '1';
      var okTags = rowHasAnyTag(row, tags);
      var okBand = !bandFilter || row._bandId === bandFilter;
      row.hidden = !(okCity && okFree && okTags && okBand);
    });

    // In near mode the rows live in the flat list, so the (now-empty) bands stay
    // hidden regardless; in date mode a band hides when all its rows fall away.
    bands.forEach(function (band) {
      band.hidden = nearActive
        || band.querySelectorAll('.cal-row:not([hidden])').length === 0;
    });

    if (noResults) {
      var anyShown = rows.some(function (r) { return !r.hidden; });
      if (anyShown) {
        noResults.hidden = true;
      } else if (noResults.hidden) {
        // Becoming visible: rewrite the text too, so the aria-live region
        // sees a fresh node — some screen readers skip a bare hidden-flip.
        noResults.hidden = false;
        noResults.textContent = noResultsText;
      }
    }

    syncClear();  // CAL-UX-10: every path that changes filter state ends here
  }

  if (citySel) citySel.addEventListener('change', apply);
  if (freeChk) freeChk.addEventListener('change', apply);
  tagChks.forEach(function (chk) { chk.addEventListener('change', apply); });

  // ---- Bands as filter chips (CAL-16) -------------------------------------
  // Single-select: the bands partition time, so only one window can be active.
  // Tapping the active chip clears it. The chips stay plain jump anchors with
  // JS off (this handler never runs), so preventDefault is safe here.
  function setBandFilter(id) {
    bandFilter = id;
    bandChips.forEach(function (chip) {
      chip.setAttribute('aria-pressed',
        chip.getAttribute('data-band') === id ? 'true' : 'false');
    });
    apply();
  }

  if (bandChips.length) {
    jump.setAttribute('aria-label', 'Filter by time');
    bandChips.forEach(function (chip) {
      chip.setAttribute('role', 'button');
      chip.setAttribute('aria-pressed', 'false');
      chip.addEventListener('click', function (e) {
        e.preventDefault();
        var id = chip.getAttribute('data-band');
        setBandFilter(bandFilter === id ? '' : id);
      });
      // role="button" promises Space activation; anchors only get Enter free.
      chip.addEventListener('keydown', function (e) {
        if (e.key === ' ' || e.key === 'Spacebar') {
          e.preventDefault();
          chip.click();
        }
      });
    });
  }

  // ---- Near-me distance sort (CAL-05) -------------------------------------
  var nearBtn = bar.querySelector('[data-nearme]');
  var nearActive = false;
  var nearWrap = null, nearList = null, nearNote = null;

  function coordsOf(row) {
    var lat = parseFloat(row.getAttribute('data-lat'));
    var lng = parseFloat(row.getAttribute('data-lng'));
    if (isNaN(lat) || isNaN(lng)) return null;
    return { lat: lat, lng: lng };
  }

  // Great-circle distance in miles between two {lat,lng} points.
  function haversineMiles(a, b) {
    var R = 3958.8, rad = Math.PI / 180;
    var dLat = (b.lat - a.lat) * rad, dLng = (b.lng - a.lng) * rad;
    var la1 = a.lat * rad, la2 = b.lat * rad;
    var h = Math.sin(dLat / 2) * Math.sin(dLat / 2)
      + Math.cos(la1) * Math.cos(la2) * Math.sin(dLng / 2) * Math.sin(dLng / 2);
    return 2 * R * Math.asin(Math.min(1, Math.sqrt(h)));
  }

  function fmtMiles(mi) {
    return (mi < 10 ? mi.toFixed(1) : String(Math.round(mi))) + ' mi';
  }

  function setChip(row, mi) {
    var marks = row.querySelector('.cal-row__marks');
    if (!marks) return;
    var chip = row.querySelector('.cal-row__dist');
    if (!chip) {
      chip = document.createElement('span');
      chip.className = 'cal-row__dist';
      marks.appendChild(chip);
    }
    chip.textContent = fmtMiles(mi);
  }

  function clearChips() {
    rows.forEach(function (r) {
      var chip = r.querySelector('.cal-row__dist');
      if (chip) chip.parentNode.removeChild(chip);
    });
  }

  function note(msg) {
    if (!nearNote) return;
    nearNote.textContent = msg || '';
    nearNote.hidden = !msg;
  }

  // Build the flat-list container once, lazily (only if the toggle is used).
  function ensureNearList() {
    if (nearWrap || !bands.length) return;
    nearWrap = document.createElement('section');
    nearWrap.className = 'cal-band cal-nearband';
    nearWrap.hidden = true;
    var h2 = document.createElement('h2');
    h2.className = 'cal-band__h2';
    h2.textContent = 'Nearest first';
    nearList = document.createElement('div');
    nearList.className = 'cal-rows';
    nearWrap.appendChild(h2);
    nearWrap.appendChild(nearList);
    bands[0].parentNode.insertBefore(nearWrap, bands[0]);
  }

  function activate(pos) {
    ensureNearList();
    if (!nearList) return;
    nearActive = true;
    var located = [], unlocated = [];
    rows.forEach(function (r) {
      var c = coordsOf(r);
      if (c) { r._distMi = haversineMiles(pos, c); located.push(r); }
      else { unlocated.push(r); }
    });
    located.sort(function (a, b) { return a._distMi - b._distMi; });
    // Located rows nearest-first with a chip; unlocated rows trail, no chip.
    located.forEach(function (r) { setChip(r, r._distMi); nearList.appendChild(r); });
    unlocated.forEach(function (r) { nearList.appendChild(r); });
    // CAL-16: the jump-nav stays visible in near mode — its band links are
    // filter chips now, and they still apply inside the flat list.
    nearWrap.hidden = false;
    nearBtn.setAttribute('aria-pressed', 'true');
    nearBtn.textContent = 'Sort by distance';
    note('');
    apply();  // reassert the active filters within the flat list
  }

  function deactivate() {
    nearActive = false;
    // Restore rows to their original bands. `rows` is in original document
    // order, so appending each back to its recorded parent rebuilds each band
    // in order.
    rows.forEach(function (r) { r._origParent.appendChild(r); });
    clearChips();
    if (nearWrap) nearWrap.hidden = true;
    nearBtn.setAttribute('aria-pressed', 'false');
    nearBtn.textContent = 'Sort by distance';
    note('');
    apply();
  }

  if (nearBtn) {
    // Reveal the toggle only if geolocation exists AND some row is located —
    // otherwise it could never do anything, so leave it hidden.
    var anyCoords = rows.some(function (r) { return coordsOf(r); });
    if (navigator.geolocation && anyCoords) {
      rows.forEach(function (r) { r._origParent = r.parentNode; });
      nearBtn.hidden = false;
      // A small inline note for denial / errors, placed right below the bar.
      nearNote = document.createElement('p');
      nearNote.className = 'cal-empty cal-nearnote';
      nearNote.hidden = true;
      nearNote.setAttribute('role', 'status');
      bar.parentNode.insertBefore(nearNote, bar.nextSibling);
      nearBtn.addEventListener('click', function () {
        if (nearActive) { deactivate(); return; }
        note('');
        nearBtn.disabled = true;
        nearBtn.textContent = 'Locating…';
        navigator.geolocation.getCurrentPosition(function (p) {
          nearBtn.disabled = false;
          activate({ lat: p.coords.latitude, lng: p.coords.longitude });
        }, function (err) {
          nearBtn.disabled = false;
          nearBtn.textContent = 'Sort by distance';
          note(err && err.code === 1
            ? 'Location access was denied — showing sessions by date.'
            : 'Couldn’t get your location — showing sessions by date.');
        }, { enableHighAccuracy: false, timeout: 10000, maximumAge: 600000 });
      });
    }
  }

  // ---- Clear-all + off-screen indicator (CAL-UX-10) -----------------------
  // anyActive() is the single "is anything filtering/sorting?" predicate; the
  // bar's clear button and the floating chip both key off it via syncClear(),
  // which rides on the end of apply() — every state change funnels through.
  var clearBtn = bar.querySelector('[data-filter-clear]');

  // The floating chip is JS-created (like the near-me note): it can only ever
  // matter with JS running, so no-JS pages never carry the markup. It lands
  // right after the bar, so its tab-order slot is beside the controls it
  // clears. position:fixed via .cal-filterpill; CSS hides it at >=1080px,
  // where the CAL-23 rail keeps the bar sticky-visible anyway.
  var pill = document.createElement('button');
  pill.type = 'button';
  pill.className = 'cal-filterpill';
  pill.hidden = true;
  pill.textContent = 'Filters on · Clear';
  bar.parentNode.insertBefore(pill, bar.nextSibling);

  // Off-viewport tracking. The sticky masthead covers the top of the screen,
  // so shrink the observed area to match (the 90px is the house
  // scroll-margin-top): a bar sitting under the masthead is off-screen for
  // this purpose. No IntersectionObserver → the chip just never shows; the
  // bar's own clear button still works.
  var barOffscreen = false;
  if ('IntersectionObserver' in window) {
    new IntersectionObserver(function (entries) {
      barOffscreen = !entries[entries.length - 1].isIntersecting;
      syncPill();
    }, { rootMargin: '-90px 0px 0px 0px' }).observe(bar);
  }

  function anyActive() {
    return !!(citySel && citySel.value) || !!(freeChk && freeChk.checked)
      || selectedTags().length > 0 || !!bandFilter || nearActive;
  }

  function syncPill() {
    pill.hidden = !(anyActive() && barOffscreen);
  }

  function syncClear() {
    if (clearBtn) clearBtn.hidden = !anyActive();
    syncPill();
  }

  function clearAll() {
    if (citySel) citySel.value = '';
    if (freeChk) freeChk.checked = false;
    tagChks.forEach(function (chk) { chk.checked = false; });
    if (nearActive) deactivate();
    setBandFilter('');  // re-applies; syncClear() rides on apply()
    // Hand focus to the bar's first control — the affordance just clicked
    // hides itself. preventScroll, then jump the bar into view INSTANTLY
    // (only when it's actually off-screen, i.e. a chip tap): restoring 50+
    // rows re-anchors the scroll position, and a several-thousand-px smooth
    // scroll through a reflowed list is disorienting. "Clear" returns the
    // seeker to the head of the restored full list.
    var first = bar.querySelector('select, input');
    if (first) {
      try { first.focus({ preventScroll: true }); } catch (e) { first.focus(); }
    }
    if (barOffscreen) {
      try { bar.scrollIntoView({ behavior: 'instant', block: 'start' }); }
      catch (e2) { bar.scrollIntoView(true); }
    }
  }

  if (clearBtn) clearBtn.addEventListener('click', clearAll);
  pill.addEventListener('click', clearAll);

  apply();
})();

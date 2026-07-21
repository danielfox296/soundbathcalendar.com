// Calendar filters — progressive enhancement (Track B B.5 + CAL-01 tags).
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
(function () {
  'use strict';
  var bar = document.querySelector('[data-cal-filters]');
  if (!bar) return;
  bar.hidden = false;

  var citySel = bar.querySelector('[data-filter-city]');
  var freeChk = bar.querySelector('[data-filter-free]');
  var tagChks = [].slice.call(bar.querySelectorAll('[data-filter-tag]'));
  var noResults = document.querySelector('[data-cal-noresults]');
  var rows = [].slice.call(document.querySelectorAll('.cal-row'));
  var bands = [].slice.call(document.querySelectorAll('.cal-band'));

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
      row.hidden = !(okCity && okFree && okTags);
    });

    bands.forEach(function (band) {
      band.hidden = band.querySelectorAll('.cal-row:not([hidden])').length === 0;
    });

    if (noResults) {
      noResults.hidden = rows.some(function (r) { return !r.hidden; });
    }
  }

  if (citySel) citySel.addEventListener('change', apply);
  if (freeChk) freeChk.addEventListener('change', apply);
  tagChks.forEach(function (chk) { chk.addEventListener('change', apply); });
  apply();
})();

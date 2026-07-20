// Calendar filters — progressive enhancement (Track B B.5).
//
// With JS blocked, the filter bar stays hidden (via its `hidden` attribute) and
// every row shows: the page is fully usable. With JS, this reveals the bar and
// filters rows by area + free/donation, then hides any band whose rows all fall
// away (so no empty "This weekend" heading is left behind) and shows a
// no-results line when nothing matches. Rows carry data-city / data-free; the
// [hidden] display:none is enforced in styles.css since .cal-row is display:grid.
(function () {
  'use strict';
  var bar = document.querySelector('[data-cal-filters]');
  if (!bar) return;
  bar.hidden = false;

  var citySel = bar.querySelector('[data-filter-city]');
  var freeChk = bar.querySelector('[data-filter-free]');
  var noResults = document.querySelector('[data-cal-noresults]');
  var rows = [].slice.call(document.querySelectorAll('.cal-row'));
  var bands = [].slice.call(document.querySelectorAll('.cal-band'));

  function apply() {
    var city = citySel ? citySel.value : '';
    var freeOnly = freeChk ? freeChk.checked : false;

    rows.forEach(function (row) {
      var okCity = !city || row.getAttribute('data-city') === city;
      var okFree = !freeOnly || row.getAttribute('data-free') === '1';
      row.hidden = !(okCity && okFree);
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
  apply();
})();

/**
 * Training Management System — generator.js
 * ------------------------------------------------------------------------
 * Small shared helpers used by the two public, no-login generator pages:
 *   - scheme_of_work_user.html
 *   - lesson_plan_user.html
 *
 * Both pages receive the *entire* live curriculum (sectors, trades,
 * levels, trade/level links, modules, learning outcomes, indicative
 * contents, trainers, logos) as one JSON payload rendered into a
 * <script type="application/json" id="tms-data"> tag by the view. These
 * helpers turn that payload into cascading <select> options and provide
 * a couple of formatting/print utilities so the page-specific scripts
 * stay focused on layout, not plumbing.
 * ------------------------------------------------------------------------
 */

(function () {
  'use strict';

  function readData(elementId) {
    var el = document.getElementById(elementId || 'tms-data');
    if (!el) return null;
    try {
      return JSON.parse(el.textContent);
    } catch (e) {
      console.error('TMSGen: could not parse curriculum data payload', e);
      return null;
    }
  }

  function escapeHtml(value) {
    if (value === null || value === undefined) return '';
    return String(value)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;')
      .replace(/'/g, '&#39;');
  }

  // Turns "Learning outcome 1: Plan VoIP system installation" into
  // "Plan VoIP system installation" for places that want the short form.
  function shortOutcomeText(text) {
    if (!text) return '';
    var parts = String(text).split(':');
    return parts.length > 1 ? parts.slice(1).join(':').trim() : String(text).trim();
  }

  /**
   * Replaces a <select>'s options with a placeholder plus one <option>
   * per item.
   *   populateSelect(selectEl, items, {
   *     valueKey: 'id', labelFn: function(item) { return item.name; },
   *     placeholder: 'Select trade', disabled: false
   *   });
   */
  function populateSelect(selectEl, items, opts) {
    if (!selectEl) return;
    opts = opts || {};
    var valueKey = opts.valueKey || 'id';
    var labelFn = opts.labelFn || function (item) { return item.label || item.name || ''; };
    var placeholder = opts.placeholder || 'Select';

    selectEl.innerHTML = '';
    var placeholderOpt = document.createElement('option');
    placeholderOpt.value = '';
    placeholderOpt.textContent = placeholder;
    selectEl.appendChild(placeholderOpt);

    (items || []).forEach(function (item) {
      var opt = document.createElement('option');
      opt.value = item[valueKey];
      opt.textContent = labelFn(item);
      selectEl.appendChild(opt);
    });

    selectEl.disabled = !items || items.length === 0;
  }

  function todayLong() {
    var d = new Date();
    return d.toLocaleDateString(undefined, { year: 'numeric', month: 'long', day: 'numeric' });
  }

  // Today's date as "YYYY-MM-DD", suitable for pre-filling an
  // <input type="date">. Built from local date parts (not toISOString)
  // so the value matches the user's own calendar day, not UTC's.
  function todayISO() {
    var d = new Date();
    var mm = String(d.getMonth() + 1).padStart(2, '0');
    var dd = String(d.getDate()).padStart(2, '0');
    return d.getFullYear() + '-' + mm + '-' + dd;
  }

  function formatDateLong(isoString) {
    if (!isoString) return '\u2014';
    var d = new Date(isoString + 'T00:00:00');
    if (isNaN(d.getTime())) return isoString;
    return d.toLocaleDateString(undefined, { year: 'numeric', month: 'long', day: 'numeric' });
  }

  function printDocument() {
    window.print();
  }

  window.TMSGen = {
    readData: readData,
    escapeHtml: escapeHtml,
    shortOutcomeText: shortOutcomeText,
    populateSelect: populateSelect,
    todayLong: todayLong,
    todayISO: todayISO,
    formatDateLong: formatDateLong,
    print: printDocument,
  };
})();

// Make whole table rows clickable. Opt in per row with `data-row-href`.
// A click anywhere on the row navigates to that URL, EXCEPT when the click
// lands on a genuinely interactive element (link, button, form control,
// <details> summary) or anything tagged `data-no-row-link` — those keep
// their own behaviour. Ctrl/Cmd/middle-click and shift-click open a new tab
// / window like a normal link.
(function () {
  "use strict";

  var INTERACTIVE = "a, button, input, select, textarea, label, summary, [data-no-row-link]";

  function hrefFor(target) {
    var row = target.closest("tr[data-row-href]");
    if (!row) return null;
    // Don't hijack clicks on real controls inside the row.
    if (target.closest(INTERACTIVE)) return null;
    return { row: row, href: row.getAttribute("data-row-href") };
  }

  document.addEventListener("click", function (e) {
    if (e.defaultPrevented || e.button !== 0) return;
    var hit = hrefFor(e.target);
    if (!hit || !hit.href) return;
    if (e.metaKey || e.ctrlKey || e.shiftKey) {
      window.open(hit.href, "_blank", "noopener");
    } else {
      window.location.href = hit.href;
    }
  });

  // Middle-click → new tab.
  document.addEventListener("auxclick", function (e) {
    if (e.button !== 1) return;
    var hit = hrefFor(e.target);
    if (!hit || !hit.href) return;
    window.open(hit.href, "_blank", "noopener");
  });

  // Keyboard: a focused row responds to Enter.
  document.addEventListener("keydown", function (e) {
    if (e.key !== "Enter") return;
    var row = e.target.closest && e.target.closest("tr[data-row-href]");
    if (!row || e.target.closest(INTERACTIVE)) return;
    window.location.href = row.getAttribute("data-row-href");
  });
})();

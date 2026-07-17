// Mã chờ duyệt — per-row selection + single-row accept dialog (#55).
//
// Selection is two-tier: row checkboxes pick a subset; the header checkbox
// selects the visible page; when the whole page is checked a banner offers
// "select all N matching the filter", which sets a hidden select_all_matching
// flag the server reads to re-apply the filter itself. The approve button's
// label and enabled state track the current selection. The dialog is one
// element reused per row, filled from the clicked button's data-* attributes.

(function () {
  "use strict";

  var form = document.getElementById("bulk-form");
  if (!form) return; // no pending rows

  var rowChecks = Array.prototype.slice.call(
    document.querySelectorAll(".row-check"),
  );
  var selectPage = document.getElementById("select-page");
  var approveBtn = document.getElementById("bulk-approve-btn");
  var allMatchingInput = document.getElementById("select-all-matching");
  var pageBanner = document.getElementById("bulk-select-banner");
  var allBanner = document.getElementById("bulk-selected-all");
  var selectAllLink = document.getElementById("select-all-matching-link");
  var clearAllLink = document.getElementById("clear-select-all");
  var total = parseInt(form.getAttribute("data-total"), 10) || 0;

  function label(btn, key, n) {
    return (btn.getAttribute("data-label-" + key) || "").replace("{n}", n);
  }

  function selectedOnPage() {
    return rowChecks.filter(function (cb) {
      return cb.checked;
    }).length;
  }

  function allMatching() {
    return allMatchingInput.value === "1";
  }

  function render() {
    var n = selectedOnPage();
    var pageFull = rowChecks.length > 0 && n === rowChecks.length;
    if (selectPage) {
      selectPage.checked = pageFull;
      selectPage.indeterminate = n > 0 && !pageFull;
    }
    if (allMatching()) {
      approveBtn.disabled = false;
      approveBtn.textContent = label(approveBtn, "all", total);
      pageBanner.hidden = true;
      allBanner.hidden = false;
      return;
    }
    approveBtn.disabled = n === 0;
    approveBtn.textContent =
      n === 0 ? label(approveBtn, "empty", 0) : label(approveBtn, "some", n);
    // Offer "select all matching" only when the page is full AND there is more
    // beyond this page to select.
    pageBanner.hidden = !(pageFull && total > rowChecks.length);
    allBanner.hidden = true;
  }

  function clearAllMatching() {
    allMatchingInput.value = "";
  }

  rowChecks.forEach(function (cb) {
    cb.addEventListener("change", function () {
      clearAllMatching();
      render();
    });
  });

  if (selectPage) {
    selectPage.addEventListener("change", function () {
      var on = selectPage.checked;
      rowChecks.forEach(function (cb) {
        cb.checked = on;
      });
      clearAllMatching();
      render();
    });
  }

  if (selectAllLink) {
    selectAllLink.addEventListener("click", function (e) {
      e.preventDefault();
      allMatchingInput.value = "1";
      render();
    });
  }

  if (clearAllLink) {
    clearAllLink.addEventListener("click", function (e) {
      e.preventDefault();
      clearAllMatching();
      rowChecks.forEach(function (cb) {
        cb.checked = false;
      });
      render();
    });
  }

  // When select-all-matching is active, the explicit row checkboxes must not
  // also post — the server would intersect them and shrink the set. Uncheck
  // them at submit so only the flag travels.
  form.addEventListener("submit", function () {
    if (allMatching()) {
      rowChecks.forEach(function (cb) {
        cb.checked = false;
      });
    }
  });

  // ── Single-row accept dialog ──────────────────────────────────────────────
  var dialog = document.getElementById("accept-dialog");
  if (dialog) {
    var fCode = document.getElementById("ad-code");
    var fCodeInput = document.getElementById("ad-code-input");
    var fKind = document.getElementById("ad-code-kind");
    var fName = document.getElementById("ad-name");
    var fCategory = document.getElementById("ad-category");
    var fUom = document.getElementById("ad-uom");
    var fPsource = document.getElementById("ad-psource");
    var fSupplier = document.getElementById("ad-supplier");
    var cancel = document.getElementById("ad-cancel");

    function setSelect(sel, value) {
      sel.value = value;
      if (sel.value !== value) sel.selectedIndex = 0; // value absent → first
    }

    document.querySelectorAll(".js-accept-open").forEach(function (btn) {
      btn.addEventListener("click", function () {
        var code = btn.getAttribute("data-code");
        fCode.textContent = code;
        fCodeInput.value = code;
        fKind.value = btn.getAttribute("data-code-kind") || "";
        fName.value = btn.getAttribute("data-name") || "";
        setSelect(fCategory, btn.getAttribute("data-category") || "");
        fUom.value = btn.getAttribute("data-uom") || "";
        setSelect(fPsource, btn.getAttribute("data-psource") || "");
        fSupplier.value = "";
        if (typeof dialog.showModal === "function") {
          dialog.showModal();
        }
      });
    });

    if (cancel) {
      cancel.addEventListener("click", function () {
        dialog.close();
      });
    }
    // Click on the backdrop (outside the form) closes.
    dialog.addEventListener("click", function (e) {
      if (e.target === dialog) dialog.close();
    });
  }

  render();
})();

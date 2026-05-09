// Column picker — localStorage-backed show/hide for table columns.
//
// Wires up any <details class="col-picker" data-view-key="X"> against the
// nearest <table data-col-table="X"> sharing the same view-key. Cells with
// matching `data-col` attributes get hidden via a per-column CSS rule that
// targets `[data-col="<key>"]`.
//
// Persistence: localStorage key `colpicker:<view_key>` stores a JSON array
// of HIDDEN column keys (smaller than visible-set; missing key = visible).

(function () {
  const LS_PREFIX = "colpicker:";

  function loadHidden(viewKey) {
    try {
      const raw = localStorage.getItem(LS_PREFIX + viewKey);
      if (!raw) return new Set();
      const arr = JSON.parse(raw);
      return new Set(Array.isArray(arr) ? arr : []);
    } catch (e) {
      return new Set();
    }
  }

  function saveHidden(viewKey, hiddenSet) {
    try {
      localStorage.setItem(
        LS_PREFIX + viewKey,
        JSON.stringify(Array.from(hiddenSet)),
      );
    } catch (e) { /* quota / disabled — ignore */ }
  }

  function applyHidden(table, hiddenSet) {
    table.querySelectorAll("[data-col]").forEach((el) => {
      const key = el.getAttribute("data-col");
      el.style.display = hiddenSet.has(key) ? "none" : "";
    });
  }

  function syncCheckboxes(picker, hiddenSet) {
    picker.querySelectorAll("[data-col-toggle]").forEach((cb) => {
      const key = cb.getAttribute("data-col-toggle");
      cb.checked = !hiddenSet.has(key);
    });
  }

  function wirePicker(picker) {
    const viewKey = picker.getAttribute("data-view-key");
    if (!viewKey) return;
    const table = document.querySelector(`table[data-col-table="${viewKey}"]`);
    if (!table) return;

    const hidden = loadHidden(viewKey);
    syncCheckboxes(picker, hidden);
    applyHidden(table, hidden);

    picker.addEventListener("change", (e) => {
      const cb = e.target.closest("[data-col-toggle]");
      if (!cb) return;
      const key = cb.getAttribute("data-col-toggle");
      if (cb.checked) hidden.delete(key);
      else hidden.add(key);
      saveHidden(viewKey, hidden);
      applyHidden(table, hidden);
    });

    const resetBtn = picker.querySelector("[data-col-reset]");
    if (resetBtn) {
      resetBtn.addEventListener("click", () => {
        hidden.clear();
        saveHidden(viewKey, hidden);
        syncCheckboxes(picker, hidden);
        applyHidden(table, hidden);
      });
    }
  }

  function init() {
    document.querySelectorAll("details.col-picker[data-view-key]")
      .forEach(wirePicker);
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();

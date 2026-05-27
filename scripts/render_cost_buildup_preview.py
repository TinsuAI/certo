"""Render the cost-buildup UI block to a standalone HTML page for screenshot.

Bypasses CO_AUTH and Data Hub by constructing a minimal mock case and
rendering only the relevant fragment of `co_case.html` via Jinja.
"""
from __future__ import annotations

from pathlib import Path
from jinja2 import Environment, FileSystemLoader, select_autoescape

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / ".ai" / "screenshots" / "cost-buildup-ui" / "preview.html"
OUT.parent.mkdir(parents=True, exist_ok=True)


def main() -> None:
    env = Environment(
        loader=FileSystemLoader(str(ROOT / "app" / "templates")),
        autoescape=select_autoescape(["html"]),
    )
    # Render only the cost-buildup snippet as a standalone preview page.
    snippet = """
<!doctype html>
<html lang="vi">
<head>
  <meta charset="utf-8">
  <title>Cost-buildup preview</title>
  <link rel="stylesheet" href="../../../app/static/css/app.css">
  <style>
    body { padding: 24px; font: 14px -apple-system, "Segoe UI", Arial, sans-serif; background: #f3f4f6; }
    .preview-wrap { background: white; padding: 20px; max-width: 980px; margin: 0 auto; border-radius: 8px; box-shadow: 0 1px 3px rgba(0,0,0,0.1); }
    .preview-title { font-size: 16px; margin-bottom: 4px; }
    .preview-subtitle { color: #6b7280; font-size: 13px; margin-bottom: 16px; }
  </style>
</head>
<body>
  <div class="preview-wrap">
    <h2 class="preview-title">Tab Origin · Sheet TP {{ product.code }}</h2>
    <p class="preview-subtitle">Criterion: <strong>{{ product.documented_result }}</strong> · FOB: {{ product.fob }} USD · Số NPL: {{ product.materials|length }}</p>

    <div data-origin-sheet-panel data-product-fob="{{ product.fob }}" data-product-quantity="{{ product.quantity }}">
      {% set cost_buildup = product.cost_buildup or {} %}
      {% set criterion_upper = (product.origin_sheet_effective_criteria_text or product.documented_result or '')|upper %}
      {% set cost_buildup_relevant = 'LVC' in criterion_upper or 'RVC' in criterion_upper %}
      <details class="cost-buildup-block" {% if cost_buildup_relevant %}open{% endif %}>
        <summary>
          Chi phí xuất xưởng (LVC/RVC)
          <small>Nhập các khoản ngoài NPL — engine sẽ điền vào block I-VIII của bảng kê.</small>
        </summary>
        <div class="cost-buildup-grid">
          <label>
            <span>Chi phí nhân công (II)</span>
            <input type="number" step="0.01" min="0" inputmode="decimal"
                   name="product_0_cost_buildup_labor"
                   value="{{ cost_buildup.labor or '' }}"
                   data-cost-buildup-input
                   placeholder="0.00">
          </label>
          <label>
            <span>Chi phí phân bổ (III)</span>
            <input type="number" step="0.01" min="0" inputmode="decimal"
                   name="product_0_cost_buildup_overhead"
                   value="{{ cost_buildup.overhead or '' }}"
                   data-cost-buildup-input
                   placeholder="0.00">
          </label>
          <label>
            <span>Lợi nhuận (V)</span>
            <input type="number" step="0.01" min="0" inputmode="decimal"
                   name="product_0_cost_buildup_profit"
                   value="{{ cost_buildup.profit or '' }}"
                   data-cost-buildup-input
                   placeholder="0.00">
          </label>
          <label>
            <span>Chi phí khác (VII)</span>
            <input type="number" step="0.01" min="0" inputmode="decimal"
                   name="product_0_cost_buildup_other"
                   value="{{ cost_buildup.other or '' }}"
                   data-cost-buildup-input
                   placeholder="0.00">
          </label>
        </div>
        <p class="cost-buildup-hint" data-cost-buildup-hint></p>
      </details>
    </div>
  </div>
  <script>
    // Mirror of initCostBuildupHint from co_case.html — runs on this preview.
    const formatNumber = (v) => new Intl.NumberFormat("en-US", {minimumFractionDigits: 2, maximumFractionDigits: 2}).format(Number.isFinite(v) ? v : 0);
    document.querySelectorAll(".cost-buildup-block").forEach((block) => {
      const panel = block.closest("[data-origin-sheet-panel]");
      const fob = parseFloat(panel?.dataset.productFob || "0") || 0;
      const inputs = Array.from(block.querySelectorAll("[data-cost-buildup-input]"));
      const hint = block.querySelector("[data-cost-buildup-hint]");
      const recompute = () => {
        const sum = inputs.reduce((acc, input) => acc + (parseFloat(input.value || "0") || 0), 0);
        if (fob <= 0) { hint.textContent = ""; hint.removeAttribute("data-state"); return; }
        const expectedMaterial = fob - sum;
        if (sum === 0) {
          hint.textContent = "Để trống: bảng kê chỉ show I/IV/VI/VIII; II-III-V-VII sẽ trống.";
          hint.removeAttribute("data-state");
        } else if (expectedMaterial < 0) {
          hint.textContent = `Tổng chi phí ngoài NPL = ${formatNumber(sum)} > FOB ${formatNumber(fob)} — không hợp lệ.`;
          hint.dataset.state = "warning";
        } else {
          hint.textContent = `Tổng II+III+V+VII = ${formatNumber(sum)}. NPL còn lại = ${formatNumber(expectedMaterial)} / FOB ${formatNumber(fob)}.`;
          hint.dataset.state = "ok";
        }
      };
      inputs.forEach((input) => { input.addEventListener("input", recompute); input.addEventListener("blur", recompute); });
      recompute();
    });
  </script>
</body>
</html>
"""
    template = env.from_string(snippet)
    product_with_data = {
        "code": "TP-LVC-01",
        "documented_result": "LVC 30%",
        "origin_sheet_effective_criteria_text": "LVC 30%",
        "fob": "5000",
        "quantity": "10",
        "materials": [{}, {}, {}],
        "cost_buildup": {
            "labor": "350.00",
            "overhead": "880.00",
            "profit": "3680.00",
            "other": "40.00",
        },
    }
    OUT.write_text(template.render(product=product_with_data), encoding="utf-8")
    print(f"Wrote {OUT}")

    # Variant 2: empty cost_buildup (LVC) — to capture "Để trống" hint.
    out_empty = OUT.parent / "preview-empty.html"
    product_empty = dict(product_with_data, cost_buildup={})
    out_empty.write_text(template.render(product=product_empty), encoding="utf-8")
    print(f"Wrote {out_empty}")

    # Variant 3: invalid (sum > FOB) — to capture warning state.
    out_warn = OUT.parent / "preview-warning.html"
    product_warn = dict(product_with_data, cost_buildup={
        "labor": "2000", "overhead": "2000", "profit": "2000", "other": "500",
    })
    out_warn.write_text(template.render(product=product_warn), encoding="utf-8")
    print(f"Wrote {out_warn}")


if __name__ == "__main__":
    main()

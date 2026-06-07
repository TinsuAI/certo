from app.web.client_context import source_stats


def test_bom_dashboard_uses_dh_bom_block():
    summary = {
        "bom": {
            "exported_with_bom": 574,
            "exported_without_bom": 77,
            "exported_total": 651,
            "product_count": 3605,
            "stale_count": 10,
            "last_published_at": "2026-05-25T12:34:52+08:00",
        }
    }
    stats = source_stats("bom", counts={}, summary=summary)
    values = [c["value"] for c in stats["cards"]]
    labels = [c["label"] for c in stats["cards"]]
    # headline is the export trio, not product_count
    assert "574/651" in values
    assert any("chưa có BOM" in label for label in labels)
    assert "3.605" in values  # product_count kept only as a secondary detail
    assert stats["cards"][0]["tone"] == "primary"
    assert "cập nhật 2026-05-25" in stats["note"]
    assert "10 mã BOM cũ" in stats["note"]


def test_bom_dashboard_gap_card_is_warn_only_when_nonzero():
    summary = {"bom": {"exported_with_bom": 63, "exported_without_bom": 0, "exported_total": 63, "product_count": 63}}
    stats = source_stats("bom", counts={}, summary=summary)
    gap = next(c for c in stats["cards"] if "chưa có BOM" in c["label"])
    assert gap["value"] == "0"
    assert gap["tone"] is None


def test_bom_dashboard_fallback_without_bom_block_is_qualitative():
    # Older Data Hub (no bom block) and no file-mode counts → qualitative card,
    # never a fabricated/50-capped number.
    stats = source_stats("bom", counts={}, summary={})
    assert len(stats["cards"]) == 1
    assert stats["cards"][0]["value"] == "—"


def test_bom_dashboard_file_mode_uses_local_counts():
    stats = source_stats("bom", counts={}, bom_products=12, bom_lines=340)
    values = [c["value"] for c in stats["cards"]]
    assert "12" in values and "340" in values

"""TKN merged-PDF size-bounded split (mục 5) — adapter + export embed.

DH returns application/zip of `…-part-NNN.pdf` when the rendered import PDF would
exceed the per-client cap (default 2 MB), so each part fits the old Ecosys upload
limit. CO holds the cap as a CO-side per-client override (`client.export_overrides
.tkn_pdf_max_part_mb`, editable even in DH source-mode) and passes it (× 1e6) as
`max_part_bytes`.
"""
import io
import zipfile

import pytest

from app.data_hub_client import DataHubClient


# ---------- adapter: download_declarations_pdf ----------

def _fake_resp(content: bytes, headers: dict):
    class FakeResp:
        def __init__(self):
            self.content = content
            self.headers = headers

        def raise_for_status(self):
            return None

    return FakeResp()


def test_adapter_passes_quality_and_max_part_bytes(monkeypatch):
    client = DataHubClient(base_url="http://test", token="t")
    captured = {}

    def fake_get(path, params=None, headers=None, timeout=None):
        captured["params"] = params
        return _fake_resp(b"%PDF-1", {"Content-Type": "application/pdf", "X-Pdf-Parts": "1"})

    monkeypatch.setattr(client._client, "get", fake_get)
    client.download_declarations_pdf(
        "c", direction="import", declaration_nos=["a"], max_part_bytes=2_000_000,
    )
    assert captured["params"]["quality"] == "print"
    assert captured["params"]["max_part_bytes"] == "2000000"
    client.close()


def test_adapter_single_pdf_sets_content_and_one_part(monkeypatch):
    client = DataHubClient(base_url="http://test", token="t")
    monkeypatch.setattr(client._client, "get", lambda *a, **k: _fake_resp(
        b"%PDF-single", {"Content-Type": "application/pdf", "X-Pdf-Parts": "1", "X-Pdf-Bytes": "11"}))
    res = client.download_declarations_pdf("c", direction="import", declaration_nos=["a"], filename="tkn.pdf")
    assert res["content"] == b"%PDF-single"
    assert [p["name"] for p in res["parts"]] == ["tkn.pdf"]
    assert res["parts"][0]["content"] == b"%PDF-single"
    assert res["parts_count"] == 1
    client.close()


def test_adapter_zip_split_returns_parts_and_oversize(monkeypatch):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("declarations_johnson-vn_import-part-001.pdf", b"%PDF-a")
        zf.writestr("declarations_johnson-vn_import-part-002.pdf", b"%PDF-b")
    zip_bytes = buf.getvalue()
    client = DataHubClient(base_url="http://test", token="t")
    monkeypatch.setattr(client._client, "get", lambda *a, **k: _fake_resp(zip_bytes, {
        "Content-Type": "application/zip",
        "X-Pdf-Parts": "2",
        "X-Pdf-Bytes": "12",
        "X-Pdf-Oversize-Nos": "107114306461, 107144890310",
    }))
    res = client.download_declarations_pdf(
        "c", direction="import", declaration_nos=["a", "b"], max_part_bytes=50_000)
    assert res["content"] is None
    assert len(res["parts"]) == 2
    assert all(p["content"][:4] == b"%PDF" for p in res["parts"])
    assert res["parts_count"] == 2
    assert res["oversize_nos"] == ["107114306461", "107144890310"]
    client.close()


def test_adapter_rejects_bad_quality():
    client = DataHubClient(base_url="http://test", token="t")
    with pytest.raises(ValueError, match="quality"):
        client.download_declarations_pdf("c", direction="import", declaration_nos=["a"], quality="lossless")
    client.close()


# ---------- export embed: _try_fetch_declaration_pdfs ----------

class _FakeHubParts:
    """Returns a 2-part split for import, info-only (included=0) otherwise."""

    def __init__(self):
        self.calls = []

    def download_declarations_pdf(self, client_id, *, direction, declaration_nos, filename="", max_part_bytes=None, **_):
        self.calls.append({"direction": direction, "max_part_bytes": max_part_bytes})
        if direction != "import":
            return {"included": 0, "parts": []}
        return {
            "content": None,
            "included": 2,
            "parts": [
                {"name": "x-part-001.pdf", "content": b"%PDF-1"},
                {"name": "x-part-002.pdf", "content": b"%PDF-2"},
            ],
            "oversize_nos": [],
        }


def test_export_embeds_split_parts_and_passes_client_cap(monkeypatch):
    from app.routers import co_case

    hub = _FakeHubParts()
    monkeypatch.setattr(co_case.portfolio_service, "data_hub", hub, raising=False)

    client = {"id": "johnson-vn", "export_overrides": {"tkn_pdf_max_part_mb": 1.5}}
    case = {"case_code": "CO123"}
    summary = {"tkn": [{"declaration_no": "111"}, {"declaration_no": "222"}], "tkx": []}
    pdfs, failures = co_case._try_fetch_declaration_pdfs(client, case, summary)

    assert sorted(pdfs) == ["CO123-to-khai-nhap-part-001.pdf", "CO123-to-khai-nhap-part-002.pdf"]
    assert pdfs["CO123-to-khai-nhap-part-001.pdf"] == b"%PDF-1"
    assert failures == []
    # the 1.5 MB cap reached DH as 1_500_000 bytes
    import_call = next(c for c in hub.calls if c["direction"] == "import")
    assert import_call["max_part_bytes"] == 1_500_000


def test_export_single_pdf_uses_unsuffixed_slot_and_default_cap(monkeypatch):
    from app.routers import co_case

    calls = []

    class FakeHub:
        def download_declarations_pdf(self, client_id, *, direction, declaration_nos, filename="", max_part_bytes=None, **_):
            calls.append(max_part_bytes)
            if direction != "import":
                return {"included": 0, "parts": []}
            return {"content": b"%PDF-merged", "included": 2,
                    "parts": [{"name": filename, "content": b"%PDF-merged"}], "oversize_nos": []}

    monkeypatch.setattr(co_case.portfolio_service, "data_hub", FakeHub(), raising=False)

    client = {"id": "johnson-vn"}  # no override → default 2 MB
    case = {"case_code": "CO123"}
    summary = {"tkn": [{"declaration_no": "111"}], "tkx": []}
    pdfs, failures = co_case._try_fetch_declaration_pdfs(client, case, summary)
    assert list(pdfs) == ["CO123-to-khai-nhap.pdf"]
    assert pdfs["CO123-to-khai-nhap.pdf"] == b"%PDF-merged"
    assert 2_000_000 in calls  # default cap passed


def test_dossier_zip_embeds_multiple_tkn_parts_under_to_khai():
    """The split parts land as separate files under 03-to-khai/ in the dossier."""
    from app.workbook_io import create_dossier_zip

    case = {"case_code": "CO9", "products": []}
    pdfs = {
        "CO9-to-khai-nhap-part-001.pdf": b"%PDF-1",
        "CO9-to-khai-nhap-part-002.pdf": b"%PDF-2",
    }
    blob = create_dossier_zip(case, [], {}, declaration_pdfs=pdfs)
    with zipfile.ZipFile(io.BytesIO(blob)) as zf:
        tkn = sorted(n for n in zf.namelist() if n.endswith(".pdf") and "to-khai" in n)
    assert tkn == ["03-to-khai/CO9-to-khai-nhap-part-001.pdf", "03-to-khai/CO9-to-khai-nhap-part-002.pdf"]


# ---------- config route: persists cap to the CO-side client overlay ----------

def test_config_route_persists_cap_to_client_overlay(monkeypatch):
    """The cap is a CO-side override on the client (like min_days), upserted
    BEFORE the source-write guard → editable even when DH source-mode is on."""
    import asyncio

    from app.routers import pages

    captured = {}

    class FakeStore:
        def upsert_client(self, client):
            captured["client"] = client

    monkeypatch.setattr(pages, "resolve_client", lambda cid: {"id": cid})
    monkeypatch.setattr(pages, "get_app_state_store", lambda: FakeStore())
    monkeypatch.setattr(pages, "require_local_source_writes", lambda: None)
    monkeypatch.setattr(pages.portfolio_service, "get_client_config",
                        lambda c: {"co_stock": {}, "allocation_code": {}})
    monkeypatch.setattr(pages.portfolio_service, "save_client_config", lambda c, cfg: cfg)
    monkeypatch.setattr(pages.portfolio_service, "refresh_client_indexes", lambda c: None)
    monkeypatch.setattr(pages, "config_context", lambda cid, **kw: {})
    monkeypatch.setattr(pages.templates, "TemplateResponse", lambda **kw: "OK")

    class FakeReq:
        async def form(self):
            return {"co_stock_lot_policy": "line_level", "tkn_pdf_max_part_mb": "3"}

    asyncio.run(pages.save_client_config_route(FakeReq(), "growatt-vn"))
    assert captured["client"]["export_overrides"]["tkn_pdf_max_part_mb"] == 3

"""Dossier ZIP — pre-staged Bearer-download consumer.

CO calls `DataHubClient.download_declarations_zip` to fetch TKX/TKN blobs
and embed them under `03-to-khai/TKX|TKN/…` when Data Hub ships the
Bearer-aware endpoint (filed at
`.ai/api-requests/2026-05-28-bcct-declarations-download-bearer.md`).

Until that ships, the call raises (404 / network) and the dossier
gracefully falls back to manifest-only mode. These tests exercise both
paths via a fake Data Hub adapter.
"""
from __future__ import annotations

import io
import zipfile

from app.workbook_io import build_dossier_readme, create_dossier_zip


def _case():
    return {
        "case_code": "CO-TEST",
        "client_id": "growatt-vn",
        "customer": "Demo",
        "customer_legal_name": "CÔNG TY DEMO",
        "customer_tax_code": "0123",
        "destination_market": "Canada",
        "products": [{"code": "P1"}],
    }


def _summary():
    return {
        "tkx": [{"declaration_no": "EXP-1", "file_count": 2}],
        "tkn": [{"declaration_no": "IMP-1", "file_count": 1}],
        "missing_tkx": [],
        "missing_tkn": [],
    }


def test_dossier_zip_falls_back_to_manifest_when_no_pdfs():
    """When the merged-PDF fetch yields nothing (DH down / no declarations),
    MANIFEST.md exists, no merged PDFs embedded, README says they're pending."""
    blob = create_dossier_zip(_case(), [], _summary())
    archive = zipfile.ZipFile(io.BytesIO(blob))
    names = archive.namelist()
    assert "03-to-khai/MANIFEST.md" in names
    assert not any("ghep.pdf" in n for n in names)
    manifest = archive.read("03-to-khai/MANIFEST.md").decode("utf-8")
    assert "chưa được nhúng" in manifest
    readme = archive.read("00-README.md").decode("utf-8")
    assert "Tờ khai ghép chưa nhúng được" in readme


def test_readme_states_embedded_status_correctly():
    readme_not_embedded = build_dossier_readme(_case(), _summary())
    readme_embedded = build_dossier_readme(
        _case(), _summary(),
        embedded_pdf_names=["CO-TEST-to-khai-xuat.pdf", "CO-TEST-to-khai-nhap.pdf"],
    )
    assert "chưa nhúng được" in readme_not_embedded
    assert "đã nhúng sẵn" in readme_embedded
    assert "CO-TEST-to-khai-nhap.pdf" in readme_embedded


def test_readme_warns_on_embed_failure():
    """A direction that had declarations to embed but failed (e.g. a render
    timeout) is surfaced loudly rather than silently dropped."""
    readme = build_dossier_readme(
        _case(), _summary(),
        embedded_pdf_names=["CO-TEST-to-khai-xuat.pdf"],
        embed_failures=[{"label": "TKN", "filename": "CO-TEST-to-khai-nhap.pdf", "declaration_count": 194}],
    )
    assert "Chưa nhúng được" in readme
    assert "TKN" in readme and "194" in readme


def test_dossier_zip_embeds_merged_declaration_pdfs():
    """Once DH ships the merged-PDF endpoint, the CO endpoint pre-fetches the
    TKX/TKN merged PDFs and passes them via declaration_pdfs, keyed by the
    archive filename. The dossier ZIP embeds them at 03-to-khai/<name>.
    Contract: .ai/api-requests/2026-06-05-declarations-merged-pdf.md."""
    pdfs = {
        "CO-TEST-to-khai-xuat.pdf": b"%PDF-fake-tkx",
        "CO-TEST-to-khai-nhap.pdf": b"%PDF-fake-tkn",
    }
    blob = create_dossier_zip(_case(), [], _summary(), declaration_pdfs=pdfs)
    archive = zipfile.ZipFile(io.BytesIO(blob))
    names = archive.namelist()
    assert "03-to-khai/CO-TEST-to-khai-xuat.pdf" in names
    assert "03-to-khai/CO-TEST-to-khai-nhap.pdf" in names
    assert archive.read("03-to-khai/CO-TEST-to-khai-nhap.pdf") == b"%PDF-fake-tkn"


def test_download_declarations_pdf_builds_request_and_parses_headers(monkeypatch):
    from app.data_hub_client import DataHubClient

    client = DataHubClient(base_url="http://test", token="t")
    captured: dict = {}

    class FakeResp:
        status_code = 200
        content = b"%PDF-merged"
        headers = {
            "X-Declarations-Requested": "3",
            "X-Declarations-Included": "2",
            "X-Declarations-Missing": "1",
            "X-Declarations-Missing-Nos": "999, 888",
        }

        def raise_for_status(self):
            return None

    def fake_get(path, params=None, headers=None, timeout=None):
        captured["path"] = path
        captured["params"] = params
        captured["timeout"] = timeout
        return FakeResp()

    monkeypatch.setattr(client._client, "get", fake_get)
    res = client.download_declarations_pdf(
        "johnson-vn", direction="import", declaration_nos=["a", "b", "c"],
        sort="registration_date",
    )
    assert captured["path"].endswith("/declarations/download.pdf")
    assert captured["params"]["direction"] == "import"
    assert captured["params"]["declaration_nos"] == "a,b,c"
    assert captured["params"]["sort"] == "registration_date"
    assert res["content"] == b"%PDF-merged"
    assert res["requested"] == 3
    assert res["included"] == 2
    assert res["missing"] == 1
    assert res["missing_nos"] == ["999", "888"]
    # Heavy render gets the extended timeout, not the default ~20s.
    from app.data_hub_client import MERGED_DECLARATIONS_PDF_TIMEOUT_SECONDS
    assert captured["timeout"] == MERGED_DECLARATIONS_PDF_TIMEOUT_SECONDS
    client.close()


def test_download_declarations_pdf_validates_inputs():
    from app.data_hub_client import DataHubClient

    client = DataHubClient(base_url="http://test", token="t")
    for bad in (
        {"direction": "wrong", "declaration_nos": ["x"]},
        {"direction": "import", "declaration_nos": []},
        {"direction": "import", "declaration_nos": ["x"], "sort": "nope"},
    ):
        try:
            client.download_declarations_pdf("c", **bad)
        except ValueError:
            pass
        else:
            raise AssertionError(f"expected validation for {bad}")
    client.close()


def test_data_hub_client_download_declarations_validates_inputs():
    """Adapter rejects obviously bad params before hitting the network."""
    from app.data_hub_client import DataHubClient

    # No actual HTTP — just construct + check argument validation.
    client = DataHubClient(base_url="http://test", token="t")
    try:
        client.download_declarations_zip("c", direction="wrong", declaration_nos=["x"])
    except ValueError as exc:
        assert "direction" in str(exc)
    else:
        raise AssertionError("expected direction validation")

    try:
        client.download_declarations_zip("c", direction="export", declaration_nos=[])
    except ValueError as exc:
        assert "declaration_nos" in str(exc)
    else:
        raise AssertionError("expected declaration_nos validation")
    client.close()

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


def test_dossier_zip_falls_back_to_manifest_when_no_archives():
    """When Data Hub hasn't shipped the Bearer download yet,
    declaration_archives is empty → MANIFEST.md exists, no TKX/TKN
    blobs embedded, README says blobs are pending."""
    blob = create_dossier_zip(_case(), [], _summary())
    archive = zipfile.ZipFile(io.BytesIO(blob))
    names = archive.namelist()
    assert "03-to-khai/MANIFEST.md" in names
    assert not any(n.startswith("03-to-khai/TKX/") for n in names)
    assert not any(n.startswith("03-to-khai/TKN/") for n in names)
    manifest = archive.read("03-to-khai/MANIFEST.md").decode("utf-8")
    assert "chưa được nhúng" in manifest
    readme = archive.read("00-README.md").decode("utf-8")
    assert "sẽ tự nhúng khi Data Hub bật" in readme


def test_dossier_zip_embeds_declaration_archives_when_provided():
    """Once DH ships the Bearer endpoint, the CO endpoint pre-fetches the
    bytes and passes them in via declaration_archives. The dossier ZIP
    embeds them under 03-to-khai/<direction>/<filename>."""
    archives = {
        "TKX/TKX_CO-TEST.zip": b"PKfake-tkx-bytes",
        "TKN/TKN_CO-TEST.zip": b"PKfake-tkn-bytes",
    }
    blob = create_dossier_zip(_case(), [], _summary(), declaration_archives=archives)
    archive = zipfile.ZipFile(io.BytesIO(blob))
    names = archive.namelist()
    assert "03-to-khai/TKX/TKX_CO-TEST.zip" in names
    assert "03-to-khai/TKN/TKN_CO-TEST.zip" in names
    assert archive.read("03-to-khai/TKX/TKX_CO-TEST.zip") == b"PKfake-tkx-bytes"
    manifest = archive.read("03-to-khai/MANIFEST.md").decode("utf-8")
    assert "đã được nhúng" in manifest
    readme = archive.read("00-README.md").decode("utf-8")
    assert "đã nhúng sẵn" in readme


def test_readme_states_embedded_status_correctly():
    readme_not_embedded = build_dossier_readme(_case(), _summary())
    readme_embedded = build_dossier_readme(_case(), _summary(), embedded_declaration_archives=True)
    assert "sẽ tự nhúng" in readme_not_embedded
    assert "đã nhúng sẵn" in readme_embedded


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

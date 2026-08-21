"""Parser tests for Materials, Code Mappings, BCCT, BOM."""
import io

import pytest
from openpyxl import Workbook

from app.parsers.bcct import parse_bcct_workbook, BcctParseError
from app.parsers.bom import parse_bom_workbook, BomParseError
from app.parsers.code_mappings import parse_code_mappings_workbook, CodeMappingsParseError
from app.parsers.materials import parse_materials_workbook, MaterialsParseError, normalize_category


def _xlsx(rows: list[tuple], sheet_title: str = "Sheet1", *,
          extra_sheets: list[tuple[str, list[tuple]]] | None = None) -> bytes:
    wb = Workbook()
    ws = wb.active
    ws.title = sheet_title
    for r in rows:
        ws.append(r)
    for title, srows in (extra_sheets or []):
        s = wb.create_sheet(title)
        for r in srows:
            s.append(r)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


# ---- Materials ----

def test_materials_parses_basic_sheet():
    blob = _xlsx([
        ("Mã HQ", "Mã NB", "Tên", "Loại", "ĐVT", "HS"),
        ("PE-001", "PE-001", "Polyethylene", "nvl", "kg", "39011010"),
        ("INV-3000", "INV-3000", "Solar inverter", "tp", "pcs", "85044090"),
    ])
    rows, _ = parse_materials_workbook(blob)
    assert len(rows) == 2
    assert rows[0]["customs_code"] == "PE-001"
    assert rows[0]["category"] == "nvl"
    assert rows[1]["category"] == "tp"


def test_materials_uses_sheet_default_when_category_missing():
    blob = _xlsx(
        [
            ("Mã HQ", "Tên", "ĐVT"),
            ("AL-100", "Aluminum", "kg"),
        ],
        sheet_title="DM NVL",
    )
    rows, _ = parse_materials_workbook(blob)
    assert rows[0]["category"] == "nvl"


def test_materials_skips_blank_customs_code():
    blob = _xlsx([
        ("Mã HQ", "Tên", "Loại"),
        ("", "Empty row", "nvl"),
        ("OK-1", "Real row", "nvl"),
    ])
    rows, skipped = parse_materials_workbook(blob)
    assert len(rows) == 1
    assert rows[0]["customs_code"] == "OK-1"
    assert len(skipped) == 1
    assert skipped[0]["reason"] == "missing_required:identifier"


def test_materials_raises_when_no_recognizable_headers():
    blob = _xlsx([("Random", "Junk", "Headers"), ("a", "b", "c")])
    with pytest.raises(MaterialsParseError):
        parse_materials_workbook(blob)


def test_normalize_category_handles_aliases():
    assert normalize_category("Nguyên Vật Liệu") == "nvl"
    assert normalize_category("Thành phẩm") == "tp"
    assert normalize_category("BTP_SX") == "btp_sx"
    assert normalize_category("Tool") == "ccdc"
    assert normalize_category(None) is None


# ---- Code mappings ----

def test_code_mappings_n_n_via_repeated_rows():
    blob = _xlsx([
        ("Mã nội bộ", "Mã hải quan"),
        ("PE-001", "PE-001"),
        ("PE-001", "PE-ALT"),  # 1:n
        ("PE-002", "PE-002"),
    ])
    rows, _ = parse_code_mappings_workbook(blob)
    assert len(rows) == 3
    pairs = {(r["internal_code"], r["customs_code"]) for r in rows}
    assert ("PE-001", "PE-001") in pairs
    assert ("PE-001", "PE-ALT") in pairs


def test_code_mappings_two_columns_minimum_works():
    """BQD often has only 2 columns; parser must not require 3+ headers."""
    blob = _xlsx([
        ("Mã nội bộ", "Mã hải quan"),
        ("X", "Y"),
    ])
    rows, _ = parse_code_mappings_workbook(blob)
    assert rows == [{
        "internal_code": "X", "customs_code": "Y", "category": None, "notes": None,
    }]


def test_code_mappings_raises_when_columns_missing():
    blob = _xlsx([("Random", "Headers"), ("x", "y")])
    with pytest.raises(CodeMappingsParseError):
        parse_code_mappings_workbook(blob)


# ---- BCCT ----

def test_bcct_extracts_typed_columns_and_direction():
    blob = _xlsx([
        ("Số tờ khai", "Dòng", "Mã loại hình", "Ngày đăng ký", "Mã NPL/SP",
         "Tên hàng", "Tổng số lượng", "ĐVT", "Trị giá", "Nguyên tệ"),
        ("104111", 1, "E11", "2025-03-15", "PE-001",
         "PE-001#&Polyethylene", 100.0, "kg", 250.0, "USD"),
        ("104112", 1, "E42", "2025-09-01", "INV-3000",
         "INV-3000#&Solar inverter", 50.0, "pcs", 12500.0, "USD"),
    ])
    rows = parse_bcct_workbook(blob)
    assert len(rows) == 2
    assert rows[0]["customs_code"] == "PE-001"
    assert rows[0]["direction"] == "import"
    assert rows[1]["direction"] == "export"
    assert rows[0]["quantity"] == 100.0
    assert rows[0]["currency_nt"] == "USD"


def test_bcct_raises_on_unknown_format():
    blob = _xlsx([("Some", "Random"), ("a", "b")])
    with pytest.raises(BcctParseError):
        parse_bcct_workbook(blob)


def test_bcct_strips_trailing_zero_from_numeric_cells():
    """Excel stores numeric cells as float. The parser must coerce
    integer-valued floats back to int before stringifying so
    declaration_no '308449399330.0' does not leak into the DB.

    Regression for /v1/hub/bcct/invoice-matches contract — CO consumes
    declaration_no / line_no / transaction_key as opaque strings and
    rejects values that do not match the customs system's printed form.
    """
    blob = _xlsx([
        ("Số tờ khai", "Dòng", "Mã loại hình", "Ngày đăng ký", "Mã NPL/SP",
         "Tên hàng", "Tổng số lượng", "ĐVT", "Trị giá", "Nguyên tệ"),
        # Numeric values written as int — openpyxl returns them as float.
        (308449399330, 133, "E42", "2026-04-18", "SD00.0010600",
         "SD00.0010600#&pin", 368.0, "CT", 12000.0, "USD"),
    ])
    rows = parse_bcct_workbook(blob)
    assert len(rows) == 1
    assert rows[0]["declaration_no"] == "308449399330"
    assert rows[0]["line_no"] == "133"
    assert rows[0]["transaction_key"] == "308449399330-133"


def test_bcct_preserves_real_decimal_when_present():
    """Decimal values like 1.5 must survive — only integer-valued floats
    get coerced back to int in the parser."""
    from app.parsers.bcct import _cell_str
    assert _cell_str([1.5], 0) == "1.5"
    assert _cell_str([1.0], 0) == "1"
    assert _cell_str([308449399330.0], 0) == "308449399330"
    assert _cell_str(["133"], 0) == "133"
    assert _cell_str([None], 0) is None
    assert _cell_str([""], 0) is None


def test_bcct_c12_classified_as_export():
    """Decision 1357/QĐ-TCHQ 2021: C12 = export from bonded warehouse,
    not import. Pre-fix parser had C12 in IMPORT_TYPES — sign-flip bug
    that would have flagged any C12 row as import direction."""
    from app.parsers.bcct import _direction_from
    assert _direction_from("C12", None) == "export"
    assert _direction_from("C11", None) == "import"


def test_bcct_invalid_h_codes_dropped():
    """H12/H13/H22/H23 don't exist in the 2021 schedule — only H11 (import)
    and H21 (export) are valid. Bogus codes should fall through to NULL,
    not silently land in either bucket."""
    from app.parsers.bcct import _direction_from
    assert _direction_from("H11", None) == "import"
    assert _direction_from("H21", None) == "export"
    assert _direction_from("H12", None) is None
    assert _direction_from("H13", None) is None
    assert _direction_from("H22", None) is None
    assert _direction_from("H23", None) is None


def test_bcct_cell_date_raises_on_unrecognized_format():
    """Silent None on bad date used to leak through parse and fail later
    at the GENERATED `year` column with an opaque message. Loud-fail
    at parse time instead."""
    from app.parsers.bcct import _cell_date, BcctParseError
    import pytest
    assert _cell_date(["2026-04-18"], 0) is not None  # ISO ok
    assert _cell_date(["18/04/2026"], 0) is not None  # DD/MM/YYYY ok
    assert _cell_date(["18.04.2026"], 0) is not None  # Thái Sơn ok
    assert _cell_date(["2026/04/18"], 0) is not None  # ECUS5 ok
    assert _cell_date([None], 0) is None              # missing ok
    assert _cell_date([""], 0) is None                # blank ok
    with pytest.raises(BcctParseError, match="unrecognized date"):
        _cell_date(["April 18, 2026"], 0)
    with pytest.raises(BcctParseError, match="unrecognized date"):
        _cell_date(["20260418"], 0)


def test_materials_status_map_chờ_duyệt_is_pending():
    """`chờ duyệt` (waiting for HQ approval) is semantically pending,
    not discontinued. Migration 026 extended chk_status to allow
    'pending' alongside 'active' / 'discontinued'."""
    from app.parsers.materials import normalize_status
    assert normalize_status("chờ duyệt") == "pending"
    assert normalize_status("cho duyet") == "pending"
    assert normalize_status("chờ phê duyệt") == "pending"
    assert normalize_status("pending") == "pending"
    # Keep 'discontinued' semantics for inactive/ngừng
    assert normalize_status("ngừng") == "discontinued"
    assert normalize_status("inactive") == "discontinued"
    # Unknown / empty default to active (existing behaviour)
    assert normalize_status("active") == "active"
    assert normalize_status("") == "active"
    assert normalize_status(None) == "active"


def test_direction_strict_set_rejects_partial_match():
    """Old `startswith('nh')` would classify 'Nhà cung cấp' (supplier)
    as import. Strict token-set match avoids that whole class of error."""
    from app.parsers.bcct import _direction_from
    assert _direction_from(None, "Nhập khẩu") == "import"
    assert _direction_from(None, "Xuất") == "export"
    assert _direction_from(None, "import") == "import"
    assert _direction_from(None, "I") == "import"
    # Old parser would have classified these as import via startswith — now NULL.
    assert _direction_from(None, "Nhà cung cấp") is None
    assert _direction_from(None, "Nhập-Xuất tại chỗ") is None
    assert _direction_from(None, "Xuong san xuat") is None
    # Falls back to declaration_type when explicit ambiguous.
    assert _direction_from("E11", "Nhà cung cấp") == "import"


def test_llm_mapping_path_runs_full_coercion_guards():
    """Sprint B audit: when the LLM-confirmed mapping bypasses the rigid
    alias path, ALL Sprint A coercion guards (qty>0, date raise,
    .0 strip) must still apply. Otherwise the smart-parse flow becomes
    a back door for the bugs Sprint A locks down on the rigid flow.
    """
    import io
    import pytest
    from openpyxl import Workbook
    from app.parsers.bcct import BcctParseError, parse_bcct_workbook

    def _xlsx(rows):
        buf = io.BytesIO()
        wb = Workbook()
        ws = wb.active
        for r in rows:
            ws.append(list(r))
        wb.save(buf)
        return buf.getvalue()

    # Excel with non-standard headers; LLM proposes a mapping.
    blob = _xlsx([
        ("Decl#", "LineIdx", "TypeCode", "RegDate", "MatCode", "GoodsDesc"),
        (308449399330, 133, "E42", "March 23, 2026",  # bad date format
         "SD00.001", "Pin"),
    ])
    mapping = {
        "Decl#": "declaration_no",
        "LineIdx": "line_no",
        "TypeCode": "declaration_type",
        "RegDate": "registration_date",
        "MatCode": "customs_code",
        "GoodsDesc": "goods_name",
    }
    # H1 guard: bad date format raises through LLM path too.
    with pytest.raises(BcctParseError, match="unrecognized date"):
        parse_bcct_workbook(blob, mapping_override=mapping)

    # .0-strip guard: int-formatted Excel cells get coerced via shared
    # cell_str on the LLM path too.
    blob_ok = _xlsx([
        ("Decl#", "LineIdx", "TypeCode", "RegDate", "MatCode", "GoodsDesc"),
        (308449399330, 133, "E42", "2026-04-18", "SD00.001", "Pin"),
    ])
    rows = parse_bcct_workbook(blob_ok, mapping_override=mapping)
    assert len(rows) == 1
    assert rows[0]["declaration_no"] == "308449399330"
    assert rows[0]["line_no"] == "133"
    assert rows[0]["transaction_key"] == "308449399330-133"


def test_bom_create_artifact_rejects_qty_zero():
    """Belt-and-suspenders: even though the DB CHECK catches qty<=0,
    the store layer pre-validates so users get a row-pointed error
    instead of a generic Postgres constraint violation."""
    import pytest
    import secrets
    from app.database import connect
    from app.parsers.bom_adapters import BomParseError
    from app.stores.bom import create_artifact

    cid = "qty-test-" + secrets.token_hex(4)
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            """insert into hub.clients
               (client_id, name, code_resolution_mode, bom_proposal_mode)
               values (%s, 'Qty Test', 'identity', 'auto')""",
            (cid,),
        )
        cur.execute(
            """insert into hub.materials
               (client_id, material_code, name, category, status)
               values (%s, 'M-A', 'A', 'nvl', 'active'),
                      (%s, 'M-B', 'B', 'nvl', 'active')""",
            (cid, cid),
        )
    try:
        with pytest.raises(BomParseError, match="qty_per_unit"):
            create_artifact(
                client_id=cid, product_code="P-1",
                rows=[
                    {"material_code": "M-A", "qty_per_unit": 1.0, "uom": "kg"},
                    {"material_code": "M-B", "qty_per_unit": 0, "uom": "kg"},
                ],
                actor="agency_staff", intent="asserted_technical",
                parent_artifact_id=None, context={}, source_upload_id=None,
            )
        with pytest.raises(BomParseError, match="qty_per_unit"):
            create_artifact(
                client_id=cid, product_code="P-1",
                rows=[
                    {"material_code": "M-A", "qty_per_unit": None, "uom": "kg"},
                ],
                actor="agency_staff", intent="asserted_technical",
                parent_artifact_id=None, context={}, source_upload_id=None,
            )
    finally:
        with connect() as conn, conn.cursor() as cur:
            cur.execute(
                "delete from hub.bom_artifact_rows where artifact_id in "
                "(select artifact_id from hub.bom_artifacts where client_id=%s)",
                (cid,),
            )
            cur.execute("delete from hub.bom_audit_events where client_id=%s", (cid,))
            cur.execute("delete from hub.bom_artifacts where client_id=%s", (cid,))
            cur.execute("delete from hub.materials where client_id=%s", (cid,))
            cur.execute("delete from hub.clients where client_id=%s", (cid,))


def test_shared_cell_str_used_everywhere():
    """All four parser modules share the same cell_str helper from
    `app/parsers/_excel.py`, so the .0 fix can't drift out of sync.

    Regression for the 4-copy duplication that allowed the bug to
    persist in materials.py / code_mappings.py / bom_adapters/_common.py
    even after bcct.py was patched."""
    from app.parsers._excel import cell_str as shared
    from app.parsers.bcct import _cell_str as bcct_cs
    from app.parsers.materials import _cell_str as materials_cs
    from app.parsers.code_mappings import _cell_str as code_mappings_cs
    from app.parsers.bom_adapters._common import cell_str as bom_cs
    # All four should be the SAME function object.
    assert bcct_cs is shared
    assert materials_cs is shared
    assert code_mappings_cs is shared
    assert bom_cs is shared


# ---- BOM ----

def test_bom_manual_flat_groups_by_product():
    blob = _xlsx([
        ("Mã SP", "Mã NVL", "Định mức", "ĐVT"),
        ("INV-3000", "PE-001", 0.45, "kg"),
        ("INV-3000", "AL-100", 0.30, "kg"),
        ("INV-5000", "PE-001", 0.60, "kg"),
    ])
    products = parse_bom_workbook(blob, profile="manual_flat")
    assert set(products.keys()) == {"INV-3000", "INV-5000"}
    assert len(products["INV-3000"]) == 2
    assert len(products["INV-5000"]) == 1


def test_bom_growatt_multi_workbook_sheet_per_product():
    blob = _xlsx(
        rows=[("Mã NVL", "Định mức", "ĐVT")],  # placeholder for default sheet
        extra_sheets=[
            ("INV-3000", [
                ("Mã NVL", "Định mức", "ĐVT"),
                ("PE-001", 0.45, "kg"),
                ("AL-100", 0.30, "kg"),
            ]),
            ("INV-5000", [
                ("Mã NVL", "Định mức", "ĐVT"),
                ("CU-WIRE", 1.20, "m"),
            ]),
        ],
    )
    products = parse_bom_workbook(blob, profile="growatt_multi_workbook")
    assert "INV-3000" in products
    assert "INV-5000" in products
    assert len(products["INV-3000"]) == 2


def test_bom_unknown_profile_raises():
    with pytest.raises(BomParseError):
        parse_bom_workbook(b"", profile="nope")

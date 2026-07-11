"""Pure-function seam for the column-9 vocabulary (VN-origin ticket #9):
raw BCCT string → ISO → Vietnamese display name, the unknown bucket, and
column9_text — proven independent of anything but its inputs.
"""
from __future__ import annotations

from app.origin_country import (
    COLUMN9_MODE_COUNTRY,
    COLUMN9_MODE_QUALIFICATION,
    column9_text,
    country_label_vi,
    is_unknown_origin,
    is_vietnam_origin,
    iso_for_raw,
    normalize_column9_mode,
)


def test_observed_bcct_vocabulary_maps_to_iso():
    for raw, iso in [
        ("VIETNAM", "VN"), ("CHINA", "CN"), ("U.S.A.", "US"), ("TAIWAN", "TW"),
        ("GERMANY", "DE"), ("JAPAN", "JP"), ("SWITZLD", "CH"), ("HG.KONG", "HK"),
        ("THAILND", "TH"), ("U KING", "GB"), ("INDNSIA", "ID"),
    ]:
        assert iso_for_raw(raw) == iso, raw


def test_raw_normalization_tolerates_case_and_whitespace():
    assert iso_for_raw("  vietnam ") == "VN"
    assert iso_for_raw("Viet  Nam") == "VN"


def test_unknown_bucket():
    for raw in ("", None, "UNKNOWN", "KHONG XAC DINH", "không xác định"):
        assert is_unknown_origin(raw), raw
    assert not is_unknown_origin("SWITZLD")  # present-but-unmapped is NOT unknown
    assert not is_unknown_origin("VIETNAM")


def test_country_label_vi_known_unknown_and_unmapped():
    assert country_label_vi("VIETNAM") == ("Việt Nam", True)
    assert country_label_vi("CHINA") == ("Trung Quốc", True)
    assert country_label_vi("UNKNOWN") == ("Không xác định", True)
    assert country_label_vi("UNKNOWN", unknown_label="Không xuất xứ") == ("Không xuất xứ", True)
    # a real-but-unmapped string renders as-is and flags mapped=False
    assert country_label_vi("WAKANDA") == ("WAKANDA", False)


def test_vietnam_detector():
    assert is_vietnam_origin("VIETNAM")
    assert is_vietnam_origin("viet nam")
    assert not is_vietnam_origin("CHINA")
    assert not is_vietnam_origin("UNKNOWN")


def test_column9_text_qualification_mode_ignores_country():
    assert column9_text(COLUMN9_MODE_QUALIFICATION, "origin", "Trung Quốc") == "Việt Nam"
    assert column9_text(COLUMN9_MODE_QUALIFICATION, "non_origin", "Việt Nam") == "Không xuất xứ"
    assert column9_text(COLUMN9_MODE_QUALIFICATION, "", "X") == "Không xuất xứ"


def test_column9_text_country_mode_ignores_status():
    assert column9_text(COLUMN9_MODE_COUNTRY, "origin", "Trung Quốc") == "Trung Quốc"
    assert column9_text(COLUMN9_MODE_COUNTRY, "non_origin", "Trung Quốc") == "Trung Quốc"


def test_mode_normalization():
    assert normalize_column9_mode("country") == "country"
    assert normalize_column9_mode(" Qualification_Label ") == "qualification_label"
    assert normalize_column9_mode("bogus") == ""
    assert normalize_column9_mode(None) == ""

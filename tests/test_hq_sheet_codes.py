from app.workbook_io import hq_sheet_codes_for_product


def _product(**fields):
    return fields


def test_eur1_with_lvc_override_picks_lvc_sheet():
    product = _product(
        origin_sheet_effective_form_code="EUR.1",
        origin_sheet_criteria_override="LVC 30%",
        origin_sheet_effective_criteria_text="LVC 30%",
        documented_result="Cần đối chiếu mô tả hàng hóa trước khi áp dụng: ...",
    )
    assert hq_sheet_codes_for_product(product) == {"LVC"}


def test_eur1_with_cth_override_picks_cth_sheet():
    product = _product(
        origin_sheet_effective_form_code="EUR.1",
        origin_sheet_criteria_override="CTH",
        documented_result="Cần đối chiếu mô tả hàng hóa trước khi áp dụng: ...",
    )
    assert hq_sheet_codes_for_product(product) == {"CTH"}


def test_eur1_with_no_criterion_match_falls_back_to_eur1():
    product = _product(
        origin_sheet_effective_form_code="EUR.1",
        origin_sheet_criteria_override="",
        documented_result="Cần đối chiếu mô tả hàng hóa trước khi áp dụng: ...",
    )
    assert hq_sheet_codes_for_product(product) == {"EUR1"}


def test_eur1_with_psr_documented_result_picks_psr():
    product = _product(
        origin_sheet_effective_form_code="EUR.1",
        documented_result="Tra PSR Form EUR.1 theo Phụ lục",
    )
    assert hq_sheet_codes_for_product(product) == {"PSR"}


def test_non_eur1_with_lvc_override_picks_lvc():
    product = _product(
        origin_sheet_effective_form_code="B",
        origin_sheet_criteria_override="LVC 30%",
    )
    assert hq_sheet_codes_for_product(product) == {"LVC"}


def test_non_eur1_with_no_criterion_defaults_to_lvc():
    product = _product(origin_sheet_effective_form_code="B")
    assert hq_sheet_codes_for_product(product) == {"LVC"}


def test_override_wins_over_documented_result():
    product = _product(
        origin_sheet_effective_form_code="AI",
        origin_sheet_criteria_override="CTH",
        documented_result="LVC 30%",
    )
    assert hq_sheet_codes_for_product(product) == {"CTH"}

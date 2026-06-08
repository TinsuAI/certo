from app import co_auth


def test_clients_picker_is_guarded_but_not_a_client_id():
    # /clients-picker is a cross-client fragment (lists ALL visible clients).
    # It must be auth-guarded, but guard_response must NOT treat it as a single
    # client_id — otherwise it 403s "picker" against the user's visible set
    # (the prod-only bug from putting it at /clients/picker).
    assert co_auth.should_guard_path("/clients-picker") is True
    assert co_auth.client_id_from_path("/clients-picker") == ""


def test_co_case_picker_keeps_real_client_id():
    # The per-client case picker DOES carry a real client_id and is checked
    # against the visible set as usual.
    assert co_auth.should_guard_path("/clients/johnson-vn/co-case-picker") is True
    assert co_auth.client_id_from_path("/clients/johnson-vn/co-case-picker") == "johnson-vn"


def test_clients_list_still_guarded():
    assert co_auth.should_guard_path("/clients") is True
    assert co_auth.client_id_from_path("/clients") == ""

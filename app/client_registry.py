from __future__ import annotations

from app.app_state_store import get_app_state_store
from app.demo_data import (
    DEMO_CASE,
    attach_results,
    clone_case,
    get_client as seed_get_client,
    get_client_case as seed_get_client_case,
    get_clients as seed_get_clients,
    get_demo_case,
)


def get_clients() -> list[dict]:
    store = get_app_state_store()
    if store and store.has_clients():
        return store.clients()
    return seed_get_clients()


def get_client(client_id: str) -> dict:
    store = get_app_state_store()
    if store and store.has_clients():
        return store.client(client_id)
    return seed_get_client(client_id)


def get_client_case(client_id: str) -> dict:
    client = get_client(client_id)
    if client_id == "growatt":
        return get_demo_case()
    case = clone_case(DEMO_CASE)
    case.update(
        {
            "id": f"{client_id}-empty-co-case",
            "customer": client["name"],
            "case_code": "Chưa tạo",
            "title": f"Hồ sơ C/O {client['name']}",
            "destination_market": "Chưa nhập",
            "agreement": "Chưa nhập",
            "co_form_type": "Chưa nhập",
            "source_label": "Chưa có dữ liệu C/O",
            "products": [],
        }
    )
    return attach_results(case)


def seed_clients() -> list[dict]:
    return [seed_get_client(row["id"]) for row in seed_get_clients()]


def seed_client_case(client_id: str) -> dict:
    return seed_get_client_case(client_id)

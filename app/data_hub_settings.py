from __future__ import annotations

import os
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping


DEFAULT_DATA_HUB_BASE_URL = "http://127.0.0.1:8754"
DEFAULT_DATA_HUB_TIMEOUT_SECONDS = 20.0
DEFAULT_DATA_HUB_CONFIG_PATH = "data/local/runtime/data-hub-link.json"
DEFAULT_CO_CASE_DELETE_ROLES = ("dev", "admin")
DEFAULT_CLIENT_CLAIM_KEYS = (
    "client_ids",
    "clients",
    "allowed_clients",
    "visible_clients",
    "dncx_ids",
    "client_id",
    "dncx_id",
)
DEFAULT_ADMIN_ROLES = ("dev", "admin")
TRUTHY = {"1", "true", "yes", "on"}
DATA_HUB_LINK_ENV_KEYS = (
    "DATA_HUB_ENABLED",
    "CO_ALLOW_LOCAL_SOURCE",
    "CO_AUTH_REQUIRED",
    "DATA_HUB_BASE_URL",
    "DATA_HUB_API_BASE_URL",
    "DATA_HUB_ISSUER_URL",
    "DATA_HUB_JWKS_URL",
    "DATA_HUB_SERVICE_TOKEN",
    "CO_PUBLIC_BASE_URL",
    "CO_FORCE_HTTPS_COOKIE",
    "DATA_HUB_REQUEST_TIMEOUT_SECONDS",
    "DATA_HUB_CLIENT_CLAIM_KEYS",
    "DATA_HUB_ADMIN_ROLES",
    "CO_CASE_DELETE_ROLES",
)
SECRET_ENV_KEYS = {"DATA_HUB_SERVICE_TOKEN"}


@dataclass(frozen=True)
class DataHubLinkSettings:
    source_enabled: bool
    allow_local_source: bool
    auth_required: bool
    data_hub_base_url: str
    data_hub_api_base_url: str
    issuer_url: str
    jwks_url: str
    api_token: str
    co_public_base_url: str
    force_https_cookie: bool
    request_timeout_seconds: float
    client_claim_keys: tuple[str, ...]
    admin_roles: frozenset[str]
    co_case_delete_roles: frozenset[str]

    @classmethod
    def from_env(cls, environ: Mapping[str, str] | None = None) -> DataHubLinkSettings:
        values = os.environ if environ is None else environ
        data_hub_base_url = clean_url(values.get("DATA_HUB_BASE_URL"), DEFAULT_DATA_HUB_BASE_URL)
        data_hub_api_base_url = clean_url(values.get("DATA_HUB_API_BASE_URL"), data_hub_base_url)
        issuer_url = clean_url(values.get("DATA_HUB_ISSUER_URL"), data_hub_base_url)
        jwks_url = clean_url(values.get("DATA_HUB_JWKS_URL"), f"{issuer_url}/v1/auth/jwks")
        return cls(
            source_enabled=env_flag(values.get("DATA_HUB_ENABLED")),
            allow_local_source=env_flag(values.get("CO_ALLOW_LOCAL_SOURCE")),
            auth_required=env_flag(values.get("CO_AUTH_REQUIRED")),
            data_hub_base_url=data_hub_base_url,
            data_hub_api_base_url=data_hub_api_base_url,
            issuer_url=issuer_url,
            jwks_url=jwks_url,
            api_token=values.get("DATA_HUB_SERVICE_TOKEN", "").strip(),
            co_public_base_url=clean_url(values.get("CO_PUBLIC_BASE_URL"), ""),
            force_https_cookie=env_flag(values.get("CO_FORCE_HTTPS_COOKIE")),
            request_timeout_seconds=positive_float_env(
                values,
                "DATA_HUB_REQUEST_TIMEOUT_SECONDS",
                DEFAULT_DATA_HUB_TIMEOUT_SECONDS,
            ),
            client_claim_keys=env_list(values.get("DATA_HUB_CLIENT_CLAIM_KEYS"), DEFAULT_CLIENT_CLAIM_KEYS),
            admin_roles=frozenset(env_list(values.get("DATA_HUB_ADMIN_ROLES"), DEFAULT_ADMIN_ROLES)),
            co_case_delete_roles=frozenset(env_list(values.get("CO_CASE_DELETE_ROLES"), DEFAULT_CO_CASE_DELETE_ROLES)),
        )

    def require_source_config(self) -> None:
        return None


def data_hub_link_settings() -> DataHubLinkSettings:
    return DataHubLinkSettings.from_env(merged_data_hub_link_env())


def env_flag(value: str | None) -> bool:
    return (value or "").strip().lower() in TRUTHY


def clean_url(value: str | None, default: str) -> str:
    return (value or default).strip().rstrip("/")


def env_list(value: str | None, default: tuple[str, ...]) -> tuple[str, ...]:
    raw = (value or "").replace(",", " ").split()
    items = tuple(item.strip() for item in raw if item.strip())
    return items or default


def positive_float_env(values: Mapping[str, str], key: str, default: float) -> float:
    raw = values.get(key, "").strip()
    if not raw:
        return default
    try:
        value = float(raw)
    except ValueError as exc:
        raise RuntimeError(f"{key} must be a positive number.") from exc
    if value <= 0:
        raise RuntimeError(f"{key} must be a positive number.")
    return value


def data_hub_config_path(environ: Mapping[str, str] | None = None) -> Path:
    values = os.environ if environ is None else environ
    return Path(values.get("DATA_HUB_CONFIG_PATH", DEFAULT_DATA_HUB_CONFIG_PATH)).expanduser()


def load_data_hub_overrides(environ: Mapping[str, str] | None = None) -> dict[str, str]:
    path = data_hub_config_path(environ)
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"Could not read Data Hub config override file: {path}") from exc
    if not isinstance(payload, dict):
        raise RuntimeError(f"Data Hub config override file must contain a JSON object: {path}")
    return {
        key: str(value).strip()
        for key, value in payload.items()
        if key in DATA_HUB_LINK_ENV_KEYS and value is not None
    }


def save_data_hub_overrides(overrides: Mapping[str, str], environ: Mapping[str, str] | None = None) -> Path:
    path = data_hub_config_path(environ)
    payload = {
        key: str(value).strip()
        for key, value in overrides.items()
        if key in DATA_HUB_LINK_ENV_KEYS and value is not None
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


def merged_data_hub_link_env(environ: Mapping[str, str] | None = None) -> dict[str, str]:
    values = dict(os.environ if environ is None else environ)
    merged = load_data_hub_overrides(values)
    merged.update(values)
    return merged

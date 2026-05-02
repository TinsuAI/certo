from __future__ import annotations

import fcntl
import json
import os
import re
import tempfile
import uuid
from contextlib import contextmanager
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from urllib.parse import quote

import httpx

from app.database import apply_migrations, connect, database_url


CUSTOMS_FX_CLIENT_ID = "global"
CUSTOMS_FX_SOURCE = "customs.gov.vn"
CUSTOMS_FX_BASE_URL = "https://www.customs.gov.vn/bridge?url=/customs/api/"
CUSTOMS_FX_USER_AGENT = "Mozilla/5.0"


class CustomsFxError(ValueError):
    pass


def get_customs_fx_store() -> "PostgresCustomsFxStore | FileCustomsFxStore":
    url = database_url()
    return PostgresCustomsFxStore(url) if url else FileCustomsFxStore()


def refresh_customs_exchange_rates(
    *,
    client_id: str = CUSTOMS_FX_CLIENT_ID,
    language: str = "TIENG_VIET",
    transport: httpx.BaseTransport | None = None,
) -> dict:
    rows = fetch_customs_exchange_rates(language=language, transport=transport)
    return get_customs_fx_store().save_refresh(client_id, rows)


def fetch_customs_exchange_rates(
    *,
    language: str = "TIENG_VIET",
    transport: httpx.BaseTransport | None = None,
) -> list[dict]:
    encoded_language = quote(language)
    with httpx.Client(
        transport=transport,
        timeout=30,
        headers={"User-Agent": CUSTOMS_FX_USER_AGENT},
    ) as client:
        currency_payload = fetch_customs_json(client, f"GetListDongTienTyGia&language={encoded_language}")
        usd_payload = fetch_customs_json(client, f"GetListUSDRate&language={encoded_language}")
        other_payload = fetch_customs_json(client, f"GetListOtherRate&language={encoded_language}")
    return parse_customs_exchange_rate_payloads(currency_payload, usd_payload, other_payload)


def fetch_customs_json(client: httpx.Client, endpoint: str) -> dict:
    response = client.get(f"{CUSTOMS_FX_BASE_URL}{endpoint}")
    response.raise_for_status()
    payload = response.json()
    if not isinstance(payload, dict):
        raise CustomsFxError("Customs FX endpoint returned a non-object payload.")
    return payload


def parse_customs_exchange_rate_payloads(currency_payload: dict, usd_payload: dict, other_payload: dict) -> list[dict]:
    fetched_at = now_iso()
    currency_names = {
        clean_text(item.get("DONG_TIEN")).upper(): clean_text(item.get("TEN_DONG_TIEN"))
        for item in payload_items(currency_payload)
        if clean_text(item.get("DONG_TIEN"))
    }
    rows = []
    for item in payload_items(usd_payload):
        code = clean_text(item.get("LOAI_NGOAI_TE") or "USD").upper() or "USD"
        row = customs_rate_row(
            currency_code=code,
            currency_name=currency_names.get(code, "Đô-la Mỹ" if code == "USD" else ""),
            effective_date=parse_customs_date(item.get("HIEU_LUC_TU_NGAY")),
            rate=parse_vnd_rate_text(item.get("TY_GIA")),
            rate_text=clean_text(item.get("TY_GIA")),
            source_endpoint="GetListUSDRate",
            fetched_at=fetched_at,
        )
        if row:
            rows.append(row)
    for item in payload_items(other_payload):
        code = clean_text(item.get("LOAI_NGOAI_TE")).upper()
        row = customs_rate_row(
            currency_code=code,
            currency_name=clean_text(item.get("TEN_NGOAI_TE")) or currency_names.get(code, ""),
            effective_date=parse_customs_date(item.get("HIEU_LUC_TU_NGAY")),
            rate=parse_vnd_rate_text(item.get("TY_GIA")),
            rate_text=clean_text(item.get("TY_GIA")),
            source_endpoint="GetListOtherRate",
            fetched_at=fetched_at,
        )
        if row:
            rows.append(row)
    return sorted(dedupe_rows(rows), key=lambda row: (row["effective_date"], row["currency_code"]), reverse=True)


def payload_items(payload: dict) -> list[dict]:
    items = payload.get("d", [])
    if not isinstance(items, list):
        return []
    return [item for item in items if isinstance(item, dict)]


def customs_rate_row(
    *,
    currency_code: str,
    currency_name: str,
    effective_date: date | None,
    rate: Decimal,
    rate_text: str,
    source_endpoint: str,
    fetched_at: str,
) -> dict | None:
    if not currency_code or effective_date is None or rate <= 0:
        return None
    row = {
        "row_key": f"{currency_code}-{effective_date.isoformat()}",
        "currency_code": currency_code,
        "currency_name": currency_name,
        "effective_date": effective_date.isoformat(),
        "rate_vnd_per_unit": decimal_text(rate),
        "rate_text": rate_text,
        "rate_display": format_vnd_rate(rate),
        "source": CUSTOMS_FX_SOURCE,
        "source_endpoint": source_endpoint,
        "fetched_at": fetched_at,
    }
    return row


def dedupe_rows(rows: list[dict]) -> list[dict]:
    by_key = {}
    for row in rows:
        by_key[(row["currency_code"], row["effective_date"])] = row
    return list(by_key.values())


def lookup_exchange_rate(rows: list[dict], currency_code: str, declaration_date: date | str | None) -> dict | None:
    effective_date = parse_customs_date(declaration_date)
    if effective_date is None:
        return None
    code = clean_text(currency_code).upper()
    applicable = None
    for row in sorted(rows, key=lambda item: item.get("effective_date", "")):
        row_date = parse_customs_date(row.get("effective_date"))
        if row.get("currency_code") != code or row_date is None:
            continue
        if row_date <= effective_date:
            applicable = row
            continue
        break
    return applicable


class FileCustomsFxStore:
    def rows(self, client_id: str = CUSTOMS_FX_CLIENT_ID) -> list[dict]:
        return prepare_rows(read_state(client_id).get("rows", []))

    def summary(self, client_id: str = CUSTOMS_FX_CLIENT_ID) -> dict:
        state = read_state(client_id)
        return summary_from_rows(prepare_rows(state.get("rows", [])), state.get("refreshes", []), backend="files")

    def save_refresh(self, client_id: str, rows: list[dict]) -> dict:
        with store_lock(client_id):
            state = read_state(client_id)
            existing = {
                (row["currency_code"], row["effective_date"]): row
                for row in prepare_rows(state.get("rows", []))
            }
            upserted = 0
            for row in prepare_rows(rows):
                key = (row["currency_code"], row["effective_date"])
                if existing.get(key) != row:
                    upserted += 1
                existing[key] = row
            saved_rows = sorted(existing.values(), key=lambda row: (row["effective_date"], row["currency_code"]), reverse=True)
            summary = summary_values(saved_rows)
            refresh = refresh_record(
                client_id=client_id,
                fetched_row_count=len(rows),
                upserted_row_count=upserted,
                saved_row_count=len(saved_rows),
                **summary,
            )
            state = {
                "schema_version": 1,
                "client_id": client_id,
                "rows": saved_rows,
                "refreshes": [refresh, *state.get("refreshes", [])[:49]],
                "updated_at": now_iso(),
            }
            write_json(state_path(client_id), state)
            return {**refresh, "backend": "files"}


class PostgresCustomsFxStore:
    def __init__(self, url: str):
        self.url = url

    def ensure_schema(self) -> None:
        apply_migrations(self.url)

    def rows(self, client_id: str = CUSTOMS_FX_CLIENT_ID) -> list[dict]:
        self.ensure_schema()
        with connect(self.url) as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    select currency_code, currency_name, effective_date::text,
                           rate_vnd_per_unit::text, rate_text, source,
                           source_endpoint, payload, fetched_at::text, updated_at::text
                    from customs_exchange_rate_rows
                    where client_id = %s
                    order by effective_date desc, currency_code
                    """,
                    (client_id,),
                )
                rows = []
                for row in cursor.fetchall():
                    payload = dict(row[7] or {})
                    payload.update({
                        "currency_code": row[0],
                        "currency_name": row[1],
                        "effective_date": row[2],
                        "rate_vnd_per_unit": row[3],
                        "rate_text": row[4],
                        "source": row[5],
                        "source_endpoint": row[6],
                        "fetched_at": row[8],
                        "updated_at": row[9],
                    })
                    rows.append(payload)
                return prepare_rows(rows)

    def summary(self, client_id: str = CUSTOMS_FX_CLIENT_ID) -> dict:
        self.ensure_schema()
        with connect(self.url) as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    select count(*), count(distinct currency_code), max(effective_date)::text
                    from customs_exchange_rate_rows
                    where client_id = %s
                    """,
                    (client_id,),
                )
                count, currency_count, latest_effective_date = cursor.fetchone()
                cursor.execute(
                    """
                    select payload
                    from customs_exchange_rate_refreshes
                    where client_id = %s
                    order by created_at desc
                    limit 1
                    """,
                    (client_id,),
                )
                refresh = cursor.fetchone()
        return {
            "backend": "postgres",
            "row_count": int(count or 0),
            "currency_count": int(currency_count or 0),
            "latest_effective_date": latest_effective_date or "",
            "latest_refresh": dict(refresh[0]) if refresh else {},
        }

    def save_refresh(self, client_id: str, rows: list[dict]) -> dict:
        from psycopg.types.json import Jsonb

        self.ensure_schema()
        prepared_rows = prepare_rows(rows)
        summary = summary_values(prepared_rows)
        refresh = refresh_record(
            client_id=client_id,
            fetched_row_count=len(rows),
            upserted_row_count=len(prepared_rows),
            saved_row_count=0,
            **summary,
        )
        with connect(self.url) as connection:
            with connection.cursor() as cursor:
                cursor.executemany(
                    """
                    insert into customs_exchange_rate_rows (
                      client_id, currency_code, effective_date, currency_name,
                      rate_vnd_per_unit, rate_text, source, source_endpoint,
                      payload, fetched_at, updated_at
                    )
                    values (%s, %s, %s, %s, %s, %s, %s, %s, %s, coalesce(%s::timestamptz, now()), now())
                    on conflict (client_id, currency_code, effective_date) do update set
                      currency_name = excluded.currency_name,
                      rate_vnd_per_unit = excluded.rate_vnd_per_unit,
                      rate_text = excluded.rate_text,
                      source = excluded.source,
                      source_endpoint = excluded.source_endpoint,
                      payload = excluded.payload,
                      fetched_at = excluded.fetched_at,
                      updated_at = now()
                    """,
                    [
                        (
                            client_id,
                            row["currency_code"],
                            row["effective_date"],
                            row["currency_name"],
                            row["rate_vnd_per_unit"],
                            row["rate_text"],
                            row["source"],
                            row["source_endpoint"],
                            Jsonb(row),
                            row.get("fetched_at"),
                        )
                        for row in prepared_rows
                    ],
                )
                cursor.execute(
                    "select count(*) from customs_exchange_rate_rows where client_id = %s",
                    (client_id,),
                )
                refresh["saved_row_count"] = int(cursor.fetchone()[0] or 0)
                cursor.execute(
                    """
                    insert into customs_exchange_rate_refreshes (
                      refresh_id, client_id, status, source, fetched_row_count,
                      upserted_row_count, saved_row_count, currency_count,
                      latest_effective_date, payload
                    )
                    values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    """,
                    (
                        refresh["refresh_id"],
                        client_id,
                        refresh["status"],
                        refresh["source"],
                        refresh["fetched_row_count"],
                        refresh["upserted_row_count"],
                        refresh["saved_row_count"],
                        refresh["currency_count"],
                        refresh["latest_effective_date"] or None,
                        Jsonb(refresh),
                    ),
                )
        return {**refresh, "backend": "postgres"}


def prepare_rows(rows: list[dict]) -> list[dict]:
    prepared = []
    for row in rows:
        code = clean_text(row.get("currency_code")).upper()
        effective_date = parse_customs_date(row.get("effective_date"))
        rate = parse_vnd_rate_text(row.get("rate_vnd_per_unit") or row.get("rate_text"))
        if not code or effective_date is None or rate <= 0:
            continue
        next_row = {
            **row,
            "row_key": row.get("row_key") or f"{code}-{effective_date.isoformat()}",
            "currency_code": code,
            "currency_name": clean_text(row.get("currency_name")),
            "effective_date": effective_date.isoformat(),
            "rate_vnd_per_unit": decimal_text(rate),
            "rate_display": format_vnd_rate(rate),
            "rate_text": clean_text(row.get("rate_text")),
            "source": clean_text(row.get("source")) or CUSTOMS_FX_SOURCE,
            "source_endpoint": clean_text(row.get("source_endpoint")),
            "fetched_at": clean_text(row.get("fetched_at")),
        }
        prepared.append(next_row)
    return sorted(dedupe_rows(prepared), key=lambda row: (row["effective_date"], row["currency_code"]), reverse=True)


def summary_from_rows(rows: list[dict], refreshes: list[dict], *, backend: str) -> dict:
    return {
        "backend": backend,
        **summary_values(rows),
        "latest_refresh": refreshes[0] if refreshes else {},
    }


def summary_values(rows: list[dict]) -> dict:
    return {
        "row_count": len(rows),
        "currency_count": len({row["currency_code"] for row in rows}),
        "latest_effective_date": max([row["effective_date"] for row in rows] or [""]),
    }


def refresh_record(
    *,
    client_id: str,
    fetched_row_count: int,
    upserted_row_count: int,
    saved_row_count: int,
    row_count: int,
    currency_count: int,
    latest_effective_date: str,
) -> dict:
    return {
        "refresh_id": make_id("customs-fx-refresh"),
        "client_id": client_id,
        "status": "updated" if fetched_row_count else "empty",
        "source": CUSTOMS_FX_SOURCE,
        "fetched_row_count": fetched_row_count,
        "upserted_row_count": upserted_row_count,
        "saved_row_count": saved_row_count or row_count,
        "currency_count": currency_count,
        "latest_effective_date": latest_effective_date,
        "error": "",
        "created_at": now_iso(),
    }


def parse_customs_date(value) -> date | None:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = clean_text(value)
    if not text:
        return None
    for fmt in ("%d/%m/%Y", "%Y-%m-%d", "%d-%m-%Y"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    return None


def parse_vnd_rate_text(value) -> Decimal:
    text = clean_text(value)
    if not text:
        return Decimal("0")
    numeric = re.sub(r"[^0-9,.-]", "", text)
    if not numeric:
        return Decimal("0")
    if "," in numeric:
        normalized = numeric.replace(".", "").replace(",", ".")
    elif "." in numeric:
        parts = numeric.split(".")
        normalized = "".join(parts) if len(parts[-1]) == 3 else numeric
    else:
        normalized = numeric
    try:
        return Decimal(normalized)
    except InvalidOperation:
        return Decimal("0")


def format_vnd_rate(value: Decimal) -> str:
    if value == value.to_integral_value():
        return f"{int(value):,}".replace(",", ".") + " VNĐ"
    text = decimal_text(value)
    whole, fraction = text.split(".", 1)
    whole_text = f"{int(whole):,}".replace(",", ".")
    return f"{whole_text},{fraction} VNĐ"


def decimal_text(value: Decimal) -> str:
    text = format(value, "f")
    return text.rstrip("0").rstrip(".") if "." in text else text


def read_state(client_id: str) -> dict:
    path = state_path(client_id)
    if not path.exists():
        return {"schema_version": 1, "client_id": client_id, "rows": [], "refreshes": []}
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2, sort_keys=True)
        handle.write("\n")
    os.replace(tmp_name, path)


@contextmanager
def store_lock(client_id: str):
    root = state_path(client_id).parent
    root.mkdir(parents=True, exist_ok=True)
    lock_path = root / ".lock"
    with lock_path.open("w") as handle:
        fcntl.flock(handle, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(handle, fcntl.LOCK_UN)


def state_path(client_id: str) -> Path:
    return customs_fx_root() / "clients" / safe_id(client_id) / "state.json"


def customs_fx_root() -> Path:
    return Path(os.environ.get("CUSTOMS_FX_STORE_ROOT", "data/local/customs-fx"))


def safe_id(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "-", clean_text(value)).strip("-._") or CUSTOMS_FX_CLIENT_ID


def make_id(prefix: str) -> str:
    return f"{prefix}-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S%f')}-{uuid.uuid4().hex[:8]}"


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def clean_text(value) -> str:
    if value is None:
        return ""
    return str(value).replace("\xa0", " ").strip()

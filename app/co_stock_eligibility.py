"""Single source of truth for "is this stock lot eligible for this case?".

Two checks layered:

1. Status / allocation gate — the existing CO eligibility (`active`,
   `allocation_code_status='resolved'`). Same predicate as the legacy
   `co_stock_is_usable`.
2. Import→export date gap — regulatory rule: the lot's import
   `registration_date` must be at least `min_gap_days` (default 2)
   before the case's export registration date. Inclusive (`>=`),
   calendar days.

Both checks fail-open on missing data: rows without a status field or
without a registration_date are NOT rejected by THAT check (status
gate still fires on the status). The caller's `export_date` argument
is optional — when absent, the gap check is a no-op.

Returns `EligibilityVerdict(ok, reason)` so callers can:
- branch on `verdict.ok`
- surface `verdict.reason` in the UI (Vietnamese strings via
  `REJECTION_LABELS`).
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from typing import Iterable


REASON_OK = "ok"
REASON_INELIGIBLE_STATUS = "ineligible_status"
REASON_UNRESOLVED_ALLOCATION = "unresolved_allocation_code"
REASON_IMPORT_TOO_RECENT = "import_too_recent"

REJECTION_LABELS = {
    REASON_INELIGIBLE_STATUS: "Lô đang không khả dụng cho CO",
    REASON_UNRESOLVED_ALLOCATION: "Mã phân bổ chưa được xác nhận",
    REASON_IMPORT_TOO_RECENT: "Ngày nhập quá gần ngày xuất khẩu",
}

DEFAULT_MIN_GAP_DAYS = 2
ALLOWED_ELIGIBILITY_VALUES = {"active", "eligible", "available"}


@dataclass(frozen=True)
class EligibilityVerdict:
    ok: bool
    reason: str

    @property
    def label(self) -> str:
        return REJECTION_LABELS.get(self.reason, "")


def is_stock_lot_eligible(
    row: dict,
    *,
    export_date: date | None = None,
    min_gap_days: int = DEFAULT_MIN_GAP_DAYS,
) -> EligibilityVerdict:
    """Decide whether a stock row may be allocated to a case.

    `export_date` is the case's export-side anchor (earliest
    `registration_date` across the case's export BCCT declarations);
    omit to skip the date-gap check.

    `min_gap_days = 0` disables the gap rule entirely — useful for
    clients whose customs agency does not enforce it. The gap check
    also no-ops when the row lacks a parseable `registration_date`
    (legacy rows from before commit `06f8c2f`).
    """
    eligibility = str(row.get("eligibility_status") or "").strip()
    if eligibility and eligibility not in ALLOWED_ELIGIBILITY_VALUES:
        return EligibilityVerdict(False, REASON_INELIGIBLE_STATUS)
    allocation_status = str(row.get("allocation_code_status") or "").strip()
    if allocation_status and allocation_status != "resolved":
        return EligibilityVerdict(False, REASON_UNRESOLVED_ALLOCATION)
    if min_gap_days > 0 and export_date is not None:
        import_date = _parse_row_import_date(row)
        if import_date is not None:
            gap = (export_date - import_date).days
            if gap < min_gap_days:
                return EligibilityVerdict(False, REASON_IMPORT_TOO_RECENT)
    return EligibilityVerdict(True, REASON_OK)


def _parse_row_import_date(row: dict) -> date | None:
    """Read the lot's import-side date.

    Try `registration_date` first (post-`06f8c2f`), then fall back
    to `declaration_date` and `import_declaration_date` for legacy
    payloads. Accept ISO `YYYY-MM-DD`, ISO datetime, and DD/MM/YYYY.
    Returns None when nothing parses — callers treat that as "no
    gap data, don't filter on this axis".
    """
    for key in ("registration_date", "declaration_date", "import_declaration_date"):
        value = row.get(key)
        if value:
            parsed = parse_flexible_date(value)
            if parsed is not None:
                return parsed
    return None


def parse_flexible_date(value) -> date | None:
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    if isinstance(value, datetime):
        return value.date()
    text = str(value or "").strip()
    if not text:
        return None
    # ISO date / ISO datetime
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).date()
    except ValueError:
        pass
    # DD/MM/YYYY (Vietnamese customs format)
    for fmt in ("%d/%m/%Y", "%d-%m-%Y", "%Y%m%d"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    return None


def earliest_export_date(declaration_records: Iterable[dict]) -> date | None:
    """Pick the earliest parseable `registration_date` across a case's
    matched export BCCT records — used as the conservative anchor
    when a case has multiple export declarations."""
    dates: list[date] = []
    for record in declaration_records or []:
        if not isinstance(record, dict):
            continue
        for key in ("registration_date", "declaration_date"):
            parsed = parse_flexible_date(record.get(key))
            if parsed is not None:
                dates.append(parsed)
                break
    return min(dates) if dates else None


def min_gap_days_from_config(client_config: dict | None) -> int:
    """Read `client_config["co_stock"]["min_days_before_export"]`.

    Falsy / missing → DEFAULT_MIN_GAP_DAYS (2). 0 disables the rule.
    Negative or non-int → DEFAULT (defensive).
    """
    if not isinstance(client_config, dict):
        return DEFAULT_MIN_GAP_DAYS
    co_stock_config = client_config.get("co_stock")
    if not isinstance(co_stock_config, dict):
        return DEFAULT_MIN_GAP_DAYS
    raw = co_stock_config.get("min_days_before_export")
    if raw is None:
        return DEFAULT_MIN_GAP_DAYS
    try:
        n = int(raw)
    except (TypeError, ValueError):
        return DEFAULT_MIN_GAP_DAYS
    return n if n >= 0 else DEFAULT_MIN_GAP_DAYS

"""OpenAI-compat LLM client + parser-mapping proposal.

Mirrors the BCQT-System pattern (`~/workspace/client/BCQT-System/app/pipeline/
user_checks.py`): use the OpenAI SDK pointed at any compatible endpoint
(Anthropic via OpenAI-compat, OpenAI direct, vLLM, llama.cpp, Ollama).
Settings live in `hub.app_settings`; callers go through `LLMConfig.load()`.

Single responsibility for hub MVP: given a workbook's headers + a few
sample rows, propose a mapping `header → logical_field` for one of the
4 modules (bcct/catalog/bqd/bom). User must confirm via UI before the
mapping is cached.

Cost / safety:
- Per-(date, client_id) budget enforced via `hub.llm_usage`.
- Only headers + 5 truncated sample rows sent (cell strings clipped to
  100 chars; no raw user prose).
- Tool-call structured output (function calling) → schema-validated.
- API key + base_url + model live in app_settings, settable via
  /admin/settings/technical (dev-only).
"""
from __future__ import annotations

import logging
import json
from dataclasses import dataclass
from datetime import date

from app import settings_store
from app.database import connect

logger = logging.getLogger(__name__)

# Sentinels — overridable via app_settings. Callers should accept None
# (LLM disabled) without crashing.
DEFAULT_TIMEOUT_S = 30
DEFAULT_MAX_RETRIES = 2
DEFAULT_TEMPERATURE = 0.0
DEFAULT_MAX_CALLS_PER_DAY = 50

CELL_TRUNCATE = 100  # chars per cell sent to LLM


class LLMUnavailable(RuntimeError):
    """Raised when LLM is not configured or budget exhausted."""


class LLMProposalError(RuntimeError):
    """Raised when the LLM returned a malformed / non-validating proposal."""


@dataclass
class LLMConfig:
    base_url: str
    model: str
    api_key: str
    temperature: float
    timeout_s: int
    max_retries: int
    max_calls_per_day_per_client: int

    @classmethod
    def load(cls) -> "LLMConfig":
        s = settings_store.get_many(settings_store.LLM_KEYS)
        return cls(
            base_url=s.get("llm_base_url", "") or "",
            model=s.get("llm_model", "") or "",
            api_key=s.get("llm_api_key", "") or "",
            temperature=settings_store.get_float("llm_temperature", DEFAULT_TEMPERATURE),
            timeout_s=settings_store.get_int("llm_timeout_s", DEFAULT_TIMEOUT_S),
            max_retries=settings_store.get_int("llm_max_retries", DEFAULT_MAX_RETRIES),
            max_calls_per_day_per_client=settings_store.get_int(
                "llm_max_calls_per_day_per_client", DEFAULT_MAX_CALLS_PER_DAY,
            ),
        )

    def is_enabled(self) -> bool:
        return bool(self.base_url) and bool(self.model) and bool(self.api_key)


def _check_and_record_budget(client_id: str, cfg: LLMConfig) -> None:
    """Enforce per-(date, client_id) call budget. Raises LLMUnavailable
    when exceeded. Increments call_count atomically on success path."""
    today = date.today()
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                insert into hub.llm_usage (date, client_id, call_count)
                values (%s, %s, 1)
                on conflict (date, client_id) do update
                  set call_count = hub.llm_usage.call_count + 1,
                      last_call_at = now()
                returning call_count
                """,
                (today, client_id),
            )
            (count,) = cur.fetchone()
    if count > cfg.max_calls_per_day_per_client:
        raise LLMUnavailable(
            f"LLM daily budget exceeded for {client_id}: "
            f"{count}/{cfg.max_calls_per_day_per_client}"
        )


def _truncate_cell(v) -> str:
    if v is None:
        return ""
    s = str(v)
    if len(s) > CELL_TRUNCATE:
        return s[: CELL_TRUNCATE - 1] + "…"
    return s


_TARGET_FIELDS_BY_MODULE: dict[str, list[str]] = {
    "bcct": [
        "declaration_no", "line_no", "declaration_type", "registration_date",
        "customs_code", "goods_name", "hs_code", "quantity", "unit",
        "total_value", "total_value_nt", "currency_nt",
        "unit_price", "unit_price_nt",
        "total_tax", "unloading_location",
        "origin", "invoice_ref",
        "exporter_name", "exporter_tax_code", "consignee_name", "incoterms",
        "weight", "weight_unit", "package_count", "package_unit",
        "invoice_date", "departure_date",
        "destination_code", "destination_name",
        "transport_mode", "exchange_rate",
    ],
    "catalog": ["customs_code", "internal_code", "name", "category", "unit",
                "hs_code", "status"],
    "bqd": ["internal_code", "customs_code", "category", "notes"],
    "bom": ["product_code", "material_code", "qty_per_unit", "uom",
            "bom_code", "bom_variant_id"],
}


def propose_header_mapping(
    *,
    client_id: str,
    module: str,
    headers: list[str],
    sample_rows: list[list],
    cfg: LLMConfig | None = None,
) -> dict[str, str]:
    """Ask the LLM to propose a mapping `header_name → logical_field` for
    a workbook whose rigid parser failed.

    Returns: dict mapping each KNOWN header to a logical field name (or
    omitted if the LLM judged it unmapped). Callers MUST present this to
    a human before persisting to `hub.parser_mappings`.

    Raises:
        LLMUnavailable — LLM not configured or daily budget exhausted.
        LLMProposalError — model returned invalid / unparseable output.
    """
    if module not in _TARGET_FIELDS_BY_MODULE:
        raise ValueError(f"Unknown module: {module}")
    cfg = cfg or LLMConfig.load()
    if not cfg.is_enabled():
        raise LLMUnavailable("LLM not configured (set keys in /admin/settings/technical)")

    _check_and_record_budget(client_id, cfg)

    target_fields = _TARGET_FIELDS_BY_MODULE[module]

    # Build a compact, defended prompt: headers + truncated sample. No
    # raw user prose passes through unescaped.
    truncated_samples = [
        [_truncate_cell(c) for c in row]
        for row in sample_rows[:5]
    ]
    user_payload = {
        "module": module,
        "headers": headers,
        "samples": truncated_samples,
        "logical_fields": target_fields,
    }

    # OpenAI's structured-output rule + many compat servers (LM Studio,
    # llama.cpp grammar mode, vLLM) enforce: when response_format is json,
    # the word "json" must appear lowercase in the messages. Make sure it
    # does — both in system prompt and in the user payload.
    system = (
        "You are a Vietnamese-customs Excel column-mapping assistant. The "
        "user uploads a spreadsheet whose headers don't match the rigid "
        "parser's alias list. Given headers + a few sample rows + a list "
        "of logical fields, return a json object mapping each input header "
        "to one logical field (or omit if unmapped). Headers are "
        "Vietnamese, English, or Chinese. Match by both the header text "
        "and the value patterns in the samples (numeric vs date vs short "
        "codes).\n\n"
        "Output rules:\n"
        "1. Each logical field is mapped to AT MOST one header.\n"
        "2. Each header maps to AT MOST one logical field (omit ambiguous).\n"
        "3. Use only the provided logical_fields. Don't invent new ones.\n"
        "4. Prefer omitting over guessing.\n"
        "5. Reply with strict json only: "
        "{\"mapping\": {\"<header>\": \"<logical_field>\", ...}}\n"
        "Do not return anything outside the json object."
    )
    user = (
        "json input follows. Reply with json only.\n\n"
        + json.dumps(user_payload, ensure_ascii=False)
    )

    from openai import OpenAI

    client = OpenAI(
        base_url=cfg.base_url,
        api_key=cfg.api_key or "not-needed",
        timeout=cfg.timeout_s,
        max_retries=cfg.max_retries,
    )

    valid_fields = set(target_fields)
    valid_headers = set(headers)

    # Self-correction loop: if the LLM returns invalid output (non-JSON,
    # missing 'mapping' key, all-zero valid pairs), feed the error back
    # and ask for a fix. Pattern lifted from BCQT-System's draft_and_validate
    # in app/pipeline/user_checks.py.
    messages: list[dict] = [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]
    last_err: str | None = None
    for attempt in range(max(1, cfg.max_retries) + 1):
        try:
            completion = client.chat.completions.create(
                model=cfg.model,
                messages=messages,
                temperature=cfg.temperature,
                response_format={"type": "json_object"},
            )
        except Exception as e:  # noqa: BLE001
            logger.exception("llm.propose_header_mapping: API call raised")
            raise LLMProposalError(f"LLM API error: {e}") from e

        content = completion.choices[0].message.content or ""
        try:
            parsed = json.loads(content)
        except json.JSONDecodeError:
            last_err = (
                f"Reply was not valid json: {content[:120]!r}. "
                f"Reply with strict json only, no prose, no markdown, no code fences."
            )
            messages.append({"role": "assistant", "content": content})
            messages.append({"role": "user", "content": last_err})
            continue

        mapping = parsed.get("mapping") if isinstance(parsed, dict) else None
        if not isinstance(mapping, dict):
            last_err = (
                f"Reply missing required 'mapping' object key. "
                f"You returned {list(parsed)!r}. "
                f"Wrap your mapping inside {{\"mapping\": {{...}}}}."
            )
            messages.append({"role": "assistant", "content": content})
            messages.append({"role": "user", "content": last_err})
            continue

        # Schema validation
        cleaned: dict[str, str] = {}
        invalid_headers: list[str] = []
        invalid_fields: list[tuple[str, str]] = []
        for header, field in mapping.items():
            if header not in valid_headers:
                invalid_headers.append(header)
                continue
            if field not in valid_fields:
                invalid_fields.append((header, field))
                continue
            cleaned[header] = field

        if not cleaned and (invalid_headers or invalid_fields):
            # Whole proposal is garbage. Tell LLM what we expected.
            errs = []
            if invalid_headers:
                errs.append(f"unknown headers: {invalid_headers[:5]}")
            if invalid_fields:
                errs.append(
                    f"unknown logical_fields: "
                    f"{[f for _, f in invalid_fields[:5]]}"
                )
            last_err = (
                f"All proposed mappings were invalid: {'; '.join(errs)}. "
                f"Use ONLY headers from {sorted(valid_headers)[:8]}... "
                f"and ONLY logical_fields from {sorted(valid_fields)[:8]}..."
            )
            messages.append({"role": "assistant", "content": content})
            messages.append({"role": "user", "content": last_err})
            continue

        # Valid (possibly partial) mapping. Drop silently logged invalid
        # entries and accept what cleaned.
        if invalid_headers:
            logger.warning("llm.propose: dropped unknown headers %r",
                           invalid_headers[:5])
        if invalid_fields:
            logger.warning("llm.propose: dropped unknown fields %r",
                           [f for _, f in invalid_fields[:5]])
        return cleaned

    raise LLMProposalError(
        f"LLM returned invalid mapping after {cfg.max_retries + 1} attempts: "
        f"{last_err}"
    )


def usage_today_for_client(client_id: str) -> int:
    """How many LLM calls used by this client today. Surfaced in admin UI."""
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "select call_count from hub.llm_usage where date = current_date and client_id = %s",
                (client_id,),
            )
            row = cur.fetchone()
            return row[0] if row else 0


def list_models(cfg: LLMConfig | None = None) -> list[str]:
    """Fetch available models from the configured OpenAI-compat endpoint.

    Returns sorted list of model IDs, or empty list if the endpoint
    doesn't expose `GET /models` (some OpenAI-compat servers don't).

    Raises:
        LLMUnavailable — base_url or api_key not set.
        LLMProposalError — endpoint reachable but returned malformed list
                           or error.
    """
    cfg = cfg or LLMConfig.load()
    if not cfg.base_url or not cfg.api_key:
        raise LLMUnavailable("Base URL and API key required to list models")

    from openai import OpenAI

    client = OpenAI(
        base_url=cfg.base_url,
        api_key=cfg.api_key or "not-needed",
        timeout=cfg.timeout_s,
        max_retries=0,
    )
    try:
        page = client.models.list()
    except Exception as e:  # noqa: BLE001
        logger.exception("llm.list_models: API call raised")
        raise LLMProposalError(f"List models failed: {type(e).__name__}") from e

    ids = []
    for m in getattr(page, "data", []) or []:
        mid = getattr(m, "id", None)
        if mid:
            ids.append(str(mid))
    return sorted(set(ids))

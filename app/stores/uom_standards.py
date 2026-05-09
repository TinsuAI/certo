"""UoM standardization helpers — alias normalization + numeric conversion.

Backed by existing tables `hub.uom_canonical (uom_code, family, base_factor)`
and `hub.uom_aliases (alias_norm, uom_code)` from mig 021, extended by
mig 051. Caches lookup tables in-process.

Distinct from `app/stores/uom.py` (per-client UoM override stack for the
flatten engine). This module is the agency-wide canonical layer that
de-noises catalog `_uom_drift` warnings when distinct alias strings
mean the same canonical UoM (PCS == PIECE == ST).

Conversion model: each canonical has a `base_factor` relative to its
family base unit (e.g. KG=1, G=0.001, T=1000 in family 'mass').
Conversion from src→dst within same family: `value * (src.base_factor /
dst.base_factor)`. Cross-family conversions return None.
"""
from __future__ import annotations

import threading

from app.database import connect


_LOCK = threading.Lock()
_ALIAS_TO_CANONICAL: dict[str, str] | None = None
_CANONICAL_INFO: dict[str, tuple[str, float]] | None = None  # uom_code → (family, base_factor)


def _load_caches() -> None:
    global _ALIAS_TO_CANONICAL, _CANONICAL_INFO
    if _ALIAS_TO_CANONICAL is not None:
        return
    with _LOCK:
        if _ALIAS_TO_CANONICAL is not None:
            return
        with connect() as conn, conn.cursor() as cur:
            cur.execute(
                "select uom_code, family, base_factor from hub.uom_canonical"
            )
            cinfo = {c: (f, float(bf)) for c, f, bf in cur.fetchall()}
            cur.execute("select alias_norm, uom_code from hub.uom_aliases")
            a2c = {a: c for a, c in cur.fetchall()}
        _CANONICAL_INFO = cinfo
        _ALIAS_TO_CANONICAL = a2c


def clear_cache() -> None:
    """Drop the alias/conversion cache. Tests that mutate uom_* tables
    should call this between assertions."""
    global _ALIAS_TO_CANONICAL, _CANONICAL_INFO
    with _LOCK:
        _ALIAS_TO_CANONICAL = None
        _CANONICAL_INFO = None


def _normalize(value: str | None) -> str | None:
    """Lowercase + strip + collapse internal whitespace. Matches the
    schema convention: aliases stored as lowercase trimmed.
    """
    if value is None:
        return None
    s = str(value).strip().lower()
    return s or None


def resolve_canonical(uom: str | None) -> str | None:
    """Resolve a UoM alias (any case, any whitespace) to its canonical
    code (lowercase). Returns None for unknown aliases."""
    norm = _normalize(uom)
    if norm is None:
        return None
    _load_caches()
    return _ALIAS_TO_CANONICAL.get(norm)


def dimension_of(uom: str | None) -> str | None:
    """Return family name ('count'/'mass'/'length'/'volume'/...) for a
    UoM, via canonical lookup. None for unknown."""
    canonical = resolve_canonical(uom)
    if canonical is None:
        return None
    _load_caches()
    info = _CANONICAL_INFO.get(canonical)
    return info[0] if info else None


def convert(value: float, from_uom: str | None,
            to_uom: str | None) -> float | None:
    """Convert numeric value between UoMs. Returns None when:
      - either UoM is unknown
      - they belong to different families
    Same canonical (synonyms) → factor 1.
    """
    src = resolve_canonical(from_uom)
    dst = resolve_canonical(to_uom)
    if src is None or dst is None:
        return None
    if src == dst:
        return float(value)
    _load_caches()
    sinfo = _CANONICAL_INFO.get(src)
    dinfo = _CANONICAL_INFO.get(dst)
    if not sinfo or not dinfo:
        return None
    if sinfo[0] != dinfo[0]:  # different family
        return None
    # value (in src units) → base units → dst units
    base_value = value * sinfo[1]
    return base_value / dinfo[1]


VALID_FAMILIES = {
    "count", "count_packaging", "mass", "length", "volume", "area",
    "volume3", "assembly", "time", "energy", "other",
}


def list_canonicals_with_alias_count() -> list[dict]:
    """For admin view: each canonical + count of aliases pointing to it."""
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            """
            select c.uom_code, c.family, c.base_factor,
                   coalesce(a.n_aliases, 0) as n_aliases
              from hub.uom_canonical c
              left join (
                select uom_code, count(*) as n_aliases
                  from hub.uom_aliases group by uom_code
              ) a on a.uom_code = c.uom_code
             order by c.family, c.uom_code
            """
        )
        cols = [d[0] for d in cur.description]
        return [dict(zip(cols, r)) for r in cur.fetchall()]


def list_aliases() -> list[dict]:
    """All aliases sorted by canonical, then alias."""
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            "select alias_norm, uom_code from hub.uom_aliases "
            "order by uom_code, alias_norm"
        )
        return [{"alias_norm": a, "uom_code": c} for a, c in cur.fetchall()]


class UomStandardsError(ValueError):
    pass


def create_canonical(*, uom_code: str, family: str, base_factor: float) -> None:
    code = (uom_code or "").strip().lower()
    if not code:
        raise UomStandardsError("uom_code required")
    if family not in VALID_FAMILIES:
        raise UomStandardsError(
            f"invalid family: {family!r}; must be one of {sorted(VALID_FAMILIES)}"
        )
    try:
        bf = float(base_factor)
    except (TypeError, ValueError) as e:
        raise UomStandardsError(f"invalid base_factor: {base_factor!r}") from e
    if bf <= 0:
        raise UomStandardsError("base_factor must be > 0")
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            "insert into hub.uom_canonical (uom_code, family, base_factor) "
            "values (%s, %s, %s) on conflict (uom_code) do nothing",
            (code, family, bf),
        )
        # Self-alias so resolve_canonical(uom_code) returns it
        cur.execute(
            "insert into hub.uom_aliases (alias_norm, uom_code) "
            "values (%s, %s) on conflict do nothing",
            (code, code),
        )
    clear_cache()


def create_alias(*, alias_norm: str, uom_code: str) -> None:
    alias = (alias_norm or "").strip().lower()
    code = (uom_code or "").strip().lower()
    if not alias:
        raise UomStandardsError("alias_norm required")
    if not code:
        raise UomStandardsError("uom_code required")
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            "select 1 from hub.uom_canonical where uom_code=%s", (code,),
        )
        if cur.fetchone() is None:
            raise UomStandardsError(f"unknown uom_code: {code!r}")
        cur.execute(
            "insert into hub.uom_aliases (alias_norm, uom_code) "
            "values (%s, %s) on conflict (alias_norm) do update set uom_code=excluded.uom_code",
            (alias, code),
        )
    clear_cache()


def delete_alias(alias_norm: str) -> None:
    alias = (alias_norm or "").strip().lower()
    if not alias:
        raise UomStandardsError("alias_norm required")
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            "delete from hub.uom_aliases where alias_norm=%s", (alias,),
        )
    clear_cache()


def are_equivalent(a: str | None, b: str | None) -> bool:
    """Two UoMs are equivalent iff they map to the same canonical code.
    For unknown aliases, fall back to raw normalized comparison so that
    novel UoMs (not covered by seed) still don't false-positive drift
    if they're literally the same string."""
    ca = resolve_canonical(a)
    cb = resolve_canonical(b)
    if ca is not None and cb is not None:
        return ca == cb
    return _normalize(a) == _normalize(b)

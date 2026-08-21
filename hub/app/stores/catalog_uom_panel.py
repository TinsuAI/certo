"""A.4.4 — catalog detail UoM panel builder.

Annotates each observed UoM chip (BCCT declarations + BOM edges where the
material is a component) with a convertibility `state` from
`classify_uom_relation`, against the catalog's official `materials.uom`.
Replaces the old binary `are_equivalent` cue that over-flagged every
non-same-canonical unit as "lệch".

States (UI renders one of four chip shades):
  equivalent   — same canonical; no marking.
  convertible  — converts cleanly via a confirmed factor; "quy đổi ×N".
  unconfirmed  — tier-A 1:1 assumption; amber "cần xác nhận".
  incompatible — no factor; warn, link to add a factor or alias.
"""
from __future__ import annotations


def _state_of(rel) -> str:
    if rel.relation == "equivalent":
        return "equivalent"
    if rel.relation == "convertible":
        return "convertible" if rel.confirmed else "unconfirmed"
    return "incompatible"


def build_uom_panel(*, client_id: str, material_code: str,
                    official: str | None,
                    uom_bcct: list[dict], uom_bom: list[dict]) -> dict:
    """Annotate each chip in-place with state/factor/remediation and return
    the panel dict consumed by `clients/catalog_detail.html`."""
    from app.stores.uom import classify_uom_relation

    def annotate(token: str | None) -> dict:
        if not official:
            # No official UoM to compare against → nothing diverges.
            return {"state": "equivalent", "factor": None,
                    "remediation": None, "confirmed": True}
        rel = classify_uom_relation(
            token, official, client_id=client_id, material_code=material_code,
        )
        return {
            "state": _state_of(rel),
            "factor": str(rel.factor) if rel.factor is not None else None,
            "remediation": rel.remediation,
            "confirmed": rel.confirmed,
        }

    for o in uom_bcct:
        o.update(annotate(o.get("unit")))
    for o in uom_bom:
        o.update(annotate(o.get("uom")))

    chips = uom_bcct + uom_bom
    return {
        "official": official,
        "bcct": uom_bcct,
        "bom": uom_bom,
        # Any non-equivalent chip → show the chip-divergence section.
        "has_divergence": any(o["state"] != "equivalent" for o in chips),
        # Only unconfirmed/incompatible chips actually need staff action
        # (a factor or an alias) — drives the call-to-action banner.
        "needs_attention": any(
            o["state"] in ("unconfirmed", "incompatible") for o in chips),
    }

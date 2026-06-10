from __future__ import annotations

# Data Hub (mig 078+) classifies every material with customs_relevance. CO trusts
# that classification and keeps NO client-specific heuristic: a material Data Hub
# does not classify (null / review / field absent) is KEPT, never silently dropped
# (per the DH spec). Fixing a misclassification is a DH-side map edit
# (hub.client_material_group_map), not CO code. See
# .ai/sister-app-notes/2026-06-09-co-consumer-spec-declarability.md.
_EXPORT_EXCLUDE = {"excluded_non_material", "declarable_unmatched"}


def is_bom_technical_noise(material: dict) -> bool:
    """True iff Data Hub classifies the material as non-emittable on a C/O export:
    rác (``excluded_non_material``) or real-but-unmatched (``declarable_unmatched``).
    Anything unclassified (``null`` / ``review`` / field absent) → False (kept)."""
    return str(material.get("customs_relevance") or "").strip() in _EXPORT_EXCLUDE


def is_declarable_unmatched(material: dict) -> bool:
    """Real, declarable-class material with no BCCT import match — export-excluded
    but surfaced as a reconciliation REVIEW queue, never lumped into rác."""
    return str(material.get("customs_relevance") or "").strip() == "declarable_unmatched"

"""Dataclasses for the flatten layer. Pure data — no behavior.

All status / strategy / reason / evidence fields use the stable English
machine codes from migration 021's CHECK constraints (spec §3B). UI
translation happens elsewhere.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Callable, Literal, Sequence

# ── Domain enums (mirror migration 021 CHECK constraints) ──────────────

SourceBomKind = Literal[
    "manual_flat", "technical_raw", "technical_flattened",
    "technical_non_flattened", "co_modified", "staff_edit",
]
FlattenStatus = Literal["flattened", "non_flattened", "not_applicable"]
FlattenStrategy = Literal[
    "manual_flat_as_provided", "technical_exploded",
    "purchased_btp_as_leaf", "self_produced_btp_exploded",
    "mixed_confirmed", "no_strategy",
]
SourceChannel = Literal[
    "agency_upload", "staff_form", "co_proposal", "migration", "seed",
]
UnresolvedReason = Literal[
    "uom_conversion_missing", "uom_conversion_ambiguous", "missing_child_bom",
    "cycle_detected", "ambiguous_dual_source", "classification_unknown",
    "canonical_uom_missing",
]
DecisionType = Literal[
    "dual_source_variant", "non_flattened_publish", "bcct_import_vs_child_bom",
    "use_db_btp_no_same_upload", "choose_btp_variant",
    "non_alias_uom_conversion", "global_uom_conversion",
    "catalog_canonical_uom_missing", "generic_bcct_evidence",
    "material_change_significant", "duplicate_source_rows",
]
DecisionStatus = Literal["pending", "confirmed", "rejected", "auto"]
ClassificationEvidence = Literal[
    "bcct_import", "child_bom_same_upload", "child_bom_current_db",
    "catalog_imported_nvl", "explicit_self_produced", "explicit_purchased",
    "unresolved_missing_child_bom", "ambiguous_dual_source",
]
ConversionMatchSource = Literal[
    "client_specific", "client_wide", "global", "alias",
]


# ── Inputs ─────────────────────────────────────────────────────────────

ParsedRow = dict        # raw {material_code, qty_per_unit, uom, bom_code, bom_variant_id, ...}
ParsedBom = dict[str, list[ParsedRow]]  # graph-key → rows


@dataclass(frozen=True)
class BomKey:
    """Graph identity (spec §3). bom_variant_id defaults to 'default'."""
    product_code: str
    bom_code: str = ""
    bom_variant_id: str = "default"

    def as_tuple(self) -> tuple[str, str, str]:
        return (self.product_code, self.bom_code or "", self.bom_variant_id or "default")


@dataclass(frozen=True)
class CatalogEntry:
    material_code: str
    category: str | None      # 'nvl'|'btp_sx'|'btp_nm'|'tp'|'ccdc'
    status: str | None        # 'active'|'discontinued'
    uom: str | None           # canonical UOM per material (post-mig-063)


@dataclass(frozen=True)
class ConversionMatch:
    factor: Decimal
    from_uom: str             # alias as provided
    to_uom: str               # canonical
    source: ConversionMatchSource

    def as_evidence(self) -> dict:
        return {
            "factor": str(self.factor),
            "from_uom": self.from_uom,
            "to_uom": self.to_uom,
            "source": self.source,
        }


# ── Lookup callables (DB-side wrappers inject these) ──────────────────

CatalogLookup = Callable[[str], CatalogEntry | None]
BcctImportLookup = Callable[[str], bool]
SameUploadBtpLookup = Callable[[str, str, str], list[ParsedRow] | None]  # (mat, bom_code, variant)
CurrentDbBtpLookup = Callable[[str, str, str], list[ParsedRow] | None]
UomLookup = Callable[[str, str | None, str | None], ConversionMatch | None]  # (material_code, from, to)
ExplicitContextLookup = Callable[[ParsedRow], str | None]   # returns 'purchased'|'self_produced'|None


@dataclass(frozen=True)
class FlattenContext:
    client_id: str
    catalog: CatalogLookup
    bcct_import: BcctImportLookup
    same_upload_btp: SameUploadBtpLookup
    current_db_btp: CurrentDbBtpLookup
    uom: UomLookup
    explicit_context: ExplicitContextLookup = field(
        default=lambda r: r.get("explicit_context")
    )
    flatten_method: str = "dh_flatten_v1"
    flatten_method_version: str = "0.1.0"


# ── Outputs ────────────────────────────────────────────────────────────

@dataclass
class FlattenedRow:
    material_code: str
    qty: Decimal              # cumulative through graph multiplications
    uom: str                  # canonical UOM after conversion
    node_path: str            # e.g. 'TP-A>BTP-B>X'
    classification_evidence: ClassificationEvidence
    classification_evidence_detail: dict = field(default_factory=dict)
    conversion_evidence: dict | None = None    # ConversionMatch.as_evidence() per hop applied
    original_qty: Decimal | None = None
    original_uom: str | None = None
    # SAP item-type provenance (carried through to payload; drives the
    # derived item_category / customs_relevance — see migration 078).
    material_group: str | None = None
    phantom: bool = False
    bulk: bool = False


@dataclass
class UnresolvedNode:
    node_path: str
    material_code: str
    reason: UnresolvedReason
    evidence: dict = field(default_factory=dict)


@dataclass
class Decision:
    decision_type: DecisionType
    chosen_action: str
    alternatives: list[dict] = field(default_factory=list)
    evidence: dict = field(default_factory=dict)
    status: DecisionStatus = "pending"
    staff_confirmation_required: bool = True
    # Bound to a specific candidate version when relevant; resolved at
    # materialization time.
    target_key: BomKey | None = None
    target_strategy: FlattenStrategy | None = None


@dataclass
class FlattenedVersion:
    """A draft version about to be materialized. The stores layer assigns
    artifact_id, artifact_no, parent_artifact_id, etc."""
    key: BomKey
    source_bom_kind: SourceBomKind
    flatten_status: FlattenStatus
    flatten_strategy: FlattenStrategy
    rows: list[FlattenedRow]
    unresolved: list[UnresolvedNode] = field(default_factory=list)
    lineage: dict = field(default_factory=dict)   # {btp_versions_used:[…]}
    requires_decision_ids: list[str] = field(default_factory=list)


@dataclass
class FlattenResult:
    versions: list[FlattenedVersion]
    decisions: list[Decision]

    def by_key(self, key: BomKey) -> list[FlattenedVersion]:
        return [v for v in self.versions if v.key.as_tuple() == key.as_tuple()]


@dataclass(frozen=True)
class ClassificationResult:
    """Per-component decision result. dual_source=True means BOTH purchased
    leaf AND self-produced explosion are valid; engine emits two variants."""
    action: Literal["leaf", "explode", "unresolved"]
    evidence: ClassificationEvidence
    detail: dict = field(default_factory=dict)
    dual_source: bool = False
    explicit: bool = False

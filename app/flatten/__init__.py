"""Technical BOM flattening — pure functions, no DB I/O.

Public surface:
- flatten(parsed, ctx) -> FlattenResult — orchestrator
- types: FlattenResult, FlattenedRow, UnresolvedNode, Decision, FlattenContext

DB-side wrappers live in app/stores/uom.py + app/stores/bom.py +
app/stores/flatten_decisions.py — they build the lookups that this
module consumes and materialize the FlattenResult into bom_artifacts /
bom_unresolved_nodes / bom_flatten_decisions.

Method identity:
  flatten_method         = 'dh_flatten_v1'
  flatten_method_version = '0.1.0'
"""
from __future__ import annotations

from app.flatten.engine import flatten
from app.flatten.types import (
    BomKey, CatalogEntry, ClassificationResult, ConversionMatch, Decision,
    FlattenContext, FlattenResult, FlattenedRow, FlattenedVersion,
    ParsedBom, ParsedRow, UnresolvedNode,
)
from app.flatten.identity import build_display_label

FLATTEN_METHOD = "dh_flatten_v1"
FLATTEN_METHOD_VERSION = "0.1.0"

__all__ = [
    "flatten",
    "BomKey", "CatalogEntry", "ClassificationResult", "ConversionMatch",
    "Decision", "FlattenContext", "FlattenResult", "FlattenedRow",
    "FlattenedVersion", "ParsedBom", "ParsedRow", "UnresolvedNode",
    "build_display_label",
    "FLATTEN_METHOD", "FLATTEN_METHOD_VERSION",
]

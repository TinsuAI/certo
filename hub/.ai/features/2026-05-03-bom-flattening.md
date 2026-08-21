# Feature: Data Hub BOM Flattening

**Date:** 2026-05-03
**Driver:** CO-side prompt at `~/workspace/client/barry-CO-main/.ai/features/2026-05-02-data-hub-bom-flattening-instructions.md`
**Plan file (canonical):** `~/.claude/plans/hazy-cooking-parnas.md`

## Why

Data Hub stores BOM versions as parsed rows only — no graph, no UOM normalization, no classification, no cycle detection, no dual-source variant model. CO will migrate to consume Data Hub BOM; before that happens, hub must own a calculation-ready flattened BOM with provenance + staff-confirmation gates so consumers can never silently get a non-flattened or wrong-strategy variant.

## Scope

- New upload profile `technical_flatten` that explodes technical BOM through child-BOMs / BCCT-import evidence / catalog leaf rules.
- TP and BTP both stored as first-class versions with structured identity (`source_bom_kind`, `flatten_status`, `flatten_strategy`, `lineage`, `display_label`).
- UOM canonical + alias + global conversion + per-client override, with conversion precedence per spec §9.
- Staff-confirmation gates for every business-decision class: dual-source choice, non_flattened publish, BCCT-import-vs-child-BOM tie-break, non-alias UOM conversion, etc.
- API `/v1/hub/products/{p}/bom/latest` hardened: filters `flatten_status`, returns 409 with variant list when dual-source variants are published.
- `manual_flat` / `growatt_multi_workbook` / `johnson_sap_exploded` paths preserved (backfill `flatten_status='not_applicable'`).

## Out of scope

CO migration. Direct CO writes to `hub` schema. Public API beyond the `latest` hardening + new response fields.

## Slicing

See plan file `~/.claude/plans/hazy-cooking-parnas.md` for the six commit-shaped slices and their critical files. Tests-first per slice.

## Acceptance

Spec §"Acceptance Criteria" must hold. 28 test items from spec §"Tests First" must each have at least one corresponding test asserting English machine codes (never Vietnamese UI labels).

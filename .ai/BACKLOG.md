# Backlog

Ideas captured but not yet planned. Each item should grow into a feature
brief (`.ai/features/YYYY-MM-DD-<slug>.md`) before being built.

For *current* in-flight state and immediate next steps, see `STATUS.md`.
For past architectural decisions, see `DECISIONS.md`.

---

## File-upload UX

### Pre-commit preview at appropriate upload stages
**Captured 2026-05-04.**

Today the upload flow is one-shot: user picks file, hub parses + ingests
in the same request. They only see the result after the fact (or a
confirm-gate preview if rows would CHANGE). For *first-time* uploads to a
fresh tab — Catalog, BQD, BOM — there's no preview at all. If the file is
malformed or the wrong shape entirely, hub either errors or ingests
silently.

Pattern proposed:
- Stage 1: upload file → parse → render preview (first ~20 rows, column
  mapping echoed back) → user confirms.
- Stage 2: confirm → ingest.

Already half-done for BCCT via the parser-mapping flow (when rigid
parsing fails), but valuable to extend to all four upload types so users
*always* see what hub interpreted before commit. May share template +
state with the existing `upload_pending` table.

Cross-cuts with: confirm-on-update gate (already shipped for BCCT, not
yet for catalog/bqd/bom).

---

## Catalog (Danh Mục) sources + provenance tracking

### Multi-source catalog with HQ-registration provenance
**Captured 2026-05-04.**

Catalog can be populated from 4 sources, each with different trust:

| Source | Provenance | Trust |
|---|---|---|
| DS NVL ĐK HQ | Registered with customs — agency declared this code | **Highest** — canonical |
| DS SP ĐK HQ | Same, for products | **Highest** |
| Auto-derived from BCCT (unique customs_codes from declarations) | Codes that appeared on declarations but may not be HQ-registered yet | Medium — operational reality |
| User-uploaded ad-hoc file | Free-form list | Lowest |

Reality: **codes appear on BCCT declarations even when not yet
registered with HQ** — they get rejected/queried later but show up in
the data. Auto-derive from BCCT will produce a superset of registered
codes; the *interesting* set is the diff between
"registered" and "appeared on a declaration but not registered".

Catalog should:
- Track per-row provenance (`registered_with_hq: bool`, `seen_in_bcct: bool`,
  `seen_in_user_upload: bool`).
- Render visual badge on catalog rows: ✓ registered / ⚠ unregistered but
  on declaration / 📥 user-added.
- Allow filtering by provenance.
- Surface "X codes appear on BCCT but aren't registered" as an audit
  alarm somewhere.

Schema sketch: extend `hub.materials` with `provenance jsonb` carrying
per-source first-seen dates + counts. Don't replace; auto-derive runs
nightly (or on-BCCT-upload) and merges into existing rows.

### Auto-derive catalog from BCCT
**Captured 2026-05-04, related to above.**

Job: scan `hub.bcct_rows` for distinct `customs_code` per client, upsert
into `hub.materials` with `provenance.seen_in_bcct = true`. Run on every
BCCT upload (or as a nightly cron). Hub shouldn't be the system of
record for these — they're just "spotted in declarations" — but having
them visible in the catalog UI helps staff notice missing registrations.

---

## BCCT tab — staleness metadata

### Show last-update + data-recency on BCCT tab
**Captured 2026-05-04.**

When staff opens the BCCT tab, they should see at a glance:
- "Last upload: 2 days ago (2026-04-30)"
- "Most recent declaration in DB: 2026-04-15 — data is 17 days old"

These two are different signals:
- Upload recency = how often is staff feeding the system?
- Declaration recency = how stale is the actual customs data, regardless
  of upload cadence?

A 30-day-old declaration on a pile that was uploaded yesterday means
"staff is on top of the upload, but no new declarations have been
processed in a month" — a different operational concern than "we haven't
been uploading for a month."

Surface as a status bar at the top of `/clients/{id}/bcct`:

```
┌─────────────────────────────────────────────────────────────┐
│ Lần upload cuối: 2 ngày trước (2026-04-30 14:23)            │
│ Tờ khai gần nhất: 2026-04-15 (17 ngày trước)                │
└─────────────────────────────────────────────────────────────┘
```

Same idea applicable to Catalog, BQD, BOM tabs.

Cheap to implement: two `MAX()` queries on `file_uploads.parsed_at` and
`bcct_rows.registration_date` per client. Cache for ~1 minute if
needed.

---

## Cross-cut from /rev (still open)

- **Cache `use_count` overcounts** when cached mapping fails parse and
  fallback to rigid happens (`_lookup_cached_mapping` increments before
  we know the parse succeeded).
- **`Path(stored_path).read_bytes()`** in `parse_mapping_confirm` has no
  FileNotFoundError handling — 500s if blob missing.
- **Migration numbering gap** (010 → 012, no 011).
- **CSRF protection** on POST endpoints (pre-existing project gap).
- **`set_config('app.user_id', ..., false)`** — switch to `true` (LOCAL)
  if connection pooling lands.

## Cross-cut from prior /rev (Stage A+B/D/C1/C2)

- Apply confirm-gate pattern to catalog/bqd/bom uploads (currently only
  BCCT has the pre-flight diff).
- Manual mapping UI when LLM is disabled (today: upload errors with
  no recourse besides edit-in-DB).

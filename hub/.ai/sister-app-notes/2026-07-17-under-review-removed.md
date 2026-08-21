# Adoption guide — `under_review` removed from materials.status

**Released:** 2026-07-17
**Issue:** `TinsuAI/data-hub#49`
**Migration:** `094_drop_under_review_material_status.sql`
**ADR:** `docs/adr/0001-catalog-discovery-is-a-view-not-a-table.md` (this
executes the alternative that ADR rejected)
**Context:** No action required by CO or BCQT. This note exists because
`2026-05-09-catalog-multi-source-and-vocab.md` instructed you to branch on a
value that no longer exists — see "Amends" below.

---

## What changed

`hub.materials.status` no longer admits `under_review`. Legal values are now
`active | deprecated | tombstoned | inactive`, enforced by a CHECK constraint
(mig 094). The one row holding it was flipped to `active` before the constraint
was added.

Accepting a candidate on the "Mã chờ duyệt" page now lands `active`. It
previously landed `under_review`, while the bulk-approve button beside it
landed `active` — the two disagreed. Worse, a code auto-ingested from BCCT with
no review at all landed `active`, so the *unreviewed* path produced the more
trusted state. Approval is `source` promotion plus the candidates queue; status
was never the approval gate.

## Amends `2026-05-09-catalog-multi-source-and-vocab.md`

That note's section **`resolution_status='resolved_pending_review'`** (lines
122-126) told you:

> When the resolver hits a `bcct_observed/under_review` material … it returns
> `resolution_status='resolved_pending_review'` instead of `'resolved'`.

**That value is gone.** The BCCT material-identity payload now returns
`resolution_status='resolved'` for every resolved material. Nothing can produce
`resolved_pending_review`, because nothing can be `under_review`.

## Do you need to change anything?

**No.** Verified by grep at time of writing:

- **CO** — zero `under_review` hits. One reference to the removed value, at
  `app/data_hub_client.py:1118`:
  ```python
  if identity.get("resolution_status") not in ("resolved", "resolved_pending_review"):
  ```
  This keeps working unchanged — the removed element simply stops matching. It
  is now dead and can be dropped next time that file is touched. No rush.
- **BCQT** — zero hits for either `under_review` or `resolved_pending_review`.
  No consumer exists.

## API surface

`GET /v1/hub/materials` and `/v1/hub/materials/{customs_code}` are unchanged in
shape. The alive-only default (`status not in ('tombstoned','inactive')`) is
unchanged in meaning. `?status=under_review` now matches zero rows rather than
erroring. Response bytes for every live row are identical — all are `active`.

Filed `Cosmetic` in `docs/API_CHANGELOG.md` (2026-07-17), not `Breaking`: no
sister app must update code.

## Also removed

The `promote_material` route (`POST /clients/{cid}/catalog/{code}/promote`) and
its UI. It was the only exit from `under_review` and 404'd on every call once
zero rows held that status. The `materials.promoted_to_declared_at` /
`promoted_by` columns are **retained** (3 dev-era rows still carry values) but
are no longer read or displayed.

`POST /clients/{cid}/catalog/{code}/edit` now rejects `under_review` with 400
instead of raising a CheckViolation.

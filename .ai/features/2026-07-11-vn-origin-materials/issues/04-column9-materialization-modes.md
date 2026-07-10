# 04 — Column (9)/(12)/(13) materialization: modes, normalization, unknown label

Status: ready-for-agent — tracked on GitHub: [TinsuAI/co#9](https://github.com/TinsuAI/co/issues/9) (tracker of record)

## Parent

`.ai/features/2026-07-11-vn-origin-materials/spec.md` (build-order ticket 4).

## What to build

Column (9) fills itself per the client's filing convention. Two modes: `country`
(Vietnamese country display name; default) and `qualification_label`
("Việt Nam"/"Không xuất xứ"). One resolver function owns the precedence
(client-config default + per-case override — the per-case *control surface* ships in
ticket 05, but the resolver accepts it now). The mode is read once per Tính and the
resulting text is materialized onto each row as `bang_ke_origin_text`, with the
resolved mode stamped on the product and the (12)/(13) text fields materialized into
the snapshot (content stays blank until ticket 07). All three export renderers and
the web-grid cell become pure readers of the materialized text — export == web holds
by construction.

Country names come from a new code-owned normalization module (raw BCCT string → ISO
→ Vietnamese display name, seeded from the observed BCCT vocabulary). Lots in the
unknown bucket (UNKNOWN / KHONG XAC DINH / blank) render the new free-text
client-config label `bang_ke.unknown_origin_label` (default "Không xác định"). A
real-but-unmapped country string renders raw with a non-blocking warning — never a
block. A read-only UI view shows the mapping plus the client's own unmapped strings.

## Acceptance criteria

- [ ] Normalization module with raw→ISO and ISO→Vietnamese tables, unit-tested
      directly; git-versioned, not admin-editable.
- [ ] `column9_text(mode, origin_status, country_label_vi)` is pure and never touches
      `origin_status`.
- [ ] Same case calculated in both modes → identical column (7)/(8) money totals and
      LVC (regression test).
- [ ] `bang_ke_origin_text` + (12)/(13) text fields materialized per row at Tính;
      resolved mode stamped per product; renderers and web cell read only
      materialized fields (no renderer reads config).
- [ ] Export == web parity test across all three export formats.
- [ ] `bang_ke.unknown_origin_label` free-text field on the client-config form;
      default "Không xác định" when empty; applies to the unknown bucket only.
- [ ] Unmapped-but-real country string renders raw + non-blocking material warning;
      lock and export never block on a display-vocabulary gap.
- [ ] Country mode: one line with CHINA and TAIWAN lots splits into two rows via the
      ticket 02 machinery; qualification mode: the same line renders one row.
- [ ] Read-only normalization view (mapping + client's unmapped origin strings).
- [ ] Legacy persisted sheets render blank column (9) until re-Tính (materialized →
      legacy field → empty fallback); config migration auto-adds the new defaults.

## Blocked by

- 01 — Plumb lot origin fields into sheet materials at Tính
- 02 — Override identity re-key + render-split fan-out machinery

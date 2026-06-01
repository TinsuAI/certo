# Session 2026-06-01 — Substitute fuzzy multi-field search (client feedback #5)

## What Was Done

Implemented client feedback **#5** ("muốn nhiều bộ lọc cùng lúc — mã + tên") as fuzzy
multi-field search in the substitute NVL modal. Shipped via **PR #1 → squash-merge `04ce3ca`
→ CI/CD green → deployed** (Deploy demo: Deploy on tinsu + Refresh nightly stack OK).

- **`app/material_search.py`** (new): shared matcher.
  - `fold_text`: casefold + strip Vietnamese diacritics (NFD + đ→d).
  - `match_score(query, fields)`: tokenize query on whitespace; every token must match at
    least one field (AND across tokens, OR across fields). Tiered: exact (4) > prefix (3) >
    substring (1.5) > subsequence (0.6). First fields (code) weighted slightly higher.
    Returns None to exclude a row.
  - `rank_matches(query, rows, fields_of, limit)`: filter + sort best-first, stable.
  - **Subsequence gated two ways:** `_subseq_eligible` (field has no space and len ≤24 →
    codes/HS only, not long descriptions) AND `_token_allows_subseq` (token has a letter and
    len ≥3 → alpha typos like `bientn`, never numeric tokens).
- **Server wiring:** `PortfolioService.search_materials` (file-store), `DataHubPortfolioService.search_materials`
  (DH catalog), and `search_case_material_rows` (`main.py`) all use the matcher now.
- **`co_case.html`:** live client-side "Lọc nhanh" filter on the Khuyến nghị tab (JS mirror
  of the server matcher: foldText / isSubsequence / subseqEligible / tokenAllowsSubseq /
  matchesTokens; filters visible `<li>` by mã+tên+HS, shows a "không khớp" message, cleared
  on modal open). Multi-token hint added to the Tìm kiếm placeholder. CSS for the filter.
- **Tests:** 7 `material_search` unit cases in `tests/test_co_demo.py`. Full suite **411
  passed + 8 skipped**.

## Decisions Made

- **Surface = substitute modal, not the data tables.** The original #5 plan proposed a
  `kind:"text"` filter on the shared table component. I started there, but discovered
  catalog/BOM tables are **DH-delegated in demo mode** (render on Data Hub, not in CO), so
  that work wouldn't show on the demo. The client then clarified they meant the substitute
  modal search. Reverted the table-component work, re-targeted to the modal.
- **"Fuzzy" = token-AND multi-field + accent-fold + tiered partial, ranked** — not Levenshtein.
  Subsequence gives the typo/abbreviation tolerance; substring/prefix/exact rank above it.
- **Two false-positives caught during verification and fixed at the root** (see below). This
  is why iterative multi-scenario testing mattered — the user pushed for it.
- **CO-side only, no Data Hub contract change.** All matching is on the already-cached
  materials catalog / case rows; no new DH endpoint.
- **Branch-first then PR then squash-merge** (vs prior sessions' direct-to-main). PR #1 is
  the first PR on `tinsu` (TinsuAI/co).

## What Didn't Work

- **Subsequence on long descriptions scatter-matched.** First gate attempt allowed
  subsequence on any short field; `aptomat tep` pulled an unrelated IC (`007.0061200`)
  because "aptomat" appears as a subsequence across its long Vietnamese description.
  Fix: `_subseq_eligible` restricts subsequence to space-free fields ≤24 chars.
- **Numeric tokens still scatter-matched HS codes.** `bientan 5000` returned 14 rows incl.
  ones with no "5000" — because "5000" is a subsequence of HS `85044090` (8,**5**,0,4,4,**0**,9,**0**).
  Fix: `_token_allows_subseq` — only alphabetic tokens ≥3 chars may match by subsequence; a
  numeric token must hit a real digit run. After fix: `bientan 5000` → exactly
  BIENTAN.18/20/31, `bientan 6000` → BIENTAN.19/25, `aptomat tep` → AP3 only.
- **Initial table-component implementation was wasted** (reverted) — see decision above.

## Open Items

- **#5 docs not yet committed at handoff time** — `.ai/STATUS.md` change is in the working
  tree (uncommitted) along with this session file. Commit the docs to `main` if desired.
- Remaining client feedback batch 1 (all need client input): **#2** confirm "mở" feels fast;
  **#4** substitute ranking quality → file DH API request (needs 3-5 bad-example codes from
  client); **#6** bulk multi-select delete (needs which table). See STATUS Next Steps.
- **Perf watch:** `search_materials` now scans the full catalog (Johnson ~65k) + NFD-folds
  each field to rank globally, vs the old early-break. It's an Enter-triggered action so
  acceptable, but if a large client reports slow substitute search, cache folded fields or
  cap the scan.
- Live filter uses the same fold/subsequence logic client-side; kept in sync manually with
  the Python matcher — if one changes, change both.

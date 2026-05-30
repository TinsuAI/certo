# Feature: Nightly / demo stack for Data Hub + CO

Discovery 2026-05-29. A second, isolated instance of **both** apps on the
existing demo VPS (`100.84.189.87`), for nightly builds + demos to new
customers. New repo `tinsu-deploy` orchestrates it. Brief lives here for now;
copy into `tinsu-deploy` when the repo is created.

## Scope

**In:**
- New repo `tinsu-deploy` with one `docker-compose.nightly.yml` defining 4
  services — `dh-db`, `dh-app`, `co-db`, `co-app` — on a shared docker network,
  `COMPOSE_PROJECT_NAME=nightly`, isolated host ports / volumes / DB names.
- App images built from each repo's `main` (build context `../data-hub`,
  `../co` checked out on the box — reuses their existing `build: .` Dockerfiles).
- Nightly job: `git pull` both → `compose up -d --build` → snapshot prod DBs +
  files into the nightly volumes → restart nightly apps (their migrations run
  forward on the snapshot = migration canary) → mint/refresh the nightly
  service token.
- On-merge trigger: when either app's `main` deploys to prod (existing
  self-hosted runner), also rebuild that app in the nightly stack.
- Env templates wiring CO-nightly → DH-nightly with consistent issuer config.

**Explicitly OUT:**
- No data masking / anonymization (see risk acceptance below).
- No new VPS — same box, isolated.
- No change to the prod stacks' compose (the deploy repo has its own compose;
  prod `/home/tinsu/data-hub` + `/home/tinsu/co` untouched).
- No public DNS/TLS in v1 — reachable at `http://100.84.189.87:<port>` over
  Tailscale (can add a hostname later).

## Decisions

- **Dedicated deploy repo** — composition of "both apps + which versions + which
  data + which ports" is a cross-app concern owned by neither app repo.
- **Reuse app images, separate compose** — both apps' compose is already fully
  env-parameterized, so nightly needs no compose duplication inside the app
  repos; the deploy repo's compose sets ports/volumes/db/env.
- **Isolation:** `COMPOSE_PROJECT_NAME=nightly`; host ports DH `8764`, CO `8765`
  (containers stay on internal 8754/8755); volumes `nightly_*`; DB names reused
  but in separate container/volume → zero overlap with prod.
- **CO→DH wiring (issuer gotcha):** CO `DATA_HUB_API_BASE_URL` + `DATA_HUB_JWKS_URL`
  point at the **internal** network name (`http://dh-app:8754`) for fast s2s
  calls; CO `DATA_HUB_ISSUER_URL` **must equal** DH-nightly `sso_issuer_url`
  (browser-facing external URL `http://100.84.189.87:8764`) so the JWT `iss`
  check + SSO redirect both work. Set `sso_issuer_url` on nightly-DH explicitly.
- **Service token is nightly-local:** the prod snapshot copies prod's
  `service_accounts` rows, but those tokens were signed by **prod keys + prod
  issuer** → invalid on nightly. Nightly-DH has its own keys; mint a fresh
  nightly service token (via the new admin UI, 1y) and set it as CO-nightly's
  `DATA_HUB_SERVICE_TOKEN`. (Also fix the `DATA_HUB_API_TOKEN` → `DATA_HUB_SERVICE_TOKEN`
  key-name bug while wiring CO-nightly.)
- **Snapshot = COPY, never share:** `pg_dump` prod → restore into nightly DBs
  (DH + CO) + copy DH `appfiles` volume. Nightly code never touches prod DBs.

## Risks

- **⚠️ ACCEPTED RISK — client data exposure.** Nightly mirrors **full prod data
  with no masking**; new-customer demos will see real Growatt/Johnson client
  names + customs declarations + BOMs. User was warned twice (2026-05-29) and
  **explicitly accepted** this confidentiality risk. Recorded here + in
  DECISIONS. Revisit if a demo audience is not under NDA / client consent.
- **Migration-on-prod-shaped-data:** nightly apps run their (possibly newer)
  migrations on the prod snapshot. This is the intended canary, but a
  destructive nightly migration runs against real-shaped data — acceptable
  because it's an isolated copy, but watch the nightly migration logs.
- **Resource contention:** second Postgres + 2 apps on the same box. Monitor
  memory; the box already runs prod DH + CO + nocodb.
- **Port/issuer mismatch** is the easiest thing to get wrong — if
  `sso_issuer_url` ≠ CO `DATA_HUB_ISSUER_URL`, SSO login + API tokens silently
  401 (the documented 8754-pinning incident, now at nightly ports).
- **Snapshot staleness vs demo stability:** "both triggers" means data refreshes
  nightly + code rebuilds on merge — a demo mid-session could shift if a merge
  lands. Mitigate: schedule the nightly window off-hours; freeze merges during a
  live demo if needed.

## Open Questions

- **Snapshot cadence vs the "demo" use:** nightly re-snapshot is fine, but do we
  also want a one-button "refresh now" before a specific demo? (Cheap to add a
  manual script alongside the cron.)
- **LLM config for nightly:** reuse prod's LLM key/env, or run nightly with LLM
  disabled (cheaper, but parser/agent demos degrade)? Default: reuse prod env.
- **Keys persistence:** nightly DH keys in a `nightly_keys` volume (stable issuer
  across rebuilds) — confirm we don't wipe it on rebuild (only on volume reset).

## Next step

Scaffold `tinsu-deploy`: `docker-compose.nightly.yml` + `.env.nightly.template`
+ `scripts/snapshot-prod-to-nightly.sh` + `scripts/nightly-build.sh` + a
scheduled trigger (cron on the box or a scheduled GH Action on the self-hosted
runner) + README. Then dry-run the snapshot + issuer wiring once by hand before
enabling the schedule. Recommend `/scaffold` for the repo skeleton, then build
the scripts incrementally with a manual first run.

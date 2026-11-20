---
id: IMP-007F
title: Add the dedicated import worker and trusted launcher
priority: P0
status: ready
type: feature
parent: IMP-007
depends_on: [IMP-007B, IMP-007D, IMP-007L]
resources: [v2-import-worker]
risk: critical
size: L
agent_tier: frontier
gate: owner
gate_approval: "owner 2026-10-31, IMP-007 spec r7 (covers all child tickets)"
review: independent
branch: 
pr: 
spec: docs/specs/imp-007-r7/spec.md
spec_approved: sha256:4cce4a674bf22ce519b38274a06b9b34fb7df958e9156be431ef9c9ee726477b
updated: 2026-11-20
---

# IMP-007F: Add the dedicated import worker and trusted launcher

## Goal

Run normalization in a dedicated worker that leases members, launches the parser in an isolated child, and finishes or cleans up through the SQL functions.

## Context

- r7 [runner.md](../docs/specs/imp-007-r7/runner.md), [r7-native-policy.md](../docs/specs/imp-007-r7/r7-native-policy.md), [protocol-appendix.md](../docs/specs/imp-007-r7/protocol-appendix.md) and [wire-contracts.json](../docs/specs/imp-007-r7/wire-contracts.json).
- Background only: the revision 1 planning draft [docs/specs/v2-drafts/WL-P0-007.md](../docs/specs/v2-drafts/WL-P0-007.md) (sha256:fa0971a0da787cb327484c92144e4a5ecd916db4ad0328e03b408d647190acd5), which the r7 bundle supersedes.

### Where to start

- SQL fragments and the function inventory: `src/kurafolio/persistence/ingestion_schema.py`. Existing providers and operator commands: `src/kurafolio/persistence/migration.py`, `source_migration.py`, `migrations/`, `scripts/postgres.py`.
- Python reference checks and DTO codecs: `src/kurafolio/ingestion/` (`approval.py`, `codec.py`, `contracts.py`, `cursors.py`, `reconciliation.py`).
- V2 HTTP application and DTO style: `src/kurafolio/web_v2/api.py`, `web_v2/schemas.py`.
- Tests to extend: `tests/test_postgres_migration.py`, `tests/test_ingestion_*.py`, `tests/test_web_v2_api.py`, `tests/test_web_v2_sources.py`; vectors in `tests/fixtures/ingestion/oracle.json`.
- Public status and boundaries: [web-v2-imports.md](../docs/web-v2-imports.md). Product intent: [PRODUCT_CONTEXT.md](PRODUCT_CONTEXT.md).

### Merged state this plan builds on (`main` a2f5f2b, 2026-11-20)

- IMP-007B, IMP-007C, IMP-007D and IMP-007L are done. All eight worker functions exist in `src/kurafolio/persistence/ingestion_schema.py` (`ingestion_schema.WORKER`): `claim_member_v1`, `renew_member_v1`, `admit_stage_v1`, `finish_member_v1`, `claim_plan_v1`, `read_plan_basis_v1`, `prepare_preview_v1`, `cleanup_set_v1`. Each has the signature `(p_worker uuid, p_token text, p_request jsonb, p_bytes bytea) RETURNS jsonb` and returns `{"ok": true, "value": <Ack>}` or `{"ok": false, "code": <code>}`. Serialization failures, deadlocks, lock timeouts and cancels are re-raised, not mapped. `ingestion_migration.grants` gives the worker role EXECUTE on exactly these eight and nothing else.
- Lease lengths in the merged SQL: a normalize lease lasts `LEAST(now+30s, set expiry, raw_deadline)` and only `renew_member_v1` extends it, for the `normalize` kind only. A prepare lease from `claim_plan_v1` lasts at most 60 s and a cleanup lease 30 s, and neither kind can be renewed. After `bind`, the handoff offer lasts `LEAST(bind+60s, raw_deadline)`. `claim_plan_v1` and `cleanup_set_v1` refuse to run outside READ COMMITTED.
- Worker identity: `_guard_worker_v1` requires the `wl_ingestion.workers` row named by `p_worker` to have `login_role = session_user`, `enabled`, the request's `credential_epoch` and the current realm digest. `reserve_member_v1` needs exactly one enabled worker row. Normalize calls use the API's handoff token as `p_token`. Prepare and cleanup claims take a fresh 256-bit token the worker generates (64 lowercase hex characters), and the database does not check that a token is new.
- Outside tests, nothing on `main` writes `wl_ingestion.instance_state` (wrapper catalog bytes, `ready`) or `wl_ingestion.workers`. `operator migrate-ingestion` (`src/kurafolio/web_v2/operator.py`) installs the schema and grants only, and `ingestion_restore` disables every worker. A migrated instance is therefore not ready for a worker (Decision D1).
- No runtime profile on `main` serves the 0004 HTTP routes. The APP-011I and APP-011E plan PRs (#82, #84) found this. IMP-007F does not need those routes: the worker and launcher talk only to PostgreSQL and to each other, and the sending side of the handoff belongs to IMP-007E.
- `src/kurafolio/ingestion/runner_client.py` provides the frames (`pack_input`, `unpack_input`, `pack_result`, `unpack_result`), `ChildOutputCollector` and `PeerTLS` (TLS 1.3 mutual authentication, exact DNS and URI SAN). `discovery.admit_parser2` and `discovery.admit_native` turn a child payload into the canonical Minimal bytes that `admit_stage_v1` takes. Wrapper profiles in `tests/test_ingestion_discovery.py` name the child entry point `kurafolio.ingestion.runner_child:main`, but that module does not exist yet.
- No merged code builds a `ReviewBundle` (review plus Plan) from basis pages and stages. `approval.validate_review_bundle`, `mapping.py` and `reconciliation.py` hold checks and helpers, and the tests use bundles from `oracle.json`. Prepare work needs such a builder (Decision D2).
- `wire-contracts.json` defines no operation that gives a worker the `CleanupProof` of an attempt whose launcher handle it no longer holds. `LaunchControl` needs the handle (Decision D4).
- `tests/test_source_harness.py` is a test-only harness that already runs the r7 child profile (`docker create`, then `start --attach`) and probes network, files, PIDs, memory, CPU, output and descendants. Reuse its flags and probe ideas; do not reuse its test-only `worker.py` in production code.
- `compose.yaml` runs the SQLite app and `compose.pg-foundation.yaml` runs PostgreSQL only. OPS-021, which depends on this ticket, builds the V2 stack (Decision D3).
- Only `finish_member_v1`, under a live normalize lease, moves a member to `reupload_required`. No sweep of lapsed leases exists, so after a worker crash the member stays `receiving` or `normalizing` until the set is cancelled or expires (Decision D7).
- Overlaps: IMP-007N (plan PR #81) changes which set `claim_plan_v1(work_kind=cleanup)` hands out. IMP-007M (plan PR #85, owner undecided) may change when a slot is released after a finish without proof; its recommended option B with F would have this worker wait for its launcher proof before `finish` and call a new slot-release function after a late proof (Decision D8). The worker only calls these functions and changes neither, so its tests must not depend on oldest-first cleanup order or on a slot release the merged SQL does not promise.

## Requirements

- Frozen r7 contract bundle, the contract approved as "IMP-007 spec r7": [docs/specs/imp-007-r7/](../docs/specs/imp-007-r7/README.md) (index sha256:75a859f65d7ee4564a20220b756b88ff44cf4449644167e2df2a87fd081e7fe7; the index lists the SHA-256 of each file), notably [spec.md](../docs/specs/imp-007-r7/spec.md), [sql-appendix.md](../docs/specs/imp-007-r7/sql-appendix.md), [sql-inventory.json](../docs/specs/imp-007-r7/sql-inventory.json), [contract-appendix.md](../docs/specs/imp-007-r7/contract-appendix.md) and [acceptance.md](../docs/specs/imp-007-r7/acceptance.md).
- Real-PostgreSQL tests need the explicit isolated environment; a skipped test is not acceptance. Use the claim's `isolation_id` and `port_base`.

### What to build

Two processes, in two pull requests if that keeps each review small (worker first, launcher second; say so in the Handoff).

1. The import worker. A long-running process with its own restricted database role. It loops: claim work with `claim_plan_v1`, do it, report through the worker SQL functions, repeat. The kinds of work are normalize (run the parser on received bytes), prepare (build the preview after decisions) and cleanup (remove what a finished, cancelled or expired set left behind). It renews its lease at least every 10 seconds; a lease lasts 60 seconds on the database clock. A worker whose lease has lapsed must not publish a result: every SQL call carries the fence it was given and the database refuses a stale one.
2. The launcher. A separate small service that starts the parser in a throw-away container and returns its output. The worker talks to it over a private authenticated channel. The worker has no Docker socket; the launcher has no database credentials. The parser container has no network, a read-only root, no private mounts, and CPU, memory, process and output limits. Only operator-pinned images run; nothing is pulled automatically.

Rules that reviewers will check:

- Received bytes live in memory or tmpfs for at most 120 seconds and are never written to the database, a queue or a log. If they are lost before the parser result is admitted, the member becomes `reupload_required`.
- Cancel, restart and recovery touch only containers this launcher started, matched by exact ID and its own labels. No kill-all, no prune, no adoption by name.
- A cleanup that cannot prove the raw bytes and the container are gone keeps the storage reservation and reports the failure. It never frees capacity it cannot prove is free.
- The owner's machine is an Apple Silicon Mac with Docker Desktop (owner decision 2026-11-11). The worker and launcher must run there inside the OPS-021 compose stack. Docker Desktop runs containers in a Linux VM, so record separately which controls are effective there and which are only proven on native Linux in CI.
- Contracts: `runner.md`, `protocol-appendix.md`, `wire-contracts.json` and `r7-native-policy.md` in the r7 bundle. The client half already exists in `src/kurafolio/ingestion/runner_client.py`; `src/kurafolio/ingestion/discovery.py` and `mapping.py` hold the checks the worker applies to parser output.

## Acceptance criteria

- [ ] AC-IMP-007F-01: Worker uses only worker SQL functions and a fenced lease.
- [ ] AC-IMP-007F-02: Parser child runs with effective Linux containment; residual limits are documented.
- [ ] AC-IMP-007F-03: Crash at each step leaves a recoverable state; retry books each event once.
- [ ] AC-IMP-007F-04: Given the example Wealthsimple holdings file and the example exchange orders file uploaded through the IMP-007E routes (or their SQL functions if 007E is not merged), the worker brings each set to a preview without a human step, and a confirmation then books the facts.
- [ ] AC-IMP-007F-05: A worker that stops renewing its lease cannot publish: a second worker takes the work after the lease expires and the first worker's late result is refused.
- [ ] AC-IMP-007F-06: The parser container is shown, by a test that tries each one, to have no network, no write access outside its scratch space and no access to the host socket; exceeding the memory, process, output or time limit ends it and the member is reported failed, not hung.
- [ ] AC-IMP-007F-07: After a set is cancelled, expires or is committed, no received bytes and no container of that set remain, and the storage reservation is released exactly once.
- [ ] AC-IMP-007F-08: The worker and launcher start and stop with one documented command each, with secrets read from files.
- [ ] AC-IMP-007F-09: The documentation states which containment controls were verified on Docker Desktop for Apple Silicon and which only on Linux.

## Build plan

- Based on: `main` at a2f5f2b (2026-11-20). Dependencies IMP-007B, IMP-007D and IMP-007L are merged; this plan uses their code as it stands.
- Delivery: two pull requests from the ticket branch, as Requirements allow. Record which is which in Handoff.
  - **PR 1, worker:** SQL caller, worker loop, handoff endpoint, a fake launcher, and unit plus real-PostgreSQL tests. It covers AC-01, AC-03 (worker side), AC-05 and AC-07 (database side). AC-04 is included only if D2 places the bundle builder in this ticket.
  - **PR 2, launcher:** launcher service, Docker engine adapter, ownership journal, child entry point, compose fragment and containment evidence. It covers AC-02, AC-06, AC-07 (container side), AC-08 and AC-09, and finishes AC-03 across both processes.
- The planner chooses no new Python dependency. Both services use the standard library (`ssl`, `http.server`, `subprocess`, `secrets`, `threading`) plus the SQLAlchemy/psycopg already in `requirements-pg.lock`. Any change to a lock file is a stop-and-ask point.

### Files

PR 1:

- `src/kurafolio/ingestion/worker_sql.py` (new): `WorkerSQL`, the only code that calls the database. `FUNCTIONS = ingestion_schema.WORKER`, checked at import time to equal the eight names above. `call(name, request, payload=None) -> dict` runs one READ COMMITTED transaction through `Database.engine.connect().execution_options(isolation_level="READ COMMITTED")` and `conn.begin()`. Do not use `Database.transaction()`: it requires a `TenantContext`, and the worker has no tenant scope; scope comes from the stored set. The statement is `SELECT wl_ingestion.<name>(:worker, :token, CAST(:request AS jsonb), :payload)`, with every value bound and `name` taken only from `FUNCTIONS`. The request is `codec.encode(codec.validate(request, <Request DTO>))`, and a successful value must pass `codec.validate(value, <Ack DTO>)` (DTO names from `wire-contracts.json#/worker_sql_contracts`). `{"ok": false}` raises `WorkerCallError(code)`. A serialization failure, deadlock or lock timeout retries the same request, with the same `request_id`, at most 3 times with jittered backoff, then raises `WorkerCallError('import_busy')`. Logs carry only the function name, `request_id` and code, never the token, request body or bytes.
- `src/kurafolio/ingestion/worker_config.py` (new): a closed JSON configuration, where unknown or missing keys are rejected. It holds paths and identifiers only: the worker-role DSN secret file (read with `PostgresConfig.from_secret_file`), the worker UUID, the credential epoch, the instance UUID, the API-facing server TLS files (`PeerTLS` with `peer_role='api'`), the launcher-facing client TLS files (`peer_role='launcher'`), the launcher address and DNS name, the bind address for the handoff server, and the source catalog file (descriptors) and wrapper profile file used by `discovery.admit_*`. Secret files must be regular, owned by the service UID, mode `0600` or stricter, with one link, the same checks as `PeerTLS.context`.
- `src/kurafolio/ingestion/handoff_server.py` (new): the worker's private `POST /internal/v1/handoffs`, built on stdlib `ssl` and `http.server.ThreadingHTTPServer`. The server context is `PeerTLS(...).context(server=True)`, and `verify_peer` runs on each connection before any byte of the body is read. Rules from `protocol-appendix.md`: one positive `Content-Length`, at most `4 + MAX_CONTROL + MAX_CONTEXT + MAX_RAW`; `Transfer-Encoding`, `Content-Encoding` and `Expect` are refused; the body must arrive within 30 s in total with at most 5 s idle; the frame goes through `unpack_input(frame, schema='Handoff')`. The response is a canonical `HandoffAck`. Any other path or method gets 404 or 405 with no detail.
- `src/kurafolio/ingestion/worker.py` (new): `ImportWorker` and `main(argv)`, with subcommand `serve --config <file>`. It contains the loop under "Worker loop" below, `LeaseKeeper` (renewal), `RawHold` (in-memory ownership of raw and context), the `LauncherClient` protocol and `FakeLauncher` (in tests only, never importable from `main`).
- `tests/test_ingestion_worker.py` (new): unit tests with a fake `WorkerSQL`, a fake launcher and an injectable monotonic clock. No database and no Docker.
- `tests/test_postgres_worker.py` (new, opt-in with `KURAFOLIO_INGESTION_TEST=1`): real-PostgreSQL tests with real worker processes. Reuse the seed helpers of `tests/test_postgres_migration.py` (`claim_seed`, `lease_call`, `accept_seed`, the session fixtures). If they have to move into a shared `tests/ingestion_pg_support.py`, move them without changing any existing assertion.
- `docs/web-v2-imports.md`: what the worker does, its configuration and its limits. Replace "No worker process calls it yet" where it becomes untrue.

PR 2:

- `src/kurafolio/ingestion/launcher.py` (new): `Launcher` and `main(argv)`, with subcommand `serve --config <file>` and `check --config <file>` (readiness probes, see AC-09). Its mTLS server accepts only the worker identity (`peer_role='worker'`) and has two routes: `POST /internal/v1/jobs` (a `LaunchStart` frame from `pack_input`, context at most 1 MiB, raw at most 10 MiB) and `POST /internal/v1/control` (canonical `LaunchControl`, at most 16 KiB). Results stay in memory until acknowledged or until the raw deadline, whichever comes first. Responses are `LaunchStatus`, or for `include_result=true` a `pack_result(LaunchResult, payload)` frame with the launcher's own `handle`.
- `src/kurafolio/ingestion/launcher_engine.py` (new): the only module that touches Docker. It runs the `docker` CLI through `subprocess.run([...], shell=False, timeout=...)` with argument lists built from constants and the selected wrapper profile only. Allowed operations: `create` with the exact flags below and the labels `kurafolio.launcher.instance=<launcher instance UUID>`, `kurafolio.launcher.nonce=<sha256(nonce)>` and `kurafolio.launcher.fence=<fence>`; `start --attach --interactive <engine ID>`; `inspect <engine ID>`; `kill <engine ID>`; `rm --force <engine ID>`; and `ps --all --no-trunc --filter label=kurafolio.launcher.instance=<own UUID> --filter label=kurafolio.launcher.nonce=<digest>`, used only for the crash between create and journal write. No `pull`, `prune`, `--name` lookups or `docker exec`. The image reference is `<repository>@sha256:<digest>` from the profile, and it must already exist locally (`inspect`); the launcher never pulls.
- `src/kurafolio/ingestion/launcher_journal.py` (new): the ownership journal on its own volume. One record per attempt, written atomically (write to a temporary file, `fsync`, rename), with the fields in `protocol-appendix.md` "Native controls and restart": instance, peer, credential epoch, realm digest, job, member, fence, `sha256(nonce)`, `sha256(handle)`, engine ID, image digest, deadlines and state (`created`, `started`, `result_ready`, `failed`, `cleanup_pending`, `finished`). It never holds raw bytes, context, results, stderr or a plaintext nonce or handle.
- `src/kurafolio/ingestion/runner_child.py` (new): the fixed child entry point `main()`. It is started as `/usr/bin/env -i PATH=/usr/local/bin:/usr/bin:/bin LANG=C.UTF-8 LC_ALL=C.UTF-8 TZ=UTC HOME=/nonexistent PYTHONDONTWRITEBYTECODE=1 PYTHONHASHSEED=0 PYTHONUNBUFFERED=1 python -I /app/src/kurafolio/ingestion/runner_child.py`. That argument list is a launcher constant, not caller input. The script inserts only `/app/src` into `sys.path`, reads one stdin frame (`unpack_input(..., schema='LaunchStart')` layout: header, context, raw), decodes `ParserChildContext` or `NativeChildContext`, loads the adapter named by the image's fixed registrations (`kurafolio.source_builtin:registrations` for the built-ins), runs it, and writes `pack_result(ChildResult, payload, child=True)` to stdout. It writes nothing else to stdout, exits 0 only on success, and never prints raw values to stderr.
- `src/kurafolio/ingestion/launcher_client.py` (new): the worker's mTLS client for the launcher (`PeerTLS` with `peer_role='launcher'`). PR 1 defines the `LauncherClient` protocol this class implements.
- `compose.ingestion.yaml` (new): services `import-launcher` and `import-worker` on a network marked `internal: true`, with no published ports. Secrets are files mounted read-only and readable only by the service UID. The launcher mounts the operator-provisioned Docker socket and a dedicated `import-launcher-journal` volume. The worker mounts neither a socket nor any financial volume. Both services: `read_only: true`, `cap_drop: [ALL]`, `no-new-privileges`, and an explicit `user`. Built so that OPS-021 can include it (D3).
- `docs/web-v2-import-worker.md` (new): the start and stop commands, secret files, the worker registration step (per D1), the containment matrix for AC-09 and recovery behaviour. Link it from `docs/web-v2-imports.md` and `docs/capability-status.md`.
- `tests/test_ingestion_launcher.py` (new): unit tests with a fake engine (no Docker) for framing, journal states, restart reconciliation and refusals.
- `tests/test_ingestion_containment.py` (new, opt-in with `KURAFOLIO_LAUNCHER_TEST=1`, needs a Docker engine): real child probes through the real launcher.

### Interfaces

Child profile: `create` uses exactly these flags, the values from `protocol-appendix.md` and `tests/test_source_harness.py` `PROFILE`: `--user 10001:10001 --read-only --cap-drop ALL --security-opt no-new-privileges --network none --ipc none --tmpfs /tmp:rw,noexec,nosuid,nodev,size=33554432,uid=10001,gid=10001 --memory 268435456 --memory-swap 268435456 --cpus 1 --pids-limit 16 --ulimit cpu=2:2 --ulimit nofile=64:64 --ulimit core=0:0 -i`, plus the entry point above and no `--env`, `--volume`, `--mount`, `--privileged`, `--device` or `--add-host`. Timeouts: setup and control 30 s; execution 10 s from the engine's `State.StartedAt`; stop and reap 5 s; stream joins 2 s; removal 5 s. The raw deadline caps every phase. Stdout is read through `ChildOutputCollector`. Stderr is drained to at most 64 KiB and never stored or logged.

Launcher outcome classification, checked in this order: stdout or stderr overflow gives `output_limit` (overflow wins even if the exit raced); execution past 10 s from `StartedAt`, or the raw deadline, gives `wall_limit` after the launcher kills the child; `State.OOMKilled` true, exit status 137 without a launcher kill, or a signal exit from `RLIMIT_CPU` (SIGXCPU or SIGKILL) gives `resource_exit`; any other nonzero exit gives `child_error`; a frame that `unpack_result` refuses gives `frame_rejected`. A fork refused by `--pids-limit` does not end the child by itself; the outcome is whatever the child then does under this rule.

Handoff refusals: a refused handoff returns HTTP status `contracts.ERROR_STATUS[code]` with the canonical body `{"code": <code>}` and nothing else. `HandoffAck` is returned only with status 202. IMP-007E tests against a fake worker, so its plan and this shape must match; if they differ, stop and ask. `http.server.BaseHTTPRequestHandler.log_message` and `log_error` are overridden on both servers so that only the method, path, status, error code and request ID are logged, never headers, bodies or peer certificate details.

Worker loop. The worker is one process with three threads: the handoff server, the lease keeper and the pull loop. It has no database writes outside `WorkerSQL` and no durable state except what D4 decides.

1. **Normalize (pushed by the API).** On a handoff:
   1. Check the peer, the frame and the `Handoff` fields. Refuse with `HandoffAck.outcome = reupload_required` if `raw_deadline` or `expires_at` has passed on the worker clock. The database still decides.
   2. Call `claim_member_v1` with `p_token = handoff_token` and request `{version: 1, realm_digest, credential_epoch, job_id, set_id, member_id, work_kind: "normalize", fence, request_id: <uuid4>, raw_digest: raw_sha256, context_digest: context_sha256}`. On `claimed` or `already_claimed`, keep raw and context in a `RawHold` (`bytearray`, zeroed and released on drop) that expires at `raw_deadline` no matter how often the lease is renewed, then answer `HandoffAck{outcome: owned | already_owned, input_owned: true, stage_digest: null}`. On `import_reupload_required`, answer `reupload_required` and drop the bytes. On any other error, answer with the fixed error code and drop the bytes.
   3. `LeaseKeeper` calls `renew_member_v1` (new `request_id` each time, and always the same handoff token as `p_token`) every 10 s or sooner, and at the latest 5 s before `LeaseAck.expires_at`. Always take expiry from `expires_at`; never assume 60 s. The first renew error marks the lease lost: the job stops, cancels its launcher attempt, drops `RawHold` and makes no further call with that fence except a `finish` that the database may refuse.
   4. Start the launch with `LaunchStart{operation: "start", job_id, member_id, fence, instance_id, realm_digest, credential_epoch, installation_id, image_digest, wrapper_profile_digest, format_version (all from the decoded child context), context_sha256, context_bytes, raw_sha256, raw_bytes, deadline: raw_deadline, nonce: secrets.token_hex(32)}`. Poll `LaunchControl{operation: "status", include_result: true}` until the state is `result_ready` or `failed`, or the raw deadline passes.
   5. On `ok`: `unpack_result` against the expected bindings, then `admit_parser2` or `admit_native` with the descriptor and the wrapper profile that match `installation_id` and `wrapper_profile_digest` exactly. If there is none or more than one, finish `rejected` with `import_evidence_unsupported`. Then call `admit_stage_v1` with `p_bytes = minimal`, `stage_digest = sha256(minimal)`, `discovery_digest = sha256(child payload)`, `raw_digest` and `payload_bytes = len(minimal)`. Clear `RawHold` and every payload buffer as soon as `admit_stage_v1` returns, whatever the outcome.
   6. Send `cancel` if the attempt is still running, then poll `status` until `finished` with `cleanup_complete: true` (proof `absent`), or until the stop/reap/removal budget runs out (proof `pending` or `failed`). Then send `forget`.
   7. Call `finish_member_v1` with `outcome` and `error_code` from the table below and `cleanup_proofs = [proof]`.

   | Launcher outcome or worker event | `finish` outcome | `error_code` |
   |---|---|---|
   | `ok` and stage admitted | `stage_admitted` | `null` |
   | `output_limit`, `resource_exit`, `wall_limit` | `rejected` | `import_limit` |
   | `child_error`, `frame_rejected`, or a payload refused by `unpack_result` or `admit_*` with `import_invalid` | `rejected` | `import_invalid` |
   | `admit_*` refuses with `import_evidence_unsupported` or `import_stale` | `rejected` | the same code |
   | `context_rejected` | `rejected` | `import_stale` |
   | launcher unreachable, `cancelled` by this worker, `cleanup_failed`, or raw deadline reached before admission | `reupload_required` | `import_runner_unavailable`, or `import_reupload_required` for the deadline |

   Under the merged SQL, a `rejected` finish rejects the whole set (`test_finish_rejection_rejects_the_whole_set`), so one over-limit or invalid file ends every member of its set. The docs must say so.

   If step 6 has no `absent` or `not_created` proof yet, finish keeps the user's raw slot held until the set is terminal and cleaned (IMP-007M). The IMP-007M plan (PR #85, not decided by the owner) recommends option B with F: the worker would keep polling the launcher for the proof before `finish`, bounded by the raw deadline, and after a late proof call a new slot-release worker function. This plan does not build either. If the owner chooses them, IMP-007F gains a dependency or a follow-up, and the builder stops and asks (D8).

   A `CleanupProof` is `{job_id, fence, state, launcher_instance_id, checked_at, proof_digest}`. `state` is `absent` when the launcher reports `finished` with `cleanup_complete: true`, `not_created` when the launcher reports that no engine object was ever created for that nonce, `pending` while removal is in progress, and `failed` after a failed removal. `checked_at` is a UTC `Instant` from the launcher's status. `proof_digest = codec.digest(<the LaunchStatus object the proof was read from>)`. The DB checks only the shape, so this definition is the plan's choice; if the reviewer or owner wants another one, stop and ask.
2. **Prepare (pulled).** Loop `claim_plan_v1{work_kind: "prepare", claim_request_id: <uuid4>}` with a fresh `secrets.token_hex(32)` token. After `no_work`, sleep 1 s plus up to 1 s of jitter. After `claimed`, read every basis resource with `read_plan_basis_v1` (cursor paging, `limit` 50) under the lease, build the `ReviewBundle` (D2), and call `prepare_preview_v1` with `p_bytes = codec.encode(bundle)` and the pins from the lease and basis. The lease cannot be renewed, so if less than 5 s remain before `expires_at`, give up the work: send no further calls, and the next claim after expiry starts again. Never reuse a token or a `claim_request_id`.
3. **Cleanup (pulled).** Loop `claim_plan_v1{work_kind: "cleanup"}` the same way. For the claimed set, collect a proof for each normalize attempt of that set this worker knows about (see D4), at most 12 in total and 3 per attempt, and call `cleanup_set_v1`. If the result is `cleanup_pending`, leave the set; the database keeps the reservation and a later claim retries. Do not assume oldest-first order (IMP-007N).
4. **Shutdown (SIGTERM).** Stop accepting handoffs and claims, cancel running launches, drop every `RawHold`, and exit within 10 s. Leases lapse on the database clock. No call tries to end them early.

Launcher on restart: read the journal; for each record that is not `finished`, `kill`, then `rm --force` the exact engine ID, mark it `cleanup_pending` until `inspect` reports the ID absent, then `finished`. For a `created` record with no engine ID (a crash between create and journal write), find the container only with the exact `instance` plus `nonce`-digest label filter and remove it. Any late result from before the restart is discarded. Credential epoch change: refuse every control from the old epoch, reconcile its children, then accept the new epoch.

Operator worker registration: per D1. Until D1 is decided, tests seed `wl_ingestion.instance_state`, `instance_budgets` and `workers` through the operator role exactly as `tests/test_postgres_migration.py` does today.

### Tests

Name the acceptance ID in each test name or docstring. "PG" means opt-in real PostgreSQL (`KURAFOLIO_INGESTION_TEST=1`) with the claim's `isolation_id` and `port_base`. "Docker" means opt-in `KURAFOLIO_LAUNCHER_TEST=1` on a real engine. A skipped test is not acceptance.

| AC | Case | Expected |
|---|---|---|
| 01 | Static: every database call in `src/kurafolio/ingestion/worker*.py` goes through `WorkerSQL.call`, and `FUNCTIONS` equals `ingestion_schema.WORKER` | 8 names exactly; no other `wl_` identifier in worker modules |
| 01 | PG: the worker role reads `wl_ingestion.sets`, calls `create_set_v1`, calls `accept_preview_v1` | each fails with `permission denied` (SQLSTATE 42501) |
| 01 | Unit: every request the worker sends after a claim carries the `fence` and `job_id` from that claim's `LeaseAck` | 100 % of recorded calls; a test that alters the fence fails |
| 01 | Unit with fake clock: lease renewal cadence over 45 s of work on a lease with `expires_at` = claim + 30 s | renew at most 10 s apart; at least 4 renew calls; none after the first renew error |
| 01 | PG: two calls with the same `request_id` after a lost acknowledgement | second returns the stored acknowledgement byte for byte |
| 02 | Docker: `inspect` of a child started by the launcher | `HostConfig` values equal to the profile: `ReadonlyRootfs` true, `NetworkMode` `none`, `IpcMode` `none`, `CapDrop` `[ALL]`, `SecurityOpt` contains `no-new-privileges`, `Memory` 268435456, `MemorySwap` 268435456, `NanoCpus` 1000000000, `PidsLimit` 16, `User` `10001:10001`, no `Binds` or `Mounts` except the `/tmp` tmpfs |
| 02 | Docker: effective environment probe (the child prints `sorted(os.environ)` through a test-only probe image built from the same base) | exactly the eight declared variables, with the declared values |
| 03 | PG + fake launcher: SIGKILL the worker at each step (after claim, after launch start, after result before `admit_stage_v1`, after admit before `finish_member_v1`, after finish), then start a new worker process | Killed before finish (any step up to and including admit): the merged SQL has no path to `reupload_required` without a live-lease `finish` (only `finish_member_v1` sets it), so the member stays `normalizing`, the new worker cannot claim it (the handoff token died with the old process), `renew_member_v1` and `finish_member_v1` with the old fence return `import_stale`, and the set never reaches a preview from the old bytes. The test then cancels the set through `cancel_set_v1`: the set is `CANCELLED`, and a cleanup lease releases the slot and storage once, given proofs (D4). If killed after admit, exactly one `wl_ingestion.stages` row exists until the purge, and nothing re-runs the parser. Killed after finish: state equals the uncrashed run. See D7 for the gap against Requirements |
| 03 | PG: confirm the same preview twice with the same operation ID, and once with a new operation ID | one receipt; the second call replays it; the new operation returns the explicit no-change result; booked rows counted before and after are equal |
| 03 | Unit: database error `serialization_failure` on `admit_stage_v1` | retried with the same `request_id`; one stage |
| 04 | PG + fake launcher that runs `runner_child` logic in-process on `examples/data/wealthsimple-holdings.csv`, sets created and reserved through `create_set_v1` and `reserve_member_v1` (`reserve`, then `bind`) under the existing session fixture, and a test API peer that posts the handoff | set reaches a preview state with no test step between upload and preview; after the decisions the review requires (if any) through `decide_set_v1`, the preview is READY and `accept_preview_v1` books it; 3 accounts, 6 positions, CAD native sum 565, USD native sum 150, `as_of` 2024-02-01T10:00:00-05:00, coverage `partial`, membership `unknown` (oracle `builtin-inputs.json`, `wealthsimple_expected`) |
| 04 | Same for `examples/data/bull-orders.csv` | 2 accounts, 3 completed orders, 2 completed buys, BTC 0.00400000, LBTC 0.00300000, purchase cost CAD 700.00, funding CAD 1000.00, contribution boundary `unclassified`, no wallet truth (oracle `bull_expected`); no contribution and no wallet balance booked |
| 04 | Docker variant of both, through the real launcher and child | same values as above |
| 05 | PG: worker A claims a prepare lease and stops (SIGSTOP); after `expires_at` (forced with the `session_replication_role=replica` pattern of `test_renew_refuses_a_lapsed_or_foreign_lease`), worker B claims the same set; A is resumed and calls `prepare_preview_v1` with its old fence and token | B gets a new lease with fence + 1; A's call returns `import_stale` or `authentication_required`; exactly one preview row from B |
| 05 | PG: normalize lease with renewal stopped (process A paused with SIGSTOP); after expiry, A is resumed and calls `admit_stage_v1` and then `finish_member_v1` with its old fence | both return `import_stale`; no stage row from that fence; the member stays `normalizing` (D7) until the set is cancelled or expires. The raw bytes lived only in process A, so a "takeover" of normalize work means a new upload with a new fence after the set's recovery, not a second worker reusing A's bytes |
| 05 | PG: cleanup lease lapses; a second claim picks up the set | fence + 1; the late `cleanup_set_v1` with the old fence returns `import_stale`; storage released once |
| 06 | Docker, one probe each: connect to 1.1.1.1:53 and to the host gateway; write to `/`, `/app` and `/etc`; read a host canary path; open `/var/run/docker.sock` | each denied; only `/tmp` writable; probe output reports flags only |
| 06 | Docker, one run each: allocate 512 MiB; fork 32 processes and keep them alive; write 5 MiB to stdout; write 128 KiB to stderr; sleep 20 s; spin CPU for 5 s | each run ends within 10 s + 5 s with a launcher outcome other than `ok`, the member's `finish` is `rejected` (never left `normalizing`), no container with the attempt's labels is left, and the journal record is `finished`. The exact outcome follows the launcher's classification rule below; cross-check it against what `test_source_harness.py::test_bounded_resource_exits_output_precedence_and_cleanup` measures for the same probes |
| 06 | Unit: overflow and nonzero exit race | overflow wins (`import_limit`) |
| 07 | PG + Docker: one set each cancelled during reception, cancelled after launch, expired, and committed | after the cleanup lease: no `wl_ingestion.stages` or `previews` rows for the set, no `RawHold` in the worker, no container with the set's labels, the journal record `finished`; `instance_budgets.reserved_bytes` and the user's raw slot return to their value before the set, exactly once (a second cleanup claim returns `no_work` or `already_purged` and changes nothing) |
| 07 | PG + fake launcher returning `pending` then `failed` proofs | storage and slot stay held; `CleanupAck.outcome = cleanup_pending`; released once on the first all-`absent` proof |
| 08 | Docker: `docker compose -f compose.ingestion.yaml up -d import-launcher import-worker`, then `stop` | both start with secrets read from files under `/run/secrets`; `inspect` shows no `Env` entry holding a secret value; stop completes within 10 s; no child left |
| 08 | Unit: configuration with an unknown key, a group-readable secret, or a symlinked secret | refused with a fixed code before any connection |
| 09 | Docs check: `docs/web-v2-import-worker.md` has a table with one row per control (network, read-only root, user, capabilities, no-new-privileges, IPC, PIDs, memory and swap, CPU, RLIMIT_CPU, nofile, core, tmpfs flags, environment, socket absence, output limits) and two columns, Docker Desktop on Apple Silicon and native Linux CI, each cell `verified (date, engine version, test name)`, `not effective` or `not tested` | every row filled from an actual `launcher check` run; nothing claimed from configuration alone |

Negative cases that must exist besides the table: a wrong peer certificate on each private endpoint (refused before reading the body); a `LaunchStart` with an unknown field, a tag-based image or a profile digest not in the wrapper profile file (refused, no container created); `LaunchControl` for another worker's handle or epoch (refused); a handoff whose context or raw hash does not match (no claim, no accepted effect); duplicate JSON keys or trailing bytes in a child frame (`import_invalid`).

### Rollback

Both services are new processes. Disabling them means stopping them and, per D1, disabling the worker row. Pending sets then expire and wait for cleanup, with capacity still held, until a worker runs again. No schema, migration or accepted data changes, so there is nothing to undo in PostgreSQL. Reverting the PRs removes code and the compose fragment only.

### Do not touch

- `src/kurafolio/persistence/ingestion_schema.py`, `ingestion_migration.py`, `ingestion_restore.py`, `migrations/` and any SQL text or grant. If the worker needs a database change, stop.
- `docs/specs/imp-007-r7/**` (frozen r7 bundle, including `wire-contracts.json`), `tests/fixtures/ingestion/oracle.json` and existing assertions in `tests/test_postgres_migration.py`.
- `compose.yaml`, `compose.pg-foundation.yaml` and `Dockerfile`, apart from what D3 allows, and the IMP-007E route files (`src/kurafolio/web_v2/api.py`, `imports.py`, `schemas.py`).
- `src/kurafolio/web_v2/operator.py`, unless D1 assigns the registration command to this ticket.
- `tests/fixtures/source_capabilities/**` (test-only harness).

### Stop and ask if

- A test needs a member to reach `reupload_required` after a worker crash, or a slot to be released before the set is terminal (D7, D8). Do not add SQL for it.
- D1, D2, D3 or D4 is still open when the builder reaches the part that needs it. PR 1 can start with normalize, renewal, the fake launcher and the AC-01, AC-03 and AC-05 tests without any of them.
- A worker step seems to need a SQL function, column or grant that does not exist, or a renewal for prepare or cleanup leases.
- A required child control is not effective on Docker Desktop (for example `--ulimit cpu` or `--pids-limit` inside the Desktop VM). Record it as `not effective` and ask; do not weaken the profile.
- Building the child image needs a network pull, a new base image or a lock-file change.
- An expected value in the Tests table disagrees with the oracle fixture. The fixture wins; report the difference.
- The launcher would need the Docker socket in any container other than `import-launcher`.

## Plan

- [ ] PR 1: `WorkerSQL`, configuration, handoff endpoint, normalize loop with lease renewal, fake launcher.
- [ ] PR 1: prepare and cleanup pull loops (prepare needs D2, cleanup proofs after a restart need D4).
- [ ] PR 1: unit and real-PostgreSQL tests for AC-01, AC-03, AC-05 and AC-07 (database side); AC-04 if D2 puts the builder here.
- [ ] PR 2: launcher, engine adapter, journal and restart reconciliation.
- [ ] PR 2: `runner_child.py` and the child profile.
- [ ] PR 2: compose fragment and start/stop commands (D3); worker registration (D1).
- [ ] PR 2: containment tests on native Linux CI and on Docker Desktop for Apple Silicon; containment matrix (AC-02, AC-06, AC-09).
- [ ] Docs: `docs/web-v2-import-worker.md`, `docs/web-v2-imports.md`, `docs/capability-status.md`.

## Decisions needed

Raised by the planner on 2026-11-20 from the merged code. None of these is decided yet. D5 proposes a change to gated text; D7 may lead to one.

- **D1. Making an instance ready for the worker.** On `main`, nothing outside tests writes `wl_ingestion.instance_state` (wrapper catalog, `ready`), `instance_budgets` or the `wl_ingestion.workers` registry row. Without them every worker call returns `instance_not_ready` or `authentication_required`, and `reserve_member_v1` returns `import_runner_unavailable`. This adds to the missing 0004 runtime profile that the APP-011I and APP-011E plans reported. Options: (a) IMP-007F adds `operator register-ingestion-worker` (insert or enable the single worker row and raise `credential_epoch` on rotation), and whoever builds the 0004 runtime profile (IMP-007E is the siblings' recommendation) also loads the wrapper catalog and sets `ready`; (b) one new ticket does all three; (c) IMP-007F does all three. The planner recommends (a): the worker row is the worker's own identity, and readiness belongs with the profile that serves the routes. Until this is decided, tests seed these rows through the operator role, and AC-08 can be shown only on a test instance seeded that way.
- **D2. Who builds the ReviewBundle.** The worker's prepare step must turn basis pages, stages and decisions into a `ReviewBundle` that `prepare_preview_v1` accepts. No merged code does this; it is the reconciliation engine of `reconciliation.md`, `normalized-evidence.md` and `contract-appendix.md`, with the oracle `*-review.json` and `*-plan.json` vectors as expected values. Options: (a) a new ticket (risk critical, tier frontier) that IMP-007F's prepare step and AC-04 depend on; (b) a third PR inside IMP-007F. The planner recommends (a): it is financial logic with its own review needs, and the worker and launcher can be built and reviewed without it. Option (a) adds a dependency to this approved ticket, which needs the owner's confirmation in its Log.
- **D3. Compose stack order.** Requirements say the worker and launcher must run inside the OPS-021 compose stack, but OPS-021 depends on IMP-007F. The planner proposes that IMP-007F ship `compose.ingestion.yaml` with only the `import-launcher` and `import-worker` services, built so that OPS-021 can include it, and that the AC-08 commands use that file until OPS-021 lands. Please confirm, or say that IMP-007F should edit another compose file.
- **D4. Cleanup proofs after a worker restart.** `cleanup_set_v1` needs a `CleanupProof` per bound normalize attempt (`job_id`, `fence`), and `LaunchControl` needs the attempt's launcher `handle`. Neither the cleanup lease nor any worker function tells the worker which attempts a set had, and a restarted worker no longer holds the handles. Without a fix, a crash during normalization holds that user's only raw slot until an operator steps in, which conflicts with AC-03 and AC-07. Options: (a) the worker keeps a small private journal (set, job, member, fence and handle; no raw, context or result) on its own volume, mode `0600`, readable only by the worker UID; (b) change the frozen `LaunchControl` contract so that the launcher can answer by job and fence; this is a change to the r7 bundle and needs a new spec revision; (c) leave such attempts `cleanup_pending` and document an operator recovery. The planner recommends (a). The protocol forbids plaintext nonces and handles only in the launcher journal and in logs, and a handle is usable only with the worker's own certificate and credential epoch.
- **D5. Proposed wording change to gated text (owner approval needed).** Requirements item 1 says "a lease lasts 60 seconds on the database clock". The merged SQL, which follows the r7 limit of at most 60 s, gives normalize and cleanup leases 30 s and prepare leases up to 60 s. The plan follows the SQL and reads expiry from `LeaseAck.expires_at`. Proposed text: "a lease lasts at most 60 seconds on the database clock (30 s for normalize and cleanup in the merged functions)". This changes the spec hash and needs a new Gate A; the builder can work without it because the plan does not depend on the exact number.
- **D6. No renewal for prepare and cleanup leases.** The merged SQL renews only normalize leases. The plan bounds prepare and cleanup work to one lease and gives up when less than 5 s remain. If a large set cannot be prepared within one 60 s lease, a renewal function is a SQL change outside this ticket's `v2-import-worker` resource. Please confirm that one-lease preparation is acceptable for the MVP, or ask for a SQL ticket.
- **D7. A lost worker cannot move the member to `reupload_required`.** Requirements say "If they are lost before the parser result is admitted, the member becomes `reupload_required`." In the merged SQL only `finish_member_v1` with a live normalize lease does that. If the worker process dies, its lease lapses, nothing else can finish the attempt, and the member stays `normalizing` (or `receiving`) until the user cancels the set or it expires after 24 hours. The user's single raw slot stays held until then. The worker alone cannot meet that sentence after a crash; it can only when the worker survives (lost launcher, raw deadline). Options: (a) accept cancel or expiry as the recovery for the MVP and say so in the docs; (b) a SQL ticket (in the IMP-007M family, `ingestion-schema-sql`) for a fenced sweep that turns a lapsed normalize attempt into `reupload_required`; (c) relax the Requirements wording (a gated change). The planner recommends (b), with (a) until it lands, because AC-03 asks for a recoverable state and a 24-hour block is a poor one. The AC-03 and AC-05 tests are written against the merged behaviour.
- **D8. Dependency on the IMP-007M decision.** The IMP-007M plan (PR #85) recommends option B with F. Under that choice, this worker would keep polling the launcher for its cleanup proof before calling `finish`, within the 120 s raw deadline, and after a late proof would call a new slot-release worker function that a follow-up ticket adds. The owner has not decided, so this plan builds neither. Once the owner decides, please say whether the worker part belongs in IMP-007F (a new dependency on the follow-up ticket, recorded in this ticket's Log) or in the follow-up ticket itself.

## Handoff

- State: Not started.
- Next step: Read `runner.md` and `protocol-appendix.md` in the r7 bundle, then `src/kurafolio/ingestion/runner_client.py` and the worker function tests in `tests/test_postgres_migration.py` (`test_claim_*`, `test_finish_*`, `test_cleanup_*`). Write the worker loop against the SQL functions with a fake launcher first; add the real launcher second.
- Verify: `KURAFOLIO_INGESTION_TEST=1 PYTHONPATH=src .venv/bin/python -m unittest discover -s tests -p 'test_postgres_migration.py' -v` and `PYTHONPATH=src .venv/bin/python -m unittest discover -s tests -p 'test_ingestion_*.py' -v`; environment setup in [postgres-foundation.md](../docs/postgres-foundation.md) and [web-v2-imports.md](../docs/web-v2-imports.md)
- Gotchas: None recorded.
- Open questions: None.

## Log

- 2026-11-05 planner: created in the initial backlog plan.
- 2026-11-10 planner: owner re-confirmed this ticket for the V2 MVP on 2026-11-10; released (status ready), added starting files and verify commands.
- 2026-11-10 planner: added the dependency on IMP-007L: the worker cannot prepare a review without the prepare-lease functions.
- 2026-11-13 planner: added a plain description of the two processes, the rules from the approved r7 contract, and six acceptance criteria, including the owner's platform decision of 2026-11-11. Scope is unchanged.
- 2026-11-17 planner: the owner confirmed in conversation ("Confirm all six") the changes PR #64 made to this ticket after its approval. The approval in gate_approval covers the text as it stands now.
- 2026-11-18 claude-code/opus-5.5: ENG-113 migrated this ticket to the spec format without changing any wording: moved the bullet naming the r7 contract bundle, the "Real-PostgreSQL tests" bullet of Where to start and "What to build" from Context into Requirements and numbered the acceptance criteria AC-IMP-007F-01 to 09. Spec hash sha256:4cce4a674bf22ce519b38274a06b9b34fb7df958e9156be431ef9c9ee726477b, awaiting the owner's confirmation.
- 2026-11-18 claude-code/opus-5.5: the owner confirmed the migrated text of this ticket in conversation with "Confirm all 29", the batch listed in ENG-113 decision 3; `spec_approved` records sha256:4cce4a674bf22ce519b38274a06b9b34fb7df958e9156be431ef9c9ee726477b.
- 2026-11-20 claude-code/opus-5.5: wrote the Build plan from `main` a2f5f2b and raised decisions D1 to D8, including one proposed change to gated text (D5); plan PR #86.

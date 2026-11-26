# Dedicated import worker and trusted launcher

The dedicated import worker and the trusted launcher are two new private
processes. The worker receives one bound upload at a time, runs the reviewed
child in a constrained container, admits its canonical evidence and waits for a
cleanup proof. The launcher is the only process with Docker control; it starts
only the pinned reviewed image with the fixed profile and journals ownership as
digests. Neither process performs preparation; that is IMP-007V.

## Start and stop

Use the source-only image and the compose fragment
[`compose.ingestion.yaml`](../compose.ingestion.yaml) with OPS-021. Both services
run on the internal network with no published port.

```bash
docker compose -f compose.ingestion.yaml up -d import-launcher import-worker
docker compose -f compose.ingestion.yaml stop import-launcher import-worker
```

The launcher and worker image is built from `Dockerfile.ingestion` on an exact
source image; it adds the Docker CLI from
`docker:29.6.1-cli@sha256:862099ada15c6690...` (the multi-architecture manifest
list covers amd64 and arm64) and creates both journal directories owned by UID
10001. The child image is the source-only image built from `Dockerfile` by
`scripts/check_pr_image.py`; `Dockerfile.ingestion` is not a child image. On 2026-11-25, `docker compose -f compose.ingestion.yaml up -d`
started `import-launcher` and `import-worker` with synthetic configuration and
`stop` completed in 1 s; the worker logged its expected synthetic database
errors because no database was mounted.

The commands inside the containers are fixed:

```bash
python -m kurafolio.ingestion.launcher serve --config /run/config/launcher.json
python -m kurafolio.ingestion.launcher check --config /run/config/launcher.json
python -m kurafolio.ingestion.worker serve --config /run/config/worker.json
```

`check` prints the exact image reference, its local image ID and the created
container's effective HostConfig for each reviewed profile digest. It never
pulls an image. A missing or mismatched image fails readiness.

## Secrets and configuration

All configuration is a closed JSON file read with mode `0600`, owned by the
service UID, one link and no symlink. Unknown or missing keys refuse startup
before any database or Docker connection.

- Launcher configuration names the instance UUID, credential epoch, bind
  address and port, journal directory, wrapper-profile file, image repository
  and the worker-facing TLS files (CA, server certificate, key and exact peer
  DNS).
- Worker configuration names the PostgreSQL secret-file path and pool size, the
  worker UUID, credential epoch, instance UUID, realm digest, API-facing TLS,
  launcher-facing TLS and address, handoff bind address and port, journal
  directory, source descriptor catalog and wrapper-profile file.
- The launcher image must contain the Docker CLI and the compose fragment adds
  the operator's Docker socket group through `KURAFOLIO_DOCKER_GID`. The socket
  is not readable by UID 10001 by default; provisioning the group is an operator
  step. A launcher image without the CLI refuses before starting.
- The launcher image creates `/var/lib/kurafolio-launcher` and
  `/var/lib/kurafolio-worker` with owner `10001:10001` and mode `0700`, so fresh
  named volumes inherit the right owner and need no manual setup. A different
  image must do the same or the service refuses to start.
- Secret key files are never group- or world-readable. No secret value is
  passed through an environment variable, command line or image layer.
- The launcher mounts the Docker socket and its own journal volume. The worker
  mounts only its own journal volume; it has no Docker socket and no financial
  volume.
- Activating an instance (wrapper catalog, budgets, worker row, `ready`) is
  IMP-007S's operator command. Until it lands, activation is possible only on a
  test instance seeded through the operator role.

Keep both journal volumes. The worker journal holds one create-only record per
attempt with set, job, member, fence and the launcher handle once known. The
launcher journal holds only digests and the exact engine ID. It never holds raw
bytes, context, results, stderr, a plaintext nonce or a plaintext handle.

## Recovery and known limits

- A worker crash leaves the member `receiving` or `normalizing`. The recovery is
  to cancel the set or let it expire, until the fenced sweep ticket lands. The
  new worker does not reuse the old handoff token.
- A record without a launcher handle can produce no proof. Its set stays
  `cleanup_pending` and keeps the slot and storage until an operator acts.
- A cleanup that cannot prove child and payload absence keeps the storage
  reservation and reports `cleanup_pending` or `failed`. A later claim retries
  after the database backoff.
- A launcher restart kills and removes only its exact journaled engine IDs, or
  finds a create-before-journal container by the exact instance and nonce labels.
  Late output is discarded. Records remain until the worker sends `forget` after
  `finished` with `cleanup_complete: true`.
- After a credential epoch change, controls from the old epoch are refused.
  Attempts from before the rotation get no proof and their sets stay
  `cleanup_pending`.
- Until IMP-007V, a set whose members normalize stays `NORMALIZING`. It holds
  its storage reservation until the user cancels it or it expires, and cleanup
  then purges it.

## Containment evidence

The child profile is fixed: UID/GID `10001:10001`, read-only root, network and
IPC `none`, `cap-drop ALL`, `no-new-privileges`, a 32 MiB `noexec,nosuid,nodev`
tmpfs at `/tmp`, 256 MiB memory and swap, one CPU, 16 PIDs, RLIMIT_CPU 2 s,
nofile 64, core 0, and exactly eight environment variables. The entry point is
`/usr/bin/env -i` with `python -I` on the fixed child script.

The table records what was actually run. A configuration value alone is not
evidence. `tests/test_ingestion_containment.py` builds an offline probe image
from an immutable local base (`--network none`) and starts it with the exact
engine arguments.

| Control | Docker Desktop, Apple Silicon | Native Linux CI |
|---|---|---|
| Network | verified (2026-11-24, engine 29.6.1, `test_ac_06_network_and_filesystem_denials`) | not tested |
| Read-only root | verified (2026-11-24, engine 29.6.1, `test_ac_06_network_and_filesystem_denials`) | not tested |
| User 10001:10001 | verified (2026-11-24, engine 29.6.1, `test_ac_02_effective_profile_and_environment`) | not tested |
| Capabilities dropped | verified (2026-11-25, engine 29.6.1, `test_ac_02_effective_profile_and_environment`: `CapEff` 0) | not tested |
| No-new-privileges | verified (2026-11-25, engine 29.6.1, `test_ac_02_effective_profile_and_environment`: `NoNewPrivs` 1) | not tested |
| IPC none | not tested (HostConfig only; no effective namespace probe) | not tested |
| PIDs limit 16 | verified (2026-11-25, engine 29.6.1, `test_ac_02_effective_profile_and_environment`; `test_ac_06_pids_limit_stops_a_fork_bomb`) | not tested |
| Memory and swap 256 MiB | verified (2026-11-24, engine 29.6.1, `test_ac_02_effective_profile_and_environment`; `test_ac_06_resource_and_output_limits`) | not tested |
| CPU 1 quota | not tested (HostConfig only; RLIMIT_CPU is separate) | not tested |
| RLIMIT_CPU 2 s | verified (2026-11-24, engine 29.6.1, `test_ac_02_effective_profile_and_environment`) | not tested |
| nofile 64 | verified (2026-11-24, engine 29.6.1, `test_ac_02_effective_profile_and_environment`) | not tested |
| core 0 | verified (2026-11-24, engine 29.6.1, `test_ac_02_effective_profile_and_environment`) | not tested |
| tmpfs flags | verified (2026-11-24, engine 29.6.1, `test_ac_02_effective_profile_and_environment`) | not tested |
| Environment (eight variables) | verified (2026-11-24, engine 29.6.1, `test_ac_02_effective_profile_and_environment`) | not tested |
| Docker socket absent | verified (2026-11-24, engine 29.6.1, `test_ac_02_effective_profile_and_environment`) | not tested |
| Output limits | verified (2026-11-24, engine 29.6.1, `test_ac_06_resource_and_output_limits`) | not tested |
| Wall clock 10 s | verified (2026-11-24, engine 29.6.1, `test_ac_06_resource_and_output_limits`) | not tested |
| Real child, default entry point | verified (2026-11-26, engine 29.6.1, `test_ac_02_real_child_parses_the_two_public_examples`: both public examples, admission counts and exact HostConfig; PostgreSQL row `test_ac_02_real_child_reaches_stage_admitted_through_the_worker`) | not tested |

`launcher check` prints the HostConfig of a container it creates but never starts.
Those rows are configuration-only and are not counted as verified here; only the
runtime probes above are. Rows marked "not tested" have no effective probe yet.

Native-discovery members are rejected with `import_evidence_unsupported` before
any launch until native discovery lands in the child (IMP-007Z).

Native Linux CI has not run this matrix in this session. Docker Desktop runs the
containers in a Linux VM; this evidence is not host-root or native-macOS sandbox
proof. The launcher remains trusted host-level authority.

The offline build uses a cached local base and a generated probe script; it adds
no image tag, pull, dependency or lock-file change to the repository. No
financial workspace or private data is mounted into any probe.

## Failure and refusal codes

The worker and launcher use the closed r7 codes. A refused handoff returns the
fixed HTTP status with `{"code": <code>}` and nothing else. Framing, peer,
profile, credential-epoch and ownership mismatches never create a container.
Logs carry only the method, path, status and fixed code, never headers, bodies,
tokens, nonces, certificates or child output.

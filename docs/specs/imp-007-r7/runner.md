# Trusted isolated execution boundary

B07-02/08 select a dedicated ingestion worker and a separate trusted launcher on an operator-approved existing Docker engine. [protocol-appendix.md](protocol-appendix.md) and [wire-contracts.json](wire-contracts.json) fix peers, frames, image/profile authority, quotas, deadlines, cancellation and restart behavior. The old 006 fixture remains TEST_ONLY.

API has neither the worker DB role nor launcher peer credential. Worker has only restricted work-function access and an authenticated private launcher channel, with no Docker socket. Launcher has runtime control and a separate opaque ownership journal, but no financial DB credentials/volumes. Child has neither authority nor private mounts/network; only bounded raw and minimal parser/discovery context. Operator-reviewed images/wrappers are pinned; no browser code install, arbitrary arguments, automatic image pull or source-specific financial branch.

Launcher compromise remains significant: rootful Docker daemon control can affect its Linux host. Docker Desktop's Linux VM/shared resources have a different boundary from native host root. A restricted JSON endpoint does not remove runtime-control trust. Support requires actual effective Linux-container controls on the exact image/architecture/engine; Docker availability alone is insufficient. Desktop VM rows need separate evidence, and native Windows containers are unsupported.

Cancel/restart/recovery touches only exact owned container IDs plus verified instance/nonce/fence labels. No broad kill/prune/name-based adoption. Late/expired/cross-peer output is rejected. Raw/results are never put in the journal. Cleanup failure is visible and retains capacity reservations until absence is proved. Stage admission and financial acceptance remain separate authorities.

This is a contract candidate. No image/service/key/socket/volume has been built, created or changed during planning. Native containment and adverse-resource probes must actually execute under an independently accepted implementation plan before readiness is claimed.


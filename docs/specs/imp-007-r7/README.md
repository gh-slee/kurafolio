# IMP-007 r7 contract bundle (published subset)

This directory holds the parts of the frozen IMP-007 revision 7 ("r7") contract
bundle that open tickets cite. The IMP-007 tickets record the owner's approval of
"IMP-007 spec r7" in `gate_approval`; these files are the contract that approval
refers to. They were published by ENG-114 so that an agent on any machine can read
them. The full bundle stays local to the owner's machine.

Each source file was checked against the bundle's own manifest before copying, and
all 20 matched the frozen r7 hashes. Every file is an exact copy except
`decisions.md`, described below.

## Files

| File | Included because | Copy | Published SHA-256 |
|---|---|---|---|
| [spec.md](spec.md) | cited | exact | `be7cf080b917c9bcaa17354ff68aff0baf0ed66911c62c8a66bc3b85afb1589d` |
| [sql-appendix.md](sql-appendix.md) | cited | exact | `5f17239e149a15ccb5543ce38b10c27a0f5aef0d7283a597eb864b08e8a67ff7` |
| [sql-inventory.json](sql-inventory.json) | cited | exact | `2e6b98eb4874707b112c54596a55dd1e778ff2a1976b447811b46ef651e0784a` |
| [contract-appendix.md](contract-appendix.md) | cited | exact | `91de06ad24dc5a31492895c8559a54892fbc5966cbd542829fa531be6602f10f` |
| [acceptance.md](acceptance.md) | cited | exact | `f32af284fbdf3e5cbdfeea5324f953f19c8c40cde295f643c3ee9a94d5b5cee0` |
| [runner.md](runner.md) | cited | exact | `af43e9605c0c459909b6b5f329f952b03dd4c4ec18d94fd5ae0733d26cd05ceb` |
| [r7-native-policy.md](r7-native-policy.md) | cited | exact | `8244de5c730eee2d8b3daaf737e29ffe19283f6bec50d96dc9f3f266b9b2f5af` |
| [protocol-appendix.md](protocol-appendix.md) | cited | exact | `a875b3cdaffe11fc0ebd9674124e919f89b16b815c589983a3c167d61600e14a` |
| [wire-contracts.json](wire-contracts.json) | cited | exact | `a7a228a6e2ec1df73c2598aaa878aab164c65c414ee2bf56d7534befb0f24693` |
| [ingestion-api.md](ingestion-api.md) | cited | exact | `1e519e5982bb3cdd13b64f2876a6f0bc09ee6a2c4bc0d1fc94a37955c16baa01` |
| [failure-restore.md](failure-restore.md) | cited | exact | `6acb8cf2e1e4bb5796e9da103dcd12027cf171769a6e2fa1627f5005c7b33540` |
| [oracle.json](oracle.json) | cited | exact | `6ab9a7fd08d1780fe4dafe7de610606754f3feda9a8ba888e4094a2a4c6fe8d4` |
| [reconciliation.md](reconciliation.md) | cited | exact | `7c47e651b9a25ccd0ab28474de179d79be4855b40a92b46eab30fc86d938c858` |
| [decisions.md](decisions.md) | a cited file delegates to it | edited, see below | `0e4be06c5f73dc40675538cdb607f8264ebffdc8b05946aa8219614e614904cc` |
| [persistence.md](persistence.md) | a cited file delegates to it | exact | `2786bb71de65fe53852222afa5ea1513e74acbaf8ecf9bd0e223cb5fcb38fc84` |
| [normalized-evidence.md](normalized-evidence.md) | a cited file delegates to it | exact | `665991e057a1095e4269313d6668fdd6cdf3238507d4bdce7917438584392499` |
| [fixture-appendix.md](fixture-appendix.md) | a cited file delegates to it | exact | `7e445184d9ca833e2f2986ab6316544e6bd072359eedeee249b56fcb236a632d` |
| [codec-schema.json](codec-schema.json) | a cited file delegates to it | exact | `ef0a5f1ddc578de6caa66bac0b60b1f95bfad6322743389413b72c3cd328907f` |
| [frozen-shapes.json](frozen-shapes.json) | a cited file delegates to it | exact | `01a083297ed5a11a866ded265c34b44f8852fca33e1a031ec25b8f400147e213` |
| [fixtures/case-matrix.json](fixtures/case-matrix.json) | a cited file delegates to it | exact | `0e97619486ea517963c4d916724d53c403825fa8199a5c8c355e65370bf8f026` |

## Changes from the source

- `decisions.md`, line 3: the references to the private approval records (an
  approval call identifier, a sealed earlier bundle hash and private receipts)
  were replaced by a one-line publication note. The selected directions B07-01 to
  B07-08 and every other line are unchanged.

## Not published

These bundle files stay local. No open ticket cites them:

- Review and approval history: `README.md` of the bundle, `manifest.json`,
  `review-brief.md`, `review-summary.md`, `draft-quality-review.md`,
  `r5-repairs.md`, `r6-repairs.md`, `r4-repair-map.json`, `r5-repair-map.json`,
  `r7-repair-impact.json`, `scope.json` and `traceability.json`.
- Local implementation evidence: `implementation-snapshot.json` and
  `source-baseline.json`.
- Fixtures: 139 of the 141 files under `fixtures/` are already tracked. The test
  vector file [tests/fixtures/ingestion/oracle.json](../../../tests/fixtures/ingestion/oracle.json)
  holds each of them under its file name, with equal content (JSON compared as
  parsed values, CSV as text). `fixtures/case-matrix.json` is published here.
  `fixtures/r5-fixture-status.json` is r5 history and stays local.

Links inside the published files to the files above do not resolve.

## Relationship to the tracked test vectors

`tests/fixtures/ingestion/oracle.json` is the test vector set the implementation
uses. It also has `sql-inventory` and `codec-shapes` keys whose content differs from
[sql-inventory.json](sql-inventory.json) and [codec-schema.json](codec-schema.json)
here. The r7 oracle in this directory is a different file: it records the
acceptance cases and their expected outcomes. Where the two disagree, the files in
this directory are the contract the tickets cite. ENG-114 does not reconcile them.

## Changing these files

These files set expected values for the tickets that cite them. Tickets link this
README with its SHA-256, and the table above gives each file's SHA-256. Changing any
file here changes the spec of every ticket that cites it, so those tickets need the
owner's approval again before anyone builds against the new text. A new contract
revision belongs in a new directory, not in edits to this one.

# ⚠️ DRAFT — DESIGN PREVIEW

# Unified GIS Agent Gateway v0.3 — Design Preview (Not Final)

> **Status: DRAFT / DESIGN PREVIEW.** Everything in this directory is a work-in-progress design record, published early for transparency and feedback. It is **not** a release, and the contracts described here are **not final**.

This directory holds the design trail of the **unified GIS agent gateway v0.3** — the worklist, the draft per-verb semantic contracts and their review, the registry capability-tiering log, and two rounds of SuperMap API reconciliation notes.

## Contents

| File | What it is |
|---|---|
| `V03-WORKLIST-V2-GENERALIZED-20261103.md` | The current v0.3 worklist (generalized edition): build batches, governing rules, and the generalization principle — unified verbs and semantics across platforms, platform differences sunk into the adapter layer. |
| `G1-CONTRACTS-DRAFT-20261103.md` | First batch of the per-verb semantic contract set: a 14-field contract template plus 10 fully drafted core-verb contracts. Draft status. |
| `G1-REVIEW-20261103.md` | Muse's review of the contract draft: verdict **ACCEPT_WITH_NOTES**, with item-by-item rulings on all 15 open questions and the prerequisites for finalization. |
| `G3-TAGGING-CHANGELOG-20261103.md` | Changelog of the registry capability tiering (core / extended / exclusive) applied to the gateway leaf registry, including the V32 status repair. |
| `B1-RECONCILIATION-20261103.md` | SuperMap (iobjectspy 10.1.0) interface reconciliation, round 1: module-level cross-check of unverified registry leaves against a full API surface dump. |
| `B1-RECONCILIATION-R2-20261103.md` | Round 2 (closing round): class-level introspection that graded the remaining leaves and closed the B1 account. |

## What is deliberately NOT included here

- **Gateway code and the leaf registry** are not part of this preview. They will be published with the formal release after the December batch-1 on-machine calibration round.
- The registry ledger is currently being reconciled and refreshed; final figures will ship with the release.
- The contracts in `G1-CONTRACTS-DRAFT-20261103.md` are **drafts** (review verdict: ACCEPT_WITH_NOTES). The prerequisites for calling them final — including the FieldSpec fidelity matrix, the Z/M behavior matrix, and the naming-constraint matrix — are listed in `G1-REVIEW-20261103.md`.

---

中文说明：本目录为统一 GIS Agent 网关 v0.3 的设计预览（未定版），仅含设计文档；代码与注册表将于 12 月实机校准后随正式版发布。

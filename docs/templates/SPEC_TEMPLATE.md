---
id: SPEC-NNN
title: <capability name>
status: Draft | Ready | Blocked | Done
phase: <build phase from SHIPPABLE_SCOPE §11>
pillar: <1-5 or "foundation">
scope_refs: ["§x"]
adrs: [ADR-NNNN]
depends_on: [SPEC-NNN]
---

# SPEC-NNN: <title>

## 1. Purpose
Two or three sentences. What user-visible or system-visible outcome exists when this spec is done.

## 2. Scope and non-goals
**In:** ...
**Out:** ... (point to the spec or "not in v1" item that owns it)

## 3. Requirements
Each requirement has a stable ID `SPEC-NNN-Rnn`, uses MUST / SHOULD / MAY, and is testable.

| ID | Requirement | Priority |
|---|---|---|

## 4. Interfaces and data
Commands, payloads, tables or events this spec owns or touches. Link to SPEC-011 for table definitions.

## 5. Acceptance scenarios
Each scenario `AC-NNN-nn` names the requirement IDs it proves and its test level (unit, integration, golden, e2e, manual).

## 6. Open questions
`OQ-NNN-n`: question, owner, how to resolve, what it blocks.

## 7. Traceability
Scope sections, ADRs, invariants (section 14 of SHIPPABLE_SCOPE.md), other specs.

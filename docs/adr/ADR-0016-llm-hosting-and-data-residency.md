---
id: ADR-0016
title: LLM hosting and personal-data residency (open)
status: Proposed
date: 2026-10-11
deciders: Varun
scope_refs: ["§4", "§13", "§14 inv. 7"]
specs: [SPEC-006, SPEC-012, SPEC-013]
---

# ADR-0016: LLM hosting and personal-data residency (open)

## Context
Options from the scope document:
| Option | Trade-off |
|---|---|
| Local small model on the VPS | Data stays put; poor CPU latency; workable only with the timeout and template fallback. |
| Russian-hosted LLM API (for example GigaChat, YandexGPT; verify terms) | Better latency; data stays in-country. |
| Foreign API | Conflicts with the data-location question. Avoid unless verified acceptable. |

152-ФЗ treatment of operator names and chat ids is **unverified** and may also constrain hosting and STT.

## Decision (pending)
Decide after RAM and latency measurements on the target VPS, and after the data-location check. Constraints that apply whatever is chosen:
- the pipeline depends on an `LlmClient` interface only;
- no operator text goes to a foreign API without a documented decision (invariant 7);
- LLM payloads are minimised to facts needed for phrasing (see SPEC-006-R11).

## Consequences
**Good:** the LLM is optional in v1, so this decision does not block shipping the deterministic product.
**Costs and risks:** this blocks only the LLM go-live gate (phase 6).

## Alternatives considered
See table.

## Revisit when
Not applicable until accepted.

## Enforced by
SPEC-006-R12. Blocks SPEC-006 LLM go-live.

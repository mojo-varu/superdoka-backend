## Spec-driven development rules (SuperDoka v1)

Before changing code, read `docs/README.md`, the relevant `docs/specs/SPEC-*.md`, the ADRs it lists, and the ten "must never do" rules in `ARCHITECTURE_VERBALIZED.md`.

1. Work only on requirements in a spec whose status is Ready. For a Blocked spec, build only the parts that do not depend on the blocking ADR or open question.
2. Do not implement anything that is not traceable to a `SPEC-NNN-Rnn` requirement. If you think something is missing, propose a spec change instead of coding it.
3. Write tests from the `AC-` scenarios first. Reference requirement IDs in commit messages.
4. Never edit the decision of an Accepted ADR. Propose a new ADR that supersedes it.
5. If a spec is ambiguous or conflicts with another document, stop and report the conflict. Do not guess.
6. Do not build anything marked "later" in `SHIPPABLE_SCOPE.md` §15, and do not add proactive rules or LLM allowlist entries without updating ADR-0010 or ADR-0003 and the spec first.
7. Treat values labelled "starting value" as configuration, not constants.
8. Run `python3 docs/tools/check_docs.py --write` before finishing, and keep `docs/TRACEABILITY.md` in the commit.
9. Never mark a spec Done unless every MUST requirement has a passing scenario.

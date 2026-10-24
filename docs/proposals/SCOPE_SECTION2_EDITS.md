# Proposed edits — SHIPPABLE_SCOPE.md §2

Status: proposed, and already applied to `SHIPPABLE_SCOPE.md` in this commit, because
every change below is a factual correction about the current state of the repo, not a
product scope decision. Evidence re-verified against the live code on 2026-10-24 (not
just copied from `MVP_ASSESSMENT_FOR_CLAUDE.md`, though that memo's findings all held).

## What was wrong and the evidence

1. **"ONNX intent classifier and NER extractor" listed as Working.** False today.
   `find . -iname "*.onnx" -o -iname "*distilbert*"` returns nothing in the repo.
   `app/core/model_loader.py:219` returns `"llm_only"` as the mode, and lines 67/77 log
   `"CLASSIFIER_MODEL_PATH not set — using LLM for intent"` /
   `"NER_MODEL_PATH not set — using LLM for extraction"`. Extraction runs entirely
   through the LLM (`app/core/context_llm.py`), not the fine-tuned ONNX pair.

2. **"T1/T2/T8 style template replies" listed as Working.** T8 is not reachable, so
   this overstates it. `app/core/task_router.py`'s owner-directed branch (which
   produces T7/T8) requires `recipient="owner"`. The only caller,
   `app/core/intelligence_router.py:530`, hardcodes `recipient="operator"`. Grepped
   every call site of `task_route()` and `run_intelligence()` — `is_proactive` is
   never passed `True` anywhere either, so T5/T6 are equally unreachable. Only T1–T4
   fire in production.

3. **"The watcher was designed but is not running" undersells the gap.** The watcher
   process does run (two asyncio loops), but its nudge delivery is an unimplemented
   stub: `app/services/watcher.py:194` is `# TODO: send via adapter`, and
   `_get_owner_settings` (`watcher.py:189-191`) always returns `None`. Nudges are
   computed and logged, never sent.

4. **"`fuel_today` and `hours_today` ... missing date filter" understates the bug.**
   There is no reset mechanism at all, not merely a missing filter.
   `app/db/models.py:470-471` (`fuel_added_today`, `hours_worked_today`) are
   incremented with a plain `+=` in `app/services/event_processor.py:511,515` and
   never cleared by any cron, watcher task, or stored "last reset" column — they
   accumulate across calendar days indefinitely.

5. **New finding, not previously in this section: corrections are write-only.**
   `POST /correct/{event_id}` (`app/api/v1/endpoints/vfm.py:130-165`) writes an
   immutable `CORRECTION` `TimelineEvent`. Grepped the whole repo for `CORRECTION` —
   it is written in exactly one place and read back nowhere. It does not feed
   confidence calibration, thresholds, or flag unreliable extractions.

6. **99.3% accuracy caveat understates the gap.** It is not just "unvalidated on real
   operator language" — no evaluation script or test set exists anywhere in this
   repo. `find . -iname "*eval*.py" -o -iname "*accuracy*"` returns nothing. The
   number cannot currently be reproduced or audited by anyone.

## Applied edit

See `SHIPPABLE_SCOPE.md` §2 in this commit for the corrected text. Summary of the
diff: removed the ONNX classifier/NER claim from Working and replaced it with
"LLM-only extraction"; narrowed the T1/T2/T8 claim to T1/T2; added the T5–T8
unreachability finding, the watcher-stub evidence, the sharpened date-counter
description, the write-only-corrections finding, and the sharpened accuracy caveat,
each with path:line evidence inline so a future reader does not have to re-derive it.

No line in §1, §3–§17 was touched. This is strictly a §2 factual correction.

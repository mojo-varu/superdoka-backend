"""
app/core/model_loader.py
========================
Singleton loader for the two NLP models.
Called once at FastAPI startup via lifespan.

If model files are absent, the pipeline falls back to LLM-only mode.
This means the backend always starts cleanly regardless of model state.

Environment variables:
  CLASSIFIER_MODEL_PATH  path to ONNX intent classifier directory
  NER_MODEL_PATH         path to ONNX NER extractor directory

Both default to None (LLM-only mode) if not set.
"""

import json
import logging
import os
import threading
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# ── Module-level singletons ───────────────────────────────────────────────────
_clf_pipeline  = None
_ner_pipeline  = None
_clf_labels:   list[str] = []
_ner_labels:   list[str] = []
_intent_slots: dict[str, list[str]] = {}
_load_lock     = threading.Lock()
_loaded        = False


def load_models(blocking: bool = False) -> None:
    """
    Load both models into module-level singletons.
    Non-blocking by default — loads in a background thread.
    Set blocking=True for tests.
    """
    if blocking:
        _do_load()
    else:
        threading.Thread(target=_do_load, daemon=True).start()


def _do_load() -> None:
    global _clf_pipeline, _ner_pipeline, _clf_labels, _ner_labels
    global _intent_slots, _loaded

    with _load_lock:
        if _loaded:
            return

        clf_path = os.getenv("CLASSIFIER_MODEL_PATH")
        ner_path = os.getenv("NER_MODEL_PATH")

        if clf_path and Path(clf_path).exists():
            try:
                _clf_pipeline, _clf_labels = _load_classifier(Path(clf_path))
                logger.info(f"Intent classifier loaded from {clf_path} "
                            f"({len(_clf_labels)} classes)")
            except Exception as e:
                logger.warning(f"Classifier load failed — LLM fallback active: {e}")
        else:
            logger.info("CLASSIFIER_MODEL_PATH not set — using LLM for intent")

        if ner_path and Path(ner_path).exists():
            try:
                _ner_pipeline, _ner_labels, _intent_slots = _load_ner(Path(ner_path))
                logger.info(f"NER extractor loaded from {ner_path} "
                            f"({len(_ner_labels)} labels)")
            except Exception as e:
                logger.warning(f"NER load failed — LLM fallback active: {e}")
        else:
            logger.info("NER_MODEL_PATH not set — using LLM for extraction")

        _loaded = True


def _load_classifier(model_dir: Path):
    """Load ONNX sequence classifier using onnxruntime directly — no PyTorch needed."""
    import numpy as np
    import onnxruntime as ort
    from transformers import AutoTokenizer

    tokenizer = AutoTokenizer.from_pretrained(str(model_dir))
    sess = ort.InferenceSession(
        str(model_dir / "model.onnx"),
        providers=["CPUExecutionProvider"],
    )

    with open(model_dir / "labels.json", encoding="utf-8") as f:
        labels = json.load(f)

    def clf_pipeline(texts):
        """Minimal classifier pipeline — returns list of {label, score} dicts."""
        if isinstance(texts, str):
            texts = [texts]
        results = []
        for text in texts:
            enc = tokenizer(text, return_tensors="np", truncation=True,
                            max_length=64, padding=True)
            inputs = {k: v for k, v in enc.items()
                      if k in [i.name for i in sess.get_inputs()]}
            logits = sess.run(None, inputs)[0][0]
            exp    = np.exp(logits - logits.max())
            probs  = exp / exp.sum()
            idx    = int(probs.argmax())
            results.append({"label": labels[idx], "score": float(probs[idx])})
        return results

    logger.info("  Classifier: ONNXRuntime (no PyTorch required)")
    return clf_pipeline, labels


def _load_ner(model_dir: Path):
    """Load ONNX token classifier using onnxruntime directly — no PyTorch needed."""
    import numpy as np
    import onnxruntime as ort
    from transformers import AutoTokenizer

    tokenizer = AutoTokenizer.from_pretrained(str(model_dir))
    sess = ort.InferenceSession(
        str(model_dir / "model.onnx"),
        providers=["CPUExecutionProvider"],
    )

    with open(model_dir / "labels.json", encoding="utf-8") as f:
        labels = json.load(f)

    intent_slots: dict = {}
    slots_path = model_dir / "intent_slots.json"
    if slots_path.exists():
        with open(slots_path, encoding="utf-8") as f:
            intent_slots = json.load(f)

    def ner_pipeline(text: str) -> list[dict]:
        """
        Minimal NER pipeline — returns list of entity dicts compatible
        with the reassemble() function in intelligence_router.py.
        Applies simple aggregation: consecutive same-label tokens merged.
        """
        enc      = tokenizer(text, return_tensors="np", truncation=True,
                             max_length=64, return_offsets_mapping=True)
        word_ids = enc.word_ids(batch_index=0)
        inputs   = {k: v for k, v in enc.items()
                    if k in [i.name for i in sess.get_inputs()]}
        logits   = sess.run(None, inputs)[0][0]  # (seq_len, num_labels)

        exp   = np.exp(logits - logits.max(axis=-1, keepdims=True))
        probs = exp / exp.sum(axis=-1, keepdims=True)
        preds = probs.argmax(axis=-1)

        # Convert token predictions to entity list
        results   = []
        prev_word = None
        for idx, word_id in enumerate(word_ids):
            if word_id is None or word_id == prev_word:
                prev_word = word_id
                continue
            label = labels[int(preds[idx])]
            if label == "O":
                prev_word = word_id
                continue
            token = tokenizer.convert_ids_to_tokens(
                int(enc["input_ids"][0][idx])
            )
            score = float(probs[idx].max())
            # Group into entity_group (strip B-/I- prefix)
            entity_group = label[2:] if label.startswith(("B-", "I-")) else label
            # Merge with previous if same group
            if results and results[-1]["entity_group"] == entity_group:
                results[-1]["word"] += token.replace("##", "")
                results[-1]["score"] = min(results[-1]["score"], score)
            else:
                results.append({
                    "entity_group": entity_group,
                    "word":         token.replace("##", ""),
                    "score":        score,
                })
            prev_word = word_id

        return results

    logger.info("  NER: ONNXRuntime (no PyTorch required)")
    return ner_pipeline, labels, intent_slots


# ── Public accessors ──────────────────────────────────────────────────────────

def get_classifier():
    """Returns (pipeline, labels) or (None, []) if not loaded."""
    return _clf_pipeline, _clf_labels


def get_ner():
    """Returns (pipeline, labels, intent_slots) or (None, [], {}) if not loaded."""
    return _ner_pipeline, _ner_labels, _intent_slots


def models_ready() -> dict:
    """Returns status dict — used by health endpoint."""
    return {
        "classifier": _clf_pipeline is not None,
        "ner":        _ner_pipeline is not None,
        "mode":       _infer_mode(),
    }


def _infer_mode() -> str:
    clf_ok = _clf_pipeline is not None
    ner_ok = _ner_pipeline is not None
    if clf_ok and ner_ok:
        return "full"        # stages 1-4 all active
    if clf_ok:
        return "clf+llm"    # classifier + LLM extraction + LLM agency
    return "llm_only"       # current behaviour, unchanged

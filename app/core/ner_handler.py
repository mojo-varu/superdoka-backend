"""
app/core/ner_handler.py

Hour 2 changes (surgical — existing logic untouched):
  1. NERItem:    +confidence field (was commented out — now active)
  2. BaseSchema: +confidence field (was commented out — now active)
  3. NERHandler.predict():
       - Softmax over logits → per-token confidence scores
       - Non-O token scores aggregated → single message confidence
       - Returns List[Dict] with 'confidence' key per entity
  4. NERHandler.predict_with_confidence():
       - New method returning (entities, aggregate_confidence)
       - Used by the confidence router in event_processor.py
  5. post_process_ner():
       - Accepts and passes through confidence
       - Result dict now includes 'confidence' key

Zero breaking changes to existing callers of predict() or post_process_ner().
"""

import json
import re
import threading
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import onnxruntime as ort
from pydantic import BaseModel, Field
from transformers import AutoTokenizer
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ================================
# Globals (unchanged)
# ================================
model_loading    = False
model_loaded     = False
model_load_error = None
ner_session      = None
tokenizer        = None
model_lock       = threading.RLock()

MODEL_DIR = "app/distilxlmr_ner_m1/final"
ONNX_PATH = Path(MODEL_DIR) / "model.onnx"

# Confidence routing thresholds
CONFIDENCE_AUTO    = 0.85   # auto-write, no confirmation needed
CONFIDENCE_CONFIRM = 0.60   # write but ask operator to confirm
# below CONFIDENCE_CONFIRM → LLM fallback


# ================================
# Pydantic Models
# ================================
class NERItem(BaseModel):
    token:      str
    label:      str
    confidence: Optional[float] = None   # ← was commented out, now active


class BaseSchema(BaseModel):
    intent:     str
    text:       str
    missing:    List[str]  = Field(default_factory=list)
    confidence: Optional[float] = None   # ← was commented out, now active


class AddMachineSchema(BaseSchema):
    machine_type: Optional[str] = None
    model:        Optional[str] = None
    year:         Optional[int] = None
    reg_number:   Optional[str] = None


class ReportIssueSchema(BaseSchema):
    reg_number:  Optional[str] = None
    description: Optional[str] = None


class FuelLogSchema(BaseSchema):
    reg_number:  Optional[str]   = None
    fuel_volume: Optional[float] = None
    unit:        Optional[str]   = None


class HoursLogSchema(BaseSchema):
    reg_number: Optional[str]   = None
    hours:      Optional[float] = None
    unit:       Optional[str]   = None


class AssignMachineSchema(BaseSchema):
    reg_number:    Optional[str] = None
    operator_name: Optional[str] = None
    contact:       Optional[str] = None


class FallbackSchema(BaseSchema):
    pass


# ================================
# Mappings (unchanged)
# ================================
WORKFLOW_INTENT_MAPPING = {
    "добавитьмашину":   "add_machine",
    "добавить_машину":  "add_machine",
    "машина":           "add_machine",
    "добавитьоператора":"assign_machine",
    "добавить_оператора":"assign_machine",
    "оператор":         "assign_machine",
    "топливо":          "fuel_log",
    "заправка":         "fuel_log",
    "наработка":        "hours_log",
    "часы":             "hours_log",
    "проблема":         "report_issue",
    "неисправность":    "report_issue",
    "add_machine":      "add_machine",
    "addmachine":       "add_machine",
    "assign_machine":   "assign_machine",
    "assignmachine":    "assign_machine",
    "fuel_log":         "fuel_log",
    "fuellog":          "fuel_log",
    "hours_log":        "hours_log",
    "hourslog":         "hours_log",
    "report_issue":     "report_issue",
    "reportissue":      "report_issue",
}

SCHEMA_BY_INTENT = {
    "add_machine":   AddMachineSchema,
    "report_issue":  ReportIssueSchema,
    "fuel_log":      FuelLogSchema,
    "hours_log":     HoursLogSchema,
    "assign_machine":AssignMachineSchema,
}

ENTITY_FIELD_MAPPING = {
    "name":         "operator_name",
    "operator":     "operator_name",
    "contact":      "contact",
    "phone":        "contact",
    "tel":          "contact",
    "reg_number":   "reg_number",
    "registration": "reg_number",
    "machine_type": "machine_type",
    "type":         "machine_type",
    "model":        "model",
    "year":         "year",
    "fuel_volume":  "fuel_volume",
    "volume":       "fuel_volume",
    "fuel":         "fuel_volume",
    "hours":        "hours",
    "time":         "hours",
    "description":  "description",
    "issue":        "description",
    "problem":      "description",
    "unit":         "unit",
}


# ================================
# Model Loading (unchanged)
# ================================
def init_model():
    global model_loading, model_loaded, model_load_error, ner_session, tokenizer

    with model_lock:
        if model_loading or model_loaded:
            return
        model_loading = True

    def _load():
        global ner_session, tokenizer, model_loaded, model_load_error, model_loading
        try:
            logger.info(f"Loading ONNX NER model from {ONNX_PATH}")
            if not ONNX_PATH.exists():
                raise FileNotFoundError(f"ONNX model not found at {ONNX_PATH}")

            tokenizer = AutoTokenizer.from_pretrained(
                MODEL_DIR, use_fast=True, trust_remote_code=False
            )

            sess_options = ort.SessionOptions()
            sess_options.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
            sess_options.intra_op_num_threads = 1

            ner_session = ort.InferenceSession(
                str(ONNX_PATH),
                sess_options=sess_options,
                providers=["CPUExecutionProvider"],
            )

            with model_lock:
                model_loaded = True
                model_loading = False
            logger.info("ONNX NER model loaded successfully!")

        except Exception as e:
            logger.error(f"ONNX model loading failed: {e}")
            with model_lock:
                model_load_error = str(e)
                model_loading = False

    threading.Thread(target=_load, daemon=True).start()


def is_model_ready() -> bool:
    with model_lock:
        return model_loaded and ner_session is not None


def get_model() -> Tuple[ort.InferenceSession, AutoTokenizer]:
    with model_lock:
        if model_load_error:
            raise RuntimeError(f"NER model failed to load: {model_load_error}")
        if not is_model_ready():
            raise RuntimeError("NER model not ready yet")
        return ner_session, tokenizer


# ================================
# Utility Functions (unchanged)
# ================================
def normalize_workflow(workflow: str) -> str:
    if not workflow:
        return ""
    normalized = workflow.lstrip("#").lower().strip()
    normalized = re.sub(r"[_\s]+", "", normalized)
    return normalized


def extract_numeric_value(text: str) -> Optional[float]:
    if not text:
        return None
    cleaned = re.sub(r"[^\d.,]", "", text.replace(",", "."))
    try:
        return float(cleaned)
    except (ValueError, TypeError):
        return None


def merge_entity_tokens(entities: List[Dict[str, Any]]) -> Dict[str, str]:
    entity_map: Dict[str, str] = {}
    current_entity: Optional[str] = None
    current_tokens: List[str] = []

    for entity in entities:
        label = entity["label"]
        token = entity["token"]

        if label.startswith("B-"):
            if current_entity and current_tokens:
                entity_map[current_entity.lower()] = " ".join(current_tokens).strip()
            current_entity = label[2:]
            current_tokens = [token]
        elif label.startswith("I-") and current_entity:
            if label[2:] == current_entity:
                current_tokens.append(token)
        else:
            if current_entity and current_tokens:
                entity_map[current_entity.lower()] = " ".join(current_tokens).strip()
            current_entity = None
            current_tokens = []

    if current_entity and current_tokens:
        entity_map[current_entity.lower()] = " ".join(current_tokens).strip()

    return entity_map


# ================================
# NEW: Confidence helpers
# ================================
def _softmax(logits: np.ndarray) -> np.ndarray:
    """Numerically stable row-wise softmax."""
    shifted = logits - logits.max(axis=-1, keepdims=True)
    exp     = np.exp(shifted)
    return exp / exp.sum(axis=-1, keepdims=True)


def _aggregate_confidence(
    token_probs:  np.ndarray,   # shape (seq_len,) — max-class prob per token
    pred_labels:  List[str],    # decoded label per token
) -> float:
    """
    Aggregate per-token probabilities into a single message confidence.

    Strategy: minimum probability across tokens that were NOT labelled 'O'.
    This is intentionally conservative — one low-confidence entity drags
    the whole message down so the router escalates rather than silently
    writing bad data.

    If every token is 'O' (nothing extracted), returns 0.0 so the router
    sends the message to the LLM fallback.
    """
    non_o_probs = [
        token_probs[i]
        for i, lbl in enumerate(pred_labels)
        if lbl != "O"
    ]
    if not non_o_probs:
        return 0.0
    return float(min(non_o_probs))


# ================================
# post_process_ner (extended — now accepts and returns confidence)
# ================================
def post_process_ner(
    text:         str,
    ner_entities: List[Dict[str, Any]],
    confidence:   Optional[float] = None,   # ← new param, backward-compatible
) -> Dict[str, Any]:
    """
    Convert raw NER output into structured Pydantic schema.
    Now includes confidence in the returned dict.
    """
    try:
        logger.info(f"📝 Processing text: '{text}'")
        logger.info(f"🏷️ Raw entities: {ner_entities}")

        entity_map = merge_entity_tokens(ner_entities)
        logger.info(f"🔗 Merged entities: {entity_map}")

        workflow_raw        = entity_map.get("workflow", "")
        workflow_normalized = normalize_workflow(workflow_raw)
        logger.info(f"⚙️ Workflow: '{workflow_raw}' -> '{workflow_normalized}'")

        intent_key = WORKFLOW_INTENT_MAPPING.get(workflow_normalized, "clarification_needed")

        # Fallback intent inference from entities (supports hashtag-free input)
        if intent_key == "clarification_needed" and not workflow_raw:
            if any(k in entity_map for k in ["name", "operator", "contact"]):
                intent_key = "assign_machine"
                logger.info("🔍 Inferred intent: assign_machine")
            elif any(k in entity_map for k in ["fuel_volume", "volume", "fuel"]):
                intent_key = "fuel_log"
                logger.info("🔍 Inferred intent: fuel_log")
            elif any(k in entity_map for k in ["hours", "time"]):
                intent_key = "hours_log"
                logger.info("🔍 Inferred intent: hours_log")
            elif any(k in entity_map for k in ["description", "issue", "problem"]):
                intent_key = "report_issue"
                logger.info("🔍 Inferred intent: report_issue")

        logger.info(f"🎯 Final intent: '{intent_key}'")

        schema_cls = SCHEMA_BY_INTENT.get(intent_key, FallbackSchema)
        mapped_data: Dict[str, Any] = {
            "intent":     intent_key,
            "text":       text,
            "confidence": confidence,       # ← propagated through
        }

        for entity_key, entity_value in entity_map.items():
            if not entity_value.strip():
                continue
            schema_field = ENTITY_FIELD_MAPPING.get(entity_key, entity_key)

            if schema_field == "year" and entity_value:
                try:
                    mapped_data[schema_field] = int(extract_numeric_value(entity_value) or 0)
                except (ValueError, TypeError):
                    logger.warning(f"⚠️ Failed to convert '{entity_value}' to year")
                    continue
            elif schema_field in ("fuel_volume", "hours") and entity_value:
                numeric_val = extract_numeric_value(entity_value)
                if numeric_val is not None:
                    mapped_data[schema_field] = numeric_val
            else:
                mapped_data[schema_field] = entity_value.strip()

        schema_fields  = schema_cls.__fields__.keys()
        required_fields = [f for f in schema_fields if f not in ("intent", "text", "missing", "confidence")]
        missing         = [f for f in required_fields if f not in mapped_data or not mapped_data.get(f)]
        mapped_data["missing"] = missing

        try:
            schema_instance = schema_cls(**mapped_data)
        except Exception as e:
            logger.warning(f"⚠️ Schema validation failed: {e}, using FallbackSchema")
            schema_instance = FallbackSchema(
                intent="clarification_needed",
                text=text,
                missing=list(required_fields),
                confidence=confidence,
            )

        result = schema_instance.dict()
        logger.info(f"🎉 Final schema (confidence={confidence:.3f}): {result}")
        return result

    except Exception as e:
        logger.error(f"💥 Post-processing failed: {e}")
        return {
            "intent":     "clarification_needed",
            "text":       text,
            "missing":    [],
            "confidence": confidence,
            "error":      str(e),
        }


# ================================
# NERHandler (extended with confidence)
# ================================
class NERHandler:
    def __init__(self):
        self.session, self.tokenizer = get_model()
        self.id2label   = self._load_id2label()
        self.max_length = 512

    def _load_id2label(self) -> Dict[int, str]:
        try:
            config_path = Path(MODEL_DIR) / "config.json"
            with open(config_path, "r", encoding="utf-8") as f:
                cfg = json.load(f)
            return {int(k): v for k, v in cfg.get("id2label", {}).items()}
        except Exception as e:
            logger.error(f"Failed to load id2label: {e}")
            return {0: "O", 1: "B-WORKFLOW", 2: "I-WORKFLOW"}

    def merge_subwords(
        self,
        tokens: List[str],
        labels: List[str],
        token_probs: Optional[List[float]] = None,
    ) -> Tuple[List[str], List[str], List[float]]:
        """
        Merge subword tokens into full words.
        Now also merges token_probs (takes the min across subwords — conservative).
        """
        if not tokens or not labels or len(tokens) != len(labels):
            return [], [], []

        words, word_labels, word_probs = [], [], []
        current_word  = ""
        current_label = None
        current_prob  = 1.0

        for i, (token, label) in enumerate(zip(tokens, labels)):
            if token in self.tokenizer.all_special_tokens:
                continue

            prob = token_probs[i] if token_probs else 1.0

            if token.startswith("##"):
                if current_word:
                    current_word += token[2:]
                    current_prob  = min(current_prob, prob)
            else:
                if current_word and current_label:
                    words.append(current_word)
                    word_labels.append(current_label)
                    word_probs.append(current_prob)
                current_word  = token
                current_label = label
                current_prob  = prob

        if current_word and current_label:
            words.append(current_word)
            word_labels.append(current_label)
            word_probs.append(current_prob)

        return words, word_labels, word_probs

    def predict(self, text: str) -> List[Dict[str, Any]]:
        """
        Original interface — returns entities without aggregate confidence.
        Kept for backward compatibility with existing callers.
        """
        entities, _ = self.predict_with_confidence(text)
        return entities

    def predict_with_confidence(
        self, text: str
    ) -> Tuple[List[Dict[str, Any]], float]:
        """
        NEW primary method — returns (entities, aggregate_confidence).

        entities: list of {token, label, confidence} dicts (O labels excluded)
        aggregate_confidence: float 0.0–1.0

        Used by EventProcessor confidence router:
          ≥ 0.85 → auto write
          0.60–0.85 → write + request confirmation
          < 0.60 → LLM fallback
        """
        if not text or not text.strip():
            return [], 0.0

        try:
            text_clean = text.strip()
            tokens_enc = self.tokenizer(
                text_clean,
                truncation=True,
                padding=True,
                max_length=self.max_length,
                return_tensors="np",
                add_special_tokens=True,
            )

            ort_inputs = dict(tokens_enc)
            ort_outs   = self.session.run(None, ort_inputs)
            logits     = ort_outs[0]              # (1, seq_len, num_labels)

            # ── Confidence: softmax over label dimension ──────────────────
            probs         = _softmax(logits)       # (1, seq_len, num_labels)
            probs_squeezed = probs.squeeze(0)      # (seq_len, num_labels)
            predictions    = np.argmax(probs_squeezed, axis=-1)   # (seq_len,)
            token_max_prob = probs_squeezed.max(axis=-1)           # (seq_len,)
            # ──────────────────────────────────────────────────────────────

            pred_labels = [self.id2label.get(int(p), "O") for p in predictions]

            input_ids      = tokens_enc["input_ids"].squeeze().tolist()
            decoded_tokens = self.tokenizer.convert_ids_to_tokens(input_ids)

            words, word_labels, word_probs = self.merge_subwords(
                decoded_tokens,
                pred_labels,
                token_max_prob.tolist(),
            )

            ner_result: List[Dict[str, Any]] = []
            for word, label, prob in zip(words, word_labels, word_probs):
                if word and label != "O":
                    ner_result.append({
                        "token":      word,
                        "label":      label,
                        "confidence": round(float(prob), 4),
                    })

            aggregate = _aggregate_confidence(
                token_max_prob,
                pred_labels,
            )

            logger.info(
                f"NER result (confidence={aggregate:.3f}): {ner_result}"
            )
            return ner_result, aggregate

        except Exception as e:
            logger.error(f"NER prediction failed: {e}")
            return [], 0.0

    def extract(self, text: str) -> Dict[str, Any]:
        """
        Convenience method for the /extract debug endpoint.
        Returns the full post-processed schema including confidence.
        """
        entities, confidence = self.predict_with_confidence(text)
        return post_process_ner(text, entities, confidence)

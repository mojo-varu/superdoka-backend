import threading
import json
import re
from pathlib import Path
from typing import List, Optional, Dict, Any, Tuple
import onnxruntime as ort
from transformers import AutoTokenizer
import numpy as np
from pydantic import BaseModel, Field
import logging

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ================================
# Globals
# ================================
model_loading = False
model_loaded = False
model_load_error = None
ner_session = None
tokenizer = None
model_lock = threading.RLock()

MODEL_DIR = "app/distilxlmr_ner_m1/final"
ONNX_PATH = Path(MODEL_DIR) / "model.onnx"

# ================================
# Pydantic Models
# ================================
class NERItem(BaseModel):
    token: str
    label: str
    # confidence: Optional[float] = None

class BaseSchema(BaseModel):
    intent: str
    text: str
    missing: List[str] = Field(default_factory=list)
    # confidence: Optional[float] = None

class AddMachineSchema(BaseSchema):
    machine_type: Optional[str] = None
    model: Optional[str] = None
    year: Optional[int] = None
    reg_number: Optional[str] = None

class ReportIssueSchema(BaseSchema):
    reg_number: Optional[str] = None
    description: Optional[str] = None

class FuelLogSchema(BaseSchema):
    reg_number: Optional[str] = None
    fuel_volume: Optional[float] = None  # Changed to float for better precision
    unit: Optional[str] = None

class HoursLogSchema(BaseSchema):
    reg_number: Optional[str] = None
    hours: Optional[float] = None  # Changed to float for better precision
    unit: Optional[str] = None

class AssignMachineSchema(BaseSchema):
    reg_number: Optional[str] = None
    operator_name: Optional[str] = None
    contact: Optional[str] = None

class FallbackSchema(BaseSchema):
    pass

# Enhanced mapping with normalization
WORKFLOW_INTENT_MAPPING = {
    # Russian workflows
    "добавитьмашину": "add_machine",
    "добавить_машину": "add_machine",
    "машина": "add_machine",
    "добавитьоператора": "assign_machine",
    "добавить_оператора": "assign_machine",
    "оператор": "assign_machine",
    "топливо": "fuel_log",
    "заправка": "fuel_log",
    "наработка": "hours_log",
    "часы": "hours_log",
    "проблема": "report_issue",
    "неисправность": "report_issue",
    # English workflows
    "add_machine": "add_machine",
    "addmachine": "add_machine",
    "assign_machine": "assign_machine",
    "assignmachine": "assign_machine",
    "fuel_log": "fuel_log",
    "fuellog": "fuel_log",
    "hours_log": "hours_log",
    "hourslog": "hours_log",
    "report_issue": "report_issue",
    "reportissue": "report_issue",
}

SCHEMA_BY_INTENT = {
    "add_machine": AddMachineSchema,
    "report_issue": ReportIssueSchema,
    "fuel_log": FuelLogSchema,
    "hours_log": HoursLogSchema,
    "assign_machine": AssignMachineSchema,
}

# Field mapping for entity extraction
ENTITY_FIELD_MAPPING = {
    "name": "operator_name",
    "operator": "operator_name", 
    "contact": "contact",
    "phone": "contact",
    "tel": "contact",
    "reg_number": "reg_number",
    "registration": "reg_number",
    "machine_type": "machine_type",
    "type": "machine_type",
    "model": "model",
    "year": "year",
    "fuel_volume": "fuel_volume",
    "volume": "fuel_volume",
    "fuel": "fuel_volume",
    "hours": "hours",
    "time": "hours",
    "description": "description",
    "issue": "description",
    "problem": "description",
    "unit": "unit",
}

# ================================
# Model Loading
# ================================
def init_model():
    """Initialize the ONNX model with thread safety."""
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

            # Load tokenizer
            tokenizer = AutoTokenizer.from_pretrained(
                MODEL_DIR, 
                use_fast=True,  # Use fast tokenizer if available
                trust_remote_code=False
            )

            # Load ONNX session with optimized settings
            sess_options = ort.SessionOptions()
            sess_options.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
            sess_options.intra_op_num_threads = 1  # Optimize for single request
            
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
    """Check if model is ready for inference."""
    with model_lock:
        return model_loaded and ner_session is not None

def get_model() -> Tuple[ort.InferenceSession, AutoTokenizer]:
    """Get the loaded model components with error handling."""
    with model_lock:
        if model_load_error:
            raise RuntimeError(f"NER model failed to load: {model_load_error}")
        if not is_model_ready():
            raise RuntimeError("NER model not ready yet")
        return ner_session, tokenizer

# ================================
# Utility Functions
# ================================
def normalize_workflow(workflow: str) -> str:
    """Normalize workflow string for consistent mapping."""
    if not workflow:
        return ""
    
    # Remove leading '#' and convert to lowercase
    normalized = workflow.lstrip("#").lower().strip()
    # Remove underscores and spaces for flexible matching
    normalized = re.sub(r'[_\s]+', '', normalized)
    return normalized

def extract_numeric_value(text: str) -> Optional[float]:
    """Extract numeric value from text with better parsing."""
    if not text:
        return None
    
    # Remove common non-numeric characters but keep decimal points
    cleaned = re.sub(r'[^\d.,]', '', text.replace(',', '.'))
    
    try:
        return float(cleaned)
    except (ValueError, TypeError):
        return None

def merge_entity_tokens(entities: List[Dict[str, Any]]) -> Dict[str, str]:
    """Merge B-I- tagged entities into complete values."""
    entity_map = {}
    current_entity = None
    current_tokens = []

    for entity in entities:
        label = entity["label"]
        token = entity["token"]

        if label.startswith("B-"):
            # Save previous entity if exists
            if current_entity and current_tokens:
                key = current_entity.lower()
                entity_map[key] = " ".join(current_tokens).strip()
            
            # Start new entity
            current_entity = label[2:]
            current_tokens = [token]
            
        elif label.startswith("I-") and current_entity:
            # Continue current entity
            if label[2:] == current_entity:
                current_tokens.append(token)
        else:
            # End current entity
            if current_entity and current_tokens:
                key = current_entity.lower()
                entity_map[key] = " ".join(current_tokens).strip()
            current_entity = None
            current_tokens = []

    # Don't forget the last entity
    if current_entity and current_tokens:
        key = current_entity.lower()
        entity_map[key] = " ".join(current_tokens).strip()

    return entity_map

def post_process_ner(text: str, ner_entities: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Convert raw NER output into structured Pydantic schema with improved reliability.
    Returns only the schema, logs intermediate steps to console.
    """
    try:
        # Log input for debugging
        logger.info(f"📝 Processing text: '{text}'")
        logger.info(f"🏷️ Raw entities: {ner_entities}")
        
        # Merge tokens by label
        entity_map = merge_entity_tokens(ner_entities)
        logger.info(f"🔗 Merged entities: {entity_map}")
        
        # Determine intent from workflow
        workflow_raw = entity_map.get("workflow", "")
        workflow_normalized = normalize_workflow(workflow_raw)
        logger.info(f"⚙️ Workflow: '{workflow_raw}' -> '{workflow_normalized}'")
        
        # Map to intent with fallback logic
        intent_key = WORKFLOW_INTENT_MAPPING.get(workflow_normalized, "clarification_needed")
        
        # If no workflow found, try to infer from other entities
        if intent_key == "clarification_needed" and not workflow_raw:
            if any(key in entity_map for key in ["name", "operator", "contact"]):
                intent_key = "assign_machine"
                logger.info("🔍 Inferred intent from name/contact entities")
            elif any(key in entity_map for key in ["fuel_volume", "volume", "fuel"]):
                intent_key = "fuel_log"
                logger.info("🔍 Inferred intent from fuel entities")
            elif any(key in entity_map for key in ["hours", "time"]):
                intent_key = "hours_log"
                logger.info("🔍 Inferred intent from hours entities")
            elif any(key in entity_map for key in ["description", "issue", "problem"]):
                intent_key = "report_issue"
                logger.info("🔍 Inferred intent from issue entities")

        logger.info(f"🎯 Final intent: '{intent_key}'")

        # Get appropriate schema class
        schema_cls = SCHEMA_BY_INTENT.get(intent_key, FallbackSchema)
        logger.info(f"📋 Using schema: {schema_cls.__name__}")
        
        # Map entities to schema fields
        mapped_data = {"intent": intent_key, "text": text}
        
        for entity_key, entity_value in entity_map.items():
            if not entity_value.strip():
                continue
                
            # Map to schema field
            schema_field = ENTITY_FIELD_MAPPING.get(entity_key, entity_key)
            logger.info(f"🗂️ Mapping '{entity_key}': '{entity_value}' -> '{schema_field}'")
            
            # Type conversion based on field
            if schema_field in ["year"] and entity_value:
                try:
                    mapped_data[schema_field] = int(extract_numeric_value(entity_value) or 0)
                    logger.info(f"🔢 Converted to int: {mapped_data[schema_field]}")
                except (ValueError, TypeError):
                    logger.warning(f"⚠️ Failed to convert '{entity_value}' to year")
                    continue
            elif schema_field in ["fuel_volume", "hours"] and entity_value:
                numeric_val = extract_numeric_value(entity_value)
                if numeric_val is not None:
                    mapped_data[schema_field] = numeric_val
                    logger.info(f"🔢 Converted to float: {mapped_data[schema_field]}")
            else:
                mapped_data[schema_field] = entity_value.strip()

        logger.info(f"📊 Mapped data: {mapped_data}")

        # Calculate missing required fields
        schema_fields = schema_cls.__fields__.keys()
        required_fields = [
            f for f in schema_fields 
            if f not in ["intent", "text", "missing"]
        ]
        
        missing = [
            f for f in required_fields 
            if f not in mapped_data or not mapped_data.get(f)
        ]
        
        mapped_data["missing"] = missing
        logger.info(f"❌ Missing fields: {missing}")
        
        # Create schema instance with validation
        try:
            schema_instance = schema_cls(**mapped_data)
            logger.info(f"✅ Schema created successfully: {schema_cls.__name__}")
        except Exception as e:
            logger.warning(f"⚠️ Schema validation failed: {e}, falling back to FallbackSchema")
            fallback_data = {
                "intent": "clarification_needed",
                "text": text,
                "missing": list(required_fields)
            }
            schema_instance = FallbackSchema(**fallback_data)

        # Return only the schema
        result_schema = schema_instance.dict()
        logger.info(f"🎉 Final schema: {result_schema}")
        
        return result_schema
        
    except Exception as e:
        logger.error(f"💥 Post-processing failed: {e}")
        # Return safe fallback response - only schema
        fallback_schema = {
            "intent": "clarification_needed",
            "text": text,
            "missing": [],
            "error": str(e)
        }
        logger.error(f"🚨 Returning fallback schema: {fallback_schema}")
        return fallback_schema

# ================================
# NER Handler
# ================================
class NERHandler:
    def __init__(self):
        self.session, self.tokenizer = get_model()
        self.id2label = self._load_id2label()
        self.max_length = 512  # Reasonable max length
        
    def _load_id2label(self) -> Dict[int, str]:
        """Load label mapping with error handling."""
        try:
            config_path = Path(MODEL_DIR) / "config.json"
            with open(config_path, "r", encoding="utf-8") as f:
                cfg = json.load(f)
            return {int(k): v for k, v in cfg.get("id2label", {}).items()}
        except Exception as e:
            logger.error(f"Failed to load id2label mapping: {e}")
            # Provide basic fallback mapping
            return {0: "O", 1: "B-WORKFLOW", 2: "I-WORKFLOW"}

    def merge_subwords(self, tokens: List[str], labels: List[str]) -> Tuple[List[str], List[str]]:
        """
        Merge subword tokens into full words with improved logic.
        """
        if not tokens or not labels or len(tokens) != len(labels):
            return [], []

        words, word_labels = [], []
        current_word, current_label = "", None

        for token, label in zip(tokens, labels):
            # Skip special tokens
            if token in self.tokenizer.all_special_tokens:
                continue
                
            # Handle subword tokens
            if token.startswith("##"):
                if current_word:  # Only merge if we have a current word
                    current_word += token[2:]
            else:
                # Finalize previous word
                if current_word and current_label:
                    words.append(current_word)
                    word_labels.append(current_label)
                
                # Start new word
                current_word = token
                current_label = label

        # Don't forget the last word
        if current_word and current_label:
            words.append(current_word)
            word_labels.append(current_label)

        return words, word_labels

    def predict(self, text: str) -> List[Dict[str, Any]]:
        """
        Perform NER prediction with improved error handling and preprocessing.
        """
        if not text or not text.strip():
            return []

        try:
            # Preprocess text
            text_clean = text.strip()
            
            # Tokenize with proper handling
            tokens = self.tokenizer(
                text_clean,
                truncation=True,
                padding=True,
                max_length=self.max_length,
                return_tensors="np",
                add_special_tokens=True
            )

            # Prepare inputs
            ort_inputs = {k: v for k, v in tokens.items()}
            
            # Run inference
            ort_outs = self.session.run(None, ort_inputs)
            logits = ort_outs[0]

            # Get predictions
            predictions = np.argmax(logits, axis=-1).squeeze()
            if predictions.ndim == 0:  # Handle single token case
                predictions = [predictions.item()]
            else:
                predictions = predictions.tolist()

            # Convert to labels
            labels = [self.id2label.get(p, "O") for p in predictions]

            # Get tokens
            input_ids = tokens["input_ids"].squeeze()
            if input_ids.ndim == 0:
                input_ids = [input_ids.item()]
            else:
                input_ids = input_ids.tolist()
                
            decoded_tokens = self.tokenizer.convert_ids_to_tokens(input_ids)

            # Merge subwords
            words, word_labels = self.merge_subwords(decoded_tokens, labels)

            # Create result
            ner_result = []
            for word, label in zip(words, word_labels):
                if word and label != "O":  # Only include non-O labels
                    ner_result.append({
                        "token": word,
                        "label": label
                    })

            print(f"ner_result {ner_result}")
            return ner_result

        except Exception as e:
            logger.error(f"NER prediction failed: {e}")
            return []

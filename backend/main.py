"""
Scanline OCR - Local Image Text Extraction
==========================================
Simple, stable, single-pass OCR for any image type:
receipts, screenshots, documents, prescriptions, forms.

Model : chinmays18/medical-prescription-ocr (Donut)
API   : POST /api/ocr  ->  {"extracted_text": "..."}
"""

import asyncio
import io
import logging
import os
import re
import sys
if sys.platform == 'win32':
    try:
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
        sys.stderr.reconfigure(encoding='utf-8', errors='replace')
    except Exception:
        pass
from contextlib import asynccontextmanager
from typing import Optional

import torch
from dotenv import load_dotenv
from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from PIL import Image, ImageEnhance, ImageOps, UnidentifiedImageError
from transformers import DonutProcessor, VisionEncoderDecoderModel

# ---------------------------------------------------------------------------
# Setup
# ---------------------------------------------------------------------------

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger("scanline-ocr")

load_dotenv()

MAX_FILE_SIZE_MB        = int(os.getenv("MAX_FILE_SIZE_MB", "10"))
REQUEST_TIMEOUT_SECONDS = int(os.getenv("REQUEST_TIMEOUT_SECONDS", "180"))
MAX_OUTPUT_TOKENS       = int(os.getenv("MAX_OUTPUT_TOKENS", "768"))

ALLOWED_CONTENT_TYPES = {
    "image/jpeg": True,
    "image/jpg":  True,
    "image/png":  True,
    "image/webp": True,
}

MODEL_ID    = "chinmays18/medical-prescription-ocr"
DEVICE      = "cuda" if torch.cuda.is_available() else "cpu"
TASK_PROMPT = "<s_ocr>"

_model_state: dict = {}


# ---------------------------------------------------------------------------
# Startup: Load model once (~500MB RAM)
# ---------------------------------------------------------------------------

@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Loading Donut OCR model: %s on %s", MODEL_ID, DEVICE)
    try:
        processor = DonutProcessor.from_pretrained(MODEL_ID)
        model = VisionEncoderDecoderModel.from_pretrained(MODEL_ID)
        model.to(DEVICE)
        model.eval()
        _model_state["processor"]  = processor
        _model_state["model"]      = model
        _model_state["count"]      = 0
        logger.info("✓[OK] Model ready. ~500MB RAM used.")
    except Exception as exc:
        logger.error("✗ Model load failed: %s", exc, exc_info=True)
    yield
    _model_state.clear()
    logger.info("Server shutting down.")


# ---------------------------------------------------------------------------
# Image Preprocessing
# ---------------------------------------------------------------------------

def prepare_image(raw_bytes: bytes) -> Image.Image:
    """
    Fix orientation + gentle contrast/sharpness boost.
    No cropping, no regions — full image to Donut.
    """
    try:
        img = Image.open(io.BytesIO(raw_bytes))
    except (UnidentifiedImageError, Exception) as exc:
        raise ValueError(f"Cannot open image: {exc}") from exc

    img = ImageOps.exif_transpose(img) or img
    img = img.convert("RGB")

    # Mild enhancement — improves both printed and handwritten text clarity
    img = ImageEnhance.Contrast(img).enhance(1.25)
    img = ImageEnhance.Sharpness(img).enhance(1.15)

    return img


# ---------------------------------------------------------------------------
# Clean Output Text
# ---------------------------------------------------------------------------

def clean_text(raw: str) -> str:
    """Strip Donut special tokens and normalize whitespace."""
    text = raw.replace("<s_ocr>", "")
    text = re.sub(r"</s_[^>]+>", "\n", text)
    text = re.sub(r"<sep\s*/?>", "\n", text)
    text = re.sub(r"<.*?>", " ", text)

    lines = []
    for line in text.split("\n"):
        line = re.sub(r"[ \t]+", " ", line).strip()
        if line:
            lines.append(line)

    return "\n".join(lines).strip()


# ---------------------------------------------------------------------------
# OCR Inference
# ---------------------------------------------------------------------------

def _run_ocr(image_bytes: bytes) -> str:
    processor: DonutProcessor           = _model_state["processor"]
    model:     VisionEncoderDecoderModel = _model_state["model"]

    image = prepare_image(image_bytes)

    # Explicit configuration before generate
    model.config.pad_token_id = processor.tokenizer.pad_token_id
    model.config.decoder_start_token_id = processor.tokenizer.convert_tokens_to_ids(['<s_ocr>'])[0]

    decoder_input_ids = processor.tokenizer(
        TASK_PROMPT,
        add_special_tokens=False,
        return_tensors="pt",
    ).input_ids.to(DEVICE)

    pixel_values = processor(image, return_tensors="pt").pixel_values.to(DEVICE)

    with torch.no_grad():
        outputs = model.generate(
            pixel_values,
            decoder_input_ids=decoder_input_ids,
            max_length=768,
            pad_token_id=processor.tokenizer.pad_token_id,
            eos_token_id=processor.tokenizer.eos_token_id,
            early_stopping=True,
            no_repeat_ngram_size=3,
            repetition_penalty=1.3,
            num_beams=1,
            bad_words_ids=[[processor.tokenizer.unk_token_id]],
            return_dict_in_generate=True,
        )

    raw = processor.batch_decode(outputs.sequences)[0]
    raw = raw.replace(processor.tokenizer.eos_token, "")
    raw = raw.replace(processor.tokenizer.pad_token, "")
    raw = raw.replace("<s_ocr>", "")
    raw = re.sub(r"<.*?>", " ", raw)

    result = clean_text(raw)
    return result if result else "No text could be extracted from this image."


# ---------------------------------------------------------------------------
# FastAPI App
# ---------------------------------------------------------------------------

app = FastAPI(
    title="Scanline OCR",
    description="Local offline image text extraction using Donut.",
    version="3.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["*"],
)


@app.get("/api/health")
def health():
    ready = "model" in _model_state
    return {
        "status":    "ok" if ready else "loading",
        "model":     MODEL_ID,
        "device":    DEVICE,
        "ready":     ready,
        "requests":  _model_state.get("count", 0),
    }


@app.post("/api/ocr")
async def extract_text(
    file:            UploadFile    = File(...),
    target_language: Optional[str] = Form(None),
    language:        Optional[str] = Form(None),
):
    if "model" not in _model_state:
        raise HTTPException(503, "Model is loading. Please wait and retry.")

    if file.content_type not in ALLOWED_CONTENT_TYPES:
        raise HTTPException(400, f"Unsupported type '{file.content_type}'. Use JPG, PNG, or WebP.")

    data = await file.read()
    if not data:
        raise HTTPException(400, "Uploaded file is empty.")
    if len(data) / (1024 * 1024) > MAX_FILE_SIZE_MB:
        raise HTTPException(400, f"File too large. Max {MAX_FILE_SIZE_MB} MB.")

    _model_state["count"] = _model_state.get("count", 0) + 1
    logger.info("OCR #%d — %s (%.2f MB)", _model_state["count"], file.filename, len(data)/1024/1024)

    try:
        text = await asyncio.wait_for(
            asyncio.to_thread(_run_ocr, data),
            timeout=REQUEST_TIMEOUT_SECONDS,
        )
    except asyncio.TimeoutError:
        raise HTTPException(504, f"OCR timed out after {REQUEST_TIMEOUT_SECONDS}s. Try a smaller/clearer image.")
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    except Exception as exc:
        logger.error("OCR error: %s", exc, exc_info=True)
        raise HTTPException(500, "OCR failed. Please try again.")

    logger.info("OCR #%d done — %d chars", _model_state["count"], len(text))
    return {"extracted_text": text}


# ---------------------------------------------------------------------------
# Serve Frontend (unchanged)
# ---------------------------------------------------------------------------

FRONTEND_DIR = os.path.join(os.path.dirname(__file__), "..", "frontend")

if os.path.exists(os.path.join(FRONTEND_DIR, "static")):
    app.mount("/static", StaticFiles(directory=os.path.join(FRONTEND_DIR, "static")), name="static")


@app.get("/")
def index():
    path = os.path.join(FRONTEND_DIR, "index.html")
    if not os.path.exists(path):
        raise HTTPException(404, "Frontend not found.")
    return FileResponse(path)

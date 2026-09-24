"""
Scanline OCR Web Application - Production Backend
===================================================

A FastAPI backend that accepts uploaded images and extracts text using
Google's Gemini vision models, with multi-key round-robin rotation,
automatic multi-model fallback, configurable language translation
(Original / English / Urdu), secure CORS, structured logging, and robust error handling.

Endpoints:
    GET  /api/health   -> liveness/readiness health check probe
    POST /api/ocr       -> accepts image file + target language, returns transcript
    GET  /              -> serves frontend index.html
    /static/*           -> serves frontend static assets
"""

import asyncio
import logging
import os
import sys
from typing import List, Optional

from dotenv import load_dotenv
from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from google import genai
from google.genai import types, errors

# ---------------------------------------------------------------------------
# Structured Logging
# ---------------------------------------------------------------------------

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger("scanline-ocr")

load_dotenv()

# ---------------------------------------------------------------------------
# Environment Configuration & Multi-API-Key Setup
# ---------------------------------------------------------------------------

# Support single or multiple comma-separated Gemini API keys
raw_keys = os.getenv("GEMINI_API_KEY", "") or os.getenv("GEMINI_API_KEYS", "")
GEMINI_API_KEYS: List[str] = [k.strip() for k in raw_keys.split(",") if k.strip()]

PRIMARY_MODEL = os.getenv("OCR_MODEL", "gemini-3.6-flash")
MAX_FILE_SIZE_MB = int(os.getenv("MAX_FILE_SIZE_MB", "10"))
REQUEST_TIMEOUT_SECONDS = int(os.getenv("REQUEST_TIMEOUT_SECONDS", "30"))

# Allowed origins for CORS (comma-separated)
ALLOWED_ORIGINS_RAW = os.getenv("ALLOWED_ORIGINS", "http://localhost:8000,http://127.0.0.1:8000")
if ALLOWED_ORIGINS_RAW.strip() == "*":
    ALLOWED_ORIGINS = ["*"]
else:
    ALLOWED_ORIGINS = [
        origin.strip() for origin in ALLOWED_ORIGINS_RAW.split(",") if origin.strip()
    ]

# Multi-model fallback sequence
FALLBACK_MODELS = [
    "gemini-3.6-flash",
    "gemini-3-flash",
    "gemini-2.0-flash",
    "gemini-2.0-flash-lite",
]

ALLOWED_CONTENT_TYPES = {
    "image/jpeg": "image/jpeg",
    "image/jpg": "image/jpeg",
    "image/png": "image/png",
    "image/webp": "image/webp",
}

# Counter for Round-Robin rotation across multiple API keys
_key_index = 0


def get_ordered_api_keys() -> List[str]:
    """
    Returns all configured API keys ordered starting from the current round-robin index.
    This evenly distributes load across all keys and enables automatic failover.
    """
    global _key_index
    if not GEMINI_API_KEYS:
        return []
    start = _key_index % len(GEMINI_API_KEYS)
    _key_index = (_key_index + 1) % len(GEMINI_API_KEYS)
    return GEMINI_API_KEYS[start:] + GEMINI_API_KEYS[:start]


def mask_key(key: str) -> str:
    """Mask API key for safe logging."""
    if len(key) <= 10:
        return "***"
    return f"{key[:6]}...{key[-4:]}"


# ---------------------------------------------------------------------------
# Prompt Engineering & Language Selection
# ---------------------------------------------------------------------------

def build_ocr_prompts(target_language: Optional[str] = None) -> tuple[str, str]:
    """
    Constructs the system instruction and user prompt according to the selected language.

    - "original" / None / "": verbatim transcription in source language (no translation).
    - "english": verbatim extraction translated to English.
    - "urdu": verbatim extraction translated to Urdu.
    """
    lang = (target_language or "").strip().lower()

    base_rules = """Strict rules:
1. Transcribe ALL visible text, preserving line breaks, spacing, and reading order as closely as possible.
2. Do NOT invent, assume, complete, or add any word, letter, or number that is not clearly visible in the image.
3. If a word or part of a word (especially handwriting) is illegible or you are not confident about it, write [illegible] in its place instead of guessing.
4. If the image contains medical notes, prescriptions, or clinical data, NEVER attempt to diagnose, interpret, or advise — transcribe/translate ONLY the literal visible text.
5. Do NOT summarize, explain, or add commentary. Output ONLY the transcribed/translated text itself — nothing else.
6. If the image contains no readable text at all, output exactly:
   No text detected in the image."""

    if lang == "urdu":
        system_prompt = f"""You are a precise OCR (Optical Character Recognition) and translation engine.

Your job is to read all text visibly present in the image (printed or handwritten) and translate it accurately into Urdu (اردو).

{base_rules}
7. Output the translated text in clear Urdu script while retaining original formatting and numbers."""
        user_prompt = "Transcribe all visible text in this image and translate the transcript into Urdu."

    elif lang == "english":
        system_prompt = f"""You are a precise OCR (Optical Character Recognition) and translation engine.

Your job is to read all text visibly present in the image (printed or handwritten) and translate it accurately into English.

{base_rules}
7. Output the translated text in English while retaining original formatting and line breaks."""
        user_prompt = "Transcribe all visible text in this image and translate the transcript into English."

    else:
        # Default: Original language (no translation)
        system_prompt = f"""You are a precise OCR (Optical Character Recognition) engine.

Your only job is to read the text that is visibly present in the given image (printed or handwritten) and transcribe it exactly as it appears in its original language(s).

{base_rules}
7. Do NOT translate the text. If the image contains Urdu, keep it in Urdu script; if English, keep English; if mixed, keep mixed exactly as written."""
        user_prompt = "Transcribe all visible text in this image in its original language without translation."

    return system_prompt, user_prompt


# ---------------------------------------------------------------------------
# App Setup & Middleware
# ---------------------------------------------------------------------------

app = FastAPI(
    title="Scanline OCR API",
    description="Production-ready Optical Character Recognition API with Gemini Vision & Multi-Key Pool",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["*"],
)


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@app.get("/api/health")
def health_check():
    """Liveness probe endpoint for monitoring and hosting platforms."""
    return {
        "status": "ok",
        "api_keys_configured": len(GEMINI_API_KEYS),
        "primary_model": PRIMARY_MODEL,
    }


@app.post("/api/ocr")
async def extract_text(
    file: UploadFile = File(...),
    target_language: Optional[str] = Form(None),
    language: Optional[str] = Form(None),
):
    """
    Accept an uploaded image file and optional target language,
    extracting text using Gemini Vision with multi-key rotation and automatic model fallback.
    """
    if not GEMINI_API_KEYS:
        logger.error("OCR request failed: No GEMINI_API_KEY configured.")
        raise HTTPException(
            status_code=500,
            detail="Server configuration error: OCR provider API key is not configured.",
        )

    # Validate content type
    if file.content_type not in ALLOWED_CONTENT_TYPES:
        logger.warning("Rejected file with invalid content-type: %s", file.content_type)
        raise HTTPException(
            status_code=400,
            detail="Unsupported file type. Please upload a JPG, JPEG, PNG, or WebP image.",
        )

    # Read and validate file size
    image_bytes = await file.read()
    size_mb = len(image_bytes) / (1024 * 1024)

    if len(image_bytes) == 0:
        logger.warning("Rejected empty file upload.")
        raise HTTPException(status_code=400, detail="Uploaded file is empty.")

    if size_mb > MAX_FILE_SIZE_MB:
        logger.warning("Rejected file exceeding size limit: %.2f MB", size_mb)
        raise HTTPException(
            status_code=400,
            detail=f"File too large ({size_mb:.1f} MB). Max allowed size is {MAX_FILE_SIZE_MB} MB.",
        )

    # Resolve target language
    selected_lang = (target_language or language or "").strip()
    system_prompt, user_prompt = build_ocr_prompts(selected_lang)
    media_type = ALLOWED_CONTENT_TYPES[file.content_type]

    # Get ordered keys (round-robin) & models sequence
    ordered_keys = get_ordered_api_keys()
    models_to_try = [PRIMARY_MODEL] + [m for m in FALLBACK_MODELS if m != PRIMARY_MODEL]
    last_error_log = None

    logger.info(
        "Processing image '%s' (%.2f MB, type=%s, language=%s, available_keys=%d)",
        file.filename,
        size_mb,
        media_type,
        selected_lang or "original",
        len(ordered_keys),
    )

    # Iterate through keys pool
    for api_key in ordered_keys:
        masked = mask_key(api_key)
        client = genai.Client(api_key=api_key)

        for model_name in models_to_try:
            try:
                logger.info("Attempting OCR with key [%s] and model [%s]", masked, model_name)

                def call_gemini():
                    return client.models.generate_content(
                        model=model_name,
                        contents=[
                            types.Part.from_bytes(
                                data=image_bytes,
                                mime_type=media_type,
                            ),
                            user_prompt,
                        ],
                        config=types.GenerateContentConfig(
                            system_instruction=system_prompt,
                            temperature=0.0,
                        ),
                    )

                # Run in threadpool with timeout
                response = await asyncio.wait_for(
                    asyncio.to_thread(call_gemini),
                    timeout=REQUEST_TIMEOUT_SECONDS,
                )

                extracted_text = (response.text or "").strip()
                logger.info("Successfully extracted text with key [%s] and model [%s]", masked, model_name)
                return {"extracted_text": extracted_text}

            except asyncio.TimeoutError:
                last_error_log = f"Request timed out on key [{masked}] / model [{model_name}]"
                logger.warning(last_error_log)
                continue

            except (errors.APIError, Exception) as exc:
                err_detail = str(getattr(exc, "message", exc))
                last_error_log = f"Key [{masked}] / Model [{model_name}] error: {err_detail}"
                logger.warning(last_error_log)

                # Check if this error is retryable
                retryable_keywords = [
                    "high demand",
                    "overloaded",
                    "503",
                    "429",
                    "resource_exhausted",
                    "quota",
                    "rate",
                    "unavailable",
                    "not found",
                    "no longer available",
                    "permission_denied",
                    "invalid_argument",
                    "unauthenticated",
                    "api key",
                ]
                if any(k in err_detail.lower() for k in retryable_keywords):
                    await asyncio.sleep(0.3)
                    continue
                else:
                    logger.error("Non-retryable OCR error on key [%s]: %s", masked, err_detail, exc_info=True)
                    break  # Move to next API key

    # If all keys and fallback models failed
    logger.error("All API keys and fallback models exhausted. Last error: %s", last_error_log)
    raise HTTPException(
        status_code=502,
        detail="The OCR service is temporarily unavailable or experiencing high demand across all keys. Please try again shortly.",
    )


# ---------------------------------------------------------------------------
# Frontend Static Files Serving
# ---------------------------------------------------------------------------

FRONTEND_DIR = os.path.join(os.path.dirname(__file__), "..", "frontend")

if os.path.exists(os.path.join(FRONTEND_DIR, "static")):
    app.mount("/static", StaticFiles(directory=os.path.join(FRONTEND_DIR, "static")), name="static")


@app.get("/")
def serve_index():
    index_path = os.path.join(FRONTEND_DIR, "index.html")
    if not os.path.exists(index_path):
        raise HTTPException(status_code=404, detail="Frontend index.html not found.")
    return FileResponse(index_path)

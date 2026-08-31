# Scanline — Simple OCR Web App (MVP)

Upload a photo of text (printed or handwritten) and get the text back, ready to copy.

```
Upload Image → Extract Text → Display Text → Copy Text
```

## How it works

- **Backend:** FastAPI (Python). One endpoint, `POST /api/ocr`, accepts an
  image and returns the extracted text. It also serves the frontend, so
  there's only one server to run.
- **OCR engine:** Google's Gemini Flash vision model (via the Google GenAI API),
  not a classic OCR library like Tesseract. Traditional OCR engines are weak on
  handwriting; a vision-capable model handles both printed and handwritten
  text, and can follow the "don't guess unclear words" rule, which a
  rules-based OCR engine can't do.
- **Frontend:** Plain HTML/CSS/JS — no build step, no framework, so it's
  easy to read and extend later.

## Project structure

```
ocr-app/
├── backend/
│   ├── main.py            # FastAPI app + OCR endpoint
│   ├── requirements.txt
│   └── .env.example       # copy to .env and add your API key
├── frontend/
│   ├── index.html
│   └── static/
│       ├── style.css
│       └── script.js
└── README.md
```

## 1. Prerequisites

- Python 3.9+
- A Google Gemini API key: https://aistudio.google.com/app/apikey

## 2. Setup

```bash
cd backend
python -m venv venv

# Activate the virtual environment
# macOS/Linux:
source venv/bin/activate
# Windows (PowerShell):
venv\Scripts\Activate.ps1

pip install -r requirements.txt

# Add your API key
cp .env.example .env      # macOS/Linux
copy .env.example .env    # Windows
```

Open `backend/.env` and paste your key:

```
GEMINI_API_KEY=your_gemini_api_key_here
```

## 3. Run it

```bash
# from the backend/ folder, with the venv active
uvicorn main:app --reload --port 8000
```

Open **http://127.0.0.1:8000** in your browser. That's the whole app —
the FastAPI server hosts both the API and the frontend.

## 4. Using the app

1. Click the upload area (or drag an image onto it). JPG/JPEG/PNG, up to 10 MB.
2. Click **Extract text**.
3. Read the transcript on the right. Unclear handwriting shows up as
   `[illegible]` instead of a guessed word.
4. Click **Copy text** to copy it to your clipboard, or **Clear** to start over.

## Design notes / current limits (intentional, for this MVP)

- English-focused: the prompt transcribes text as written and does not translate.
- No database, no accounts, no history — nothing is saved between requests.
- No batch upload — one image at a time.
- CORS is wide open (`allow_origins=["*"]`) for local development convenience;
  tighten this before deploying anywhere public.
- The Anthropic API key stays server-side only (in `backend/.env`) — it is
  never sent to or exposed in the browser.

## Troubleshooting

- **"Server is missing ANTHROPIC_API_KEY"** — you haven't created `backend/.env`,
  or it's missing the key. Re-check step 2.
- **CORS or connection errors in the browser console** — make sure you're
  opening `http://127.0.0.1:8000` (served by FastAPI), not opening
  `index.html` directly as a file.
- **Large or blurry images return `[illegible]` a lot** — try a clearer photo,
  better lighting, or crop closer to the text.
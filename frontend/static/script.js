const dropzone = document.getElementById("dropzone");
const dropzoneEmpty = document.getElementById("dropzone-empty");
const previewImg = document.getElementById("preview-img");
const fileInput = document.getElementById("file-input");

const extractBtn = document.getElementById("extract-btn");
const resetBtn = document.getElementById("reset-btn");
const copyBtn = document.getElementById("copy-btn");

const outputPlaceholder = document.getElementById("output-placeholder");
const outputText = document.getElementById("output-text");
const loadingEl = document.getElementById("loading");
const errorMsg = document.getElementById("error-msg");

const langButtons = document.querySelectorAll(".lang-btn");

const ALLOWED_TYPES = ["image/jpeg", "image/jpg", "image/png", "image/webp"];
const MAX_SIZE_MB = 10;

let selectedFile = null;
let selectedLanguage = ""; // Default: Original language (no translation)

// ---------------------------------------------------------------------
// Language selector handling
// ---------------------------------------------------------------------

langButtons.forEach((btn) => {
    btn.addEventListener("click", () => {
        langButtons.forEach((b) => b.classList.remove("is-active"));
        btn.classList.add("is-active");
        selectedLanguage = btn.dataset.lang || "";
    });
});

// ---------------------------------------------------------------------
// File selection (click, drag-and-drop, file input)
// ---------------------------------------------------------------------

dropzone.addEventListener("click", () => fileInput.click());
dropzone.addEventListener("keydown", (e) => {
    if (e.key === "Enter" || e.key === " ") {
        e.preventDefault();
        fileInput.click();
    }
});

["dragenter", "dragover"].forEach((evt) =>
    dropzone.addEventListener(evt, (e) => {
        e.preventDefault();
        dropzone.classList.add("is-dragover");
    })
);

["dragleave", "drop"].forEach((evt) =>
    dropzone.addEventListener(evt, (e) => {
        e.preventDefault();
        dropzone.classList.remove("is-dragover");
    })
);

dropzone.addEventListener("drop", (e) => {
    const file = e.dataTransfer.files[0];
    if (file) handleFile(file);
});

fileInput.addEventListener("change", (e) => {
    const file = e.target.files[0];
    if (file) handleFile(file);
});

function handleFile(file) {
    hideError();

    if (!ALLOWED_TYPES.includes(file.type)) {
        showError("Please upload a JPG, PNG, or WebP image.");
        return;
    }

    const sizeMb = file.size / (1024 * 1024);
    if (sizeMb > MAX_SIZE_MB) {
        showError(`File is too large (${sizeMb.toFixed(1)} MB). Max size is ${MAX_SIZE_MB} MB.`);
        return;
    }

    selectedFile = file;

    const reader = new FileReader();
    reader.onload = (e) => {
        previewImg.src = e.target.result;
        previewImg.hidden = false;
        dropzoneEmpty.hidden = true;
    };
    reader.readAsDataURL(file);

    extractBtn.disabled = false;
    resetBtn.disabled = false;
    resetOutput();
}

// ---------------------------------------------------------------------
// Extract text
// ---------------------------------------------------------------------

extractBtn.addEventListener("click", async () => {
    if (!selectedFile) return;

    hideError();
    setLoading(true);

    const formData = new FormData();
    formData.append("file", selectedFile);
    if (selectedLanguage) {
        formData.append("target_language", selectedLanguage);
    }

    try {
        const response = await fetch("/api/ocr", {
            method: "POST",
            body: formData,
        });

        const data = await response.json();

        if (!response.ok) {
            throw new Error(data.detail || "Something went wrong while extracting text.");
        }

        showOutput(data.extracted_text);
    } catch (err) {
        showError(err.message || "Could not reach the server. Is the backend running?");
    } finally {
        setLoading(false);
    }
});

function setLoading(isLoading) {
    extractBtn.disabled = isLoading;
    loadingEl.hidden = !isLoading;
    if (isLoading) {
        outputPlaceholder.hidden = true;
        outputText.hidden = true;
    }
}

function hasUrduArabic(text) {
    const urduPattern = /[\u0600-\u06FF\u0750-\u077F\uFB50-\uFDFF\uFE70-\uFEFF]/;
    return urduPattern.test(text);
}

function showOutput(text) {
    outputPlaceholder.hidden = true;
    outputText.hidden = false;
    outputText.textContent = text;

    // Apply RTL and Urdu typography if target is Urdu or text contains Urdu/Arabic script
    if (selectedLanguage === "urdu" || hasUrduArabic(text)) {
        outputText.setAttribute("dir", "rtl");
        outputText.classList.add("is-urdu");
    } else {
        outputText.setAttribute("dir", "ltr");
        outputText.classList.remove("is-urdu");
    }

    copyBtn.disabled = false;
}

function resetOutput() {
    outputText.hidden = true;
    outputText.textContent = "";
    outputText.setAttribute("dir", "ltr");
    outputText.classList.remove("is-urdu");
    outputPlaceholder.hidden = false;
    copyBtn.disabled = true;
    copyBtn.classList.remove("is-copied");
    copyBtn.textContent = "Copy text";
}

// ---------------------------------------------------------------------
// Copy
// ---------------------------------------------------------------------

copyBtn.addEventListener("click", async () => {
    try {
        await navigator.clipboard.writeText(outputText.textContent);
        copyBtn.textContent = "Copied";
        copyBtn.classList.add("is-copied");
        setTimeout(() => {
            copyBtn.textContent = "Copy text";
            copyBtn.classList.remove("is-copied");
        }, 1500);
    } catch {
        showError("Could not copy automatically. Please select and copy the text manually.");
    }
});

// ---------------------------------------------------------------------
// Reset
// ---------------------------------------------------------------------

resetBtn.addEventListener("click", () => {
    selectedFile = null;
    fileInput.value = "";
    previewImg.src = "";
    previewImg.hidden = true;
    dropzoneEmpty.hidden = false;
    extractBtn.disabled = true;
    resetBtn.disabled = true;

    // Reset language toggle to "Original"
    selectedLanguage = "";
    langButtons.forEach((b) => {
        if (!b.dataset.lang) {
            b.classList.add("is-active");
        } else {
            b.classList.remove("is-active");
        }
    });

    hideError();
    resetOutput();
});

// ---------------------------------------------------------------------
// Errors
// ---------------------------------------------------------------------

function showError(message) {
    errorMsg.textContent = message;
    errorMsg.hidden = false;
}

function hideError() {
    errorMsg.hidden = true;
    errorMsg.textContent = "";
}
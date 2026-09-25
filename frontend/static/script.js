// DOM Elements
const dropzone = document.getElementById("dropzone");
const dropzoneEmpty = document.getElementById("dropzone-empty");
const previewContainer = document.getElementById("preview-container");
const previewImg = document.getElementById("preview-img");
const changeImgBtn = document.getElementById("change-img-btn");
const fileInfo = document.getElementById("file-info");

const fileInput = document.getElementById("file-input");
const cameraInput = document.getElementById("camera-input");
const browseBtn = document.getElementById("browse-btn");
const cameraBtn = document.getElementById("camera-btn");

const extractBtn = document.getElementById("extract-btn");
const resetBtn = document.getElementById("reset-btn");
const copyBtn = document.getElementById("copy-btn");
const copyBtnText = document.getElementById("copy-btn-text");

const outputPlaceholder = document.getElementById("output-placeholder");
const outputText = document.getElementById("output-text");
const loadingEl = document.getElementById("loading");
const statsBadge = document.getElementById("stats-badge");

const errorMsg = document.getElementById("error-msg");
const errorText = document.getElementById("error-text");

const langPills = document.querySelectorAll(".lang-pill");

// Config
const ALLOWED_TYPES = ["image/jpeg", "image/jpg", "image/png", "image/webp"];
const MAX_SIZE_MB = 15;

let selectedFile = null;
let selectedLanguage = ""; // Default: Original language (no translation)

// ---------------------------------------------------------------------------
// Native Camera & File Browsing Triggers
// ---------------------------------------------------------------------------

browseBtn.addEventListener("click", (e) => {
    e.stopPropagation();
    fileInput.click();
});

cameraBtn.addEventListener("click", (e) => {
    e.stopPropagation();
    cameraInput.click();
});

dropzone.addEventListener("click", () => {
    if (!selectedFile) {
        fileInput.click();
    }
});

dropzone.addEventListener("keydown", (e) => {
    if ((e.key === "Enter" || e.key === " ") && !selectedFile) {
        e.preventDefault();
        fileInput.click();
    }
});

changeImgBtn.addEventListener("click", (e) => {
    e.stopPropagation();
    resetFile();
});

// Drag & Drop
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

// File Input Listeners
fileInput.addEventListener("change", (e) => {
    const file = e.target.files[0];
    if (file) handleFile(file);
});

cameraInput.addEventListener("change", (e) => {
    const file = e.target.files[0];
    if (file) handleFile(file);
});

// ---------------------------------------------------------------------------
// Client-Side Fast Image Optimizer / Compressor
// ---------------------------------------------------------------------------

async function compressImage(file, maxDimension = 1800, quality = 0.85) {
    // If file is already small (< 350 KB), skip re-encoding
    if (file.size < 350 * 1024 && file.type === "image/jpeg") {
        return file;
    }

    return new Promise((resolve) => {
        const reader = new FileReader();
        reader.onload = (e) => {
            const img = new Image();
            img.onload = () => {
                let width = img.width;
                let height = img.height;

                // Scale down high-res mobile photos while preserving text sharpness
                if (width > maxDimension || height > maxDimension) {
                    if (width > height) {
                        height = Math.round((height * maxDimension) / width);
                        width = maxDimension;
                    } else {
                        width = Math.round((width * maxDimension) / height);
                        height = maxDimension;
                    }
                }

                const canvas = document.createElement("canvas");
                canvas.width = width;
                canvas.height = height;

                const ctx = canvas.getContext("2d");
                // Fill white background for transparent images
                ctx.fillStyle = "#FFFFFF";
                ctx.fillRect(0, 0, width, height);
                ctx.drawImage(img, 0, 0, width, height);

                canvas.toBlob(
                    (blob) => {
                        if (!blob || blob.size >= file.size) {
                            resolve(file);
                        } else {
                            const optimizedFile = new File(
                                [blob],
                                (file.name || "photo.jpg").replace(/\.[^/.]+$/, "") + ".jpg",
                                { type: "image/jpeg", lastModified: Date.now() }
                            );
                            resolve(optimizedFile);
                        }
                    },
                    "image/jpeg",
                    quality
                );
            };
            img.onerror = () => resolve(file);
            img.src = e.target.result;
        };
        reader.onerror = () => resolve(file);
        reader.readAsDataURL(file);
    });
}

// ---------------------------------------------------------------------------
// File Handling & Preview
// ---------------------------------------------------------------------------

async function handleFile(file) {
    hideError();

    if (!ALLOWED_TYPES.includes(file.type)) {
        showError("Unsupported format. Please upload a JPG, PNG, or WebP image.");
        return;
    }

    const originalSizeMb = file.size / (1024 * 1024);
    if (originalSizeMb > MAX_SIZE_MB) {
        showError(`File is too large (${originalSizeMb.toFixed(1)} MB). Max limit is ${MAX_SIZE_MB} MB.`);
        return;
    }

    // Instant local preview
    const previewUrl = URL.createObjectURL(file);
    previewImg.src = previewUrl;
    previewContainer.hidden = false;
    dropzoneEmpty.hidden = true;

    // Fast client-side image compression in background
    const processedFile = await compressImage(file);
    selectedFile = processedFile;

    const processedSizeKb = Math.round(processedFile.size / 1024);
    const sizeDisplay = processedSizeKb > 1024 
        ? `${(processedSizeKb / 1024).toFixed(1)} MB` 
        : `${processedSizeKb} KB`;

    // Show file info in header
    fileInfo.textContent = `${file.name || "camera-photo.jpg"} (${sizeDisplay} • Ready)`;
    fileInfo.hidden = false;

    extractBtn.disabled = false;
    resetBtn.disabled = false;
    resetOutput();
}

function resetFile() {
    selectedFile = null;
    fileInput.value = "";
    cameraInput.value = "";
    previewImg.src = "";
    previewContainer.hidden = true;
    dropzoneEmpty.hidden = false;
    fileInfo.hidden = true;
    fileInfo.textContent = "";
    extractBtn.disabled = true;
    resetBtn.disabled = true;
    hideError();
    resetOutput();
}

// ---------------------------------------------------------------------------
// Language Selection (Pill Buttons)
// ---------------------------------------------------------------------------

langPills.forEach((pill) => {
    pill.addEventListener("click", () => {
        langPills.forEach((p) => p.classList.remove("is-active"));
        pill.classList.add("is-active");
        selectedLanguage = pill.dataset.lang || "";
    });
});

// ---------------------------------------------------------------------------
// Extract Text Action
// ---------------------------------------------------------------------------

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
            throw new Error(data.detail || "Something went wrong while processing the image.");
        }

        showOutput(data.extracted_text);
    } catch (err) {
        showError(err.message || "Could not reach the OCR server. Please try again.");
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
        statsBadge.hidden = true;
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

    // Apply RTL and Urdu typography if target is Urdu or text contains Urdu script
    if (selectedLanguage === "urdu" || hasUrduArabic(text)) {
        outputText.setAttribute("dir", "rtl");
        outputText.classList.add("is-urdu");
    } else {
        outputText.setAttribute("dir", "ltr");
        outputText.classList.remove("is-urdu");
    }

    // Calculate word & character stats
    const words = text.trim() ? text.trim().split(/\s+/).length : 0;
    const chars = text.length;
    statsBadge.textContent = `${words} words · ${chars} chars`;
    statsBadge.hidden = false;

    copyBtn.disabled = false;
}

function resetOutput() {
    outputText.hidden = true;
    outputText.textContent = "";
    outputText.setAttribute("dir", "ltr");
    outputText.classList.remove("is-urdu");
    outputPlaceholder.hidden = false;
    statsBadge.hidden = true;
    statsBadge.textContent = "";
    copyBtn.disabled = true;
    copyBtn.classList.remove("is-copied");
    copyBtnText.textContent = "Copy Text";
}

// ---------------------------------------------------------------------------
// Copy to Clipboard
// ---------------------------------------------------------------------------

copyBtn.addEventListener("click", async () => {
    try {
        await navigator.clipboard.writeText(outputText.textContent);
        copyBtnText.textContent = "Copied! ✓";
        copyBtn.classList.add("is-copied");
        setTimeout(() => {
            copyBtnText.textContent = "Copy Text";
            copyBtn.classList.remove("is-copied");
        }, 1800);
    } catch {
        showError("Could not copy automatically. Please copy the text manually.");
    }
});

// ---------------------------------------------------------------------------
// Global Reset
// ---------------------------------------------------------------------------

resetBtn.addEventListener("click", () => {
    resetFile();

    // Reset language toggle to "Original"
    selectedLanguage = "";
    langPills.forEach((p) => {
        if (!p.dataset.lang) {
            p.classList.add("is-active");
        } else {
            p.classList.remove("is-active");
        }
    });
});

// ---------------------------------------------------------------------------
// Errors
// ---------------------------------------------------------------------------

function showError(message) {
    errorText.textContent = message;
    errorMsg.hidden = false;
}

function hideError() {
    errorMsg.hidden = true;
    errorText.textContent = "";
}
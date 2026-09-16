/* ============================================================
   NETRA AI — STEP 5A
   Frontend connection for REAL screening backend

   This file only connects the existing Screening UI to:
   POST /api/screen

   It does NOT redesign or remove the existing interface.
   ============================================================ */

(() => {
    "use strict";

    const API_BASE = "/api";
    let selectedFile = null;
    let selectedPreviewUrl = null;

    document.addEventListener("DOMContentLoaded", initScreening);

    function initScreening() {
        const input = document.getElementById("imageInput");
        const uploadArea = document.getElementById("uploadArea");
        const analyzeButton = document.getElementById("analyzeButton");
        const removeButton = document.getElementById("removeImage");

        if (!input || !uploadArea || !analyzeButton) {
            console.warn("NETRA Step 5A: screening elements not found.");
            return;
        }

        uploadArea.addEventListener("click", (event) => {
            if (event.target.closest("#removeImage")) return;
            input.click();
        });

        input.addEventListener("change", () => {
            const file = input.files && input.files[0];
            if (file) selectImage(file);
        });

        uploadArea.addEventListener("dragover", (event) => {
            event.preventDefault();
            uploadArea.classList.add("drag-over");
        });

        uploadArea.addEventListener("dragleave", () => {
            uploadArea.classList.remove("drag-over");
        });

        uploadArea.addEventListener("drop", (event) => {
            event.preventDefault();
            uploadArea.classList.remove("drag-over");

            const file = event.dataTransfer?.files?.[0];
            if (file) selectImage(file);
        });

        if (removeButton) {
            removeButton.addEventListener("click", (event) => {
                event.preventDefault();
                event.stopPropagation();
                resetScreening();
            });
        }

        analyzeButton.addEventListener("click", runScreening);

        resetScreening(false);
    }

    function selectImage(file) {
        const validTypes = [
            "image/jpeg",
            "image/png",
            "image/jpg",
            "image/webp"
        ];

        if (!validTypes.includes(file.type)) {
            setStatus("Please select a JPG, JPEG, PNG or WEBP image.", true);
            return;
        }

        if (file.size > 16 * 1024 * 1024) {
            setStatus("Image is too large. Maximum size is 16 MB.", true);
            return;
        }

        selectedFile = file;

        const input = document.getElementById("imageInput");
        const preview = document.getElementById("previewImage");
        const previewBox = document.getElementById("imagePreview");
        const uploadContent = document.getElementById("uploadContent");
        const analyzeButton = document.getElementById("analyzeButton");

        if (selectedPreviewUrl) {
            URL.revokeObjectURL(selectedPreviewUrl);
        }

        selectedPreviewUrl = URL.createObjectURL(file);

        if (preview) preview.src = selectedPreviewUrl;
        if (previewBox) previewBox.style.display = "block";
        if (uploadContent) uploadContent.style.display = "none";
        if (analyzeButton) analyzeButton.disabled = false;

        if (input && input.files?.length === 0) {
            try {
                const transfer = new DataTransfer();
                transfer.items.add(file);
                input.files = transfer.files;
            } catch (_) {
                /* selectedFile remains the source of truth */
            }
        }

        setStatus(`Ready • ${file.name}`);
        clearResult();
    }

    async function runScreening() {
        const analyzeButton = document.getElementById("analyzeButton");
        const file =
            selectedFile ||
            document.getElementById("imageInput")?.files?.[0];

        if (!file) {
            setStatus("Please select a retinal image first.", true);
            return;
        }

        setLoading(true);
        setStatus("NETRA is analyzing the retinal image...");

        const formData = new FormData();
        formData.append("image", file);

        try {
            const response = await fetch(`${API_BASE}/screen`, {
                method: "POST",
                body: formData
            });

            let data = null;

            try {
                data = await response.json();
            } catch (_) {
                data = null;
            }

            if (!response.ok || !data?.success) {
                throw new Error(
                    data?.details ||
                    data?.error ||
                    `Screening failed (${response.status})`
                );
            }

            renderResult(data);

            setStatus(
                "Analysis complete • Real EfficientNet-B0 + Grad-CAM"
            );

            window.dispatchEvent(
                new CustomEvent("netra:screening-complete", {
                    detail: data
                })
            );

        } catch (error) {
            console.error(
                "NETRA Step 5A screening error:",
                error
            );

            setStatus(
                error.message ||
                "Unable to complete screening.",
                true
            );

            showError(error.message);

        } finally {
            setLoading(false);
        }
    }

    function renderResult(data) {
        const empty =
            document.getElementById("analysisEmpty");

        const result =
            document.getElementById("analysisResult");

        if (empty) {
            empty.style.display = "none";
        }

        if (result) {
            result.style.display = "block";
        }

        const level =
            Number(data.level ?? 0);

        const confidence =
            Number(data.confidence ?? 0);

        const quality =
            Number(data.image_quality ?? 0);

        const severity =
            data.severity ||
            `Level ${level}`;

        const referral =
            String(
                data.referral ||
                "REVIEW"
            ).toUpperCase();

        setText(
            "severityResult",
            `Level ${level} — ${severity}`
        );

        setText(
            "confidenceValue",
            toPercent(confidence)
        );

        setText(
            "qualityValue",
            toPercent(quality)
        );

        const qualityBar =
            document.getElementById("qualityBar");

        if (qualityBar) {
            qualityBar.style.width =
                `${clampPercent(quality)}%`;
        }

        setText(
            "qualityMessage",
            quality >= 80
                ? "Image is suitable for automated analysis."
                : "Image quality is limited. Clinical review is recommended."
        );

        const referralBox =
            document.querySelector(".referral-alert");

        if (referralBox) {

            const shouldRefer =
                referral === "REFER" ||
                level >= 2;

            referralBox.innerHTML =
                shouldRefer
                    ? "<span>!</span> Referable case — specialist review recommended"
                    : "<span>✓</span> Screening result is not flagged for referral";
        }

        const resultImage =
            document.getElementById("resultImage");

        if (resultImage && data.image_url) {
            resultImage.src =
                assetUrl(data.image_url);
        }

        const xaiImage =
            document.getElementById("xaiImage");

        if (xaiImage && data.xai_url) {
            xaiImage.src =
                assetUrl(data.xai_url);

            xaiImage.style.display =
                "block";
        }

        renderEvidence(data.evidence);
        renderExplanation(data.explanation);
        renderCaseReference(data);

        const reportButton =
            document.getElementById("reportButton");

        if (reportButton) {
            reportButton.dataset.caseId =
                data.case_id ?? "";

            reportButton.disabled =
                false;
        }
    }

    function renderEvidence(evidence) {

        if (!Array.isArray(evidence)) {
            return;
        }

        const cards = [
            document.getElementById("microValue"),
            document.getElementById("hemorrhageValue"),
            document.getElementById("exudateValue")
        ];

        if (!evidence.length) {

            cards.forEach(card => {
                if (card) {
                    card.textContent = "—";
                }
            });

            return;
        }

        /*
         * The current backend returns
         * explainability evidence strings.
         * We therefore show presence indicators,
         * not invented lesion counts.
         */

        const text =
            evidence
                .map(item =>
                    String(item).toLowerCase()
                )
                .join(" ");

        if (cards[0]) {
            cards[0].textContent =
                text.includes("micro")
                    ? "✓"
                    : "—";
        }

        if (cards[1]) {
            cards[1].textContent =
                text.includes("hemorr")
                    ? "✓"
                    : "—";
        }

        if (cards[2]) {
            cards[2].textContent =
                text.includes("exud")
                    ? "✓"
                    : "—";
        }
    }

    function renderExplanation(explanation) {

        if (!explanation) {
            return;
        }

        const section =
            document.querySelector(".xai-section");

        if (!section) {
            return;
        }

        let box =
            section.querySelector(
                ".netra-step5a-explanation"
            );

        if (!box) {

            box = document.createElement("div");

            box.className =
                "netra-step5a-explanation";

            box.style.marginTop =
                "12px";

            box.style.padding =
                "12px 14px";

            box.style.border =
                "1px solid rgba(91,218,240,.13)";

            box.style.borderRadius =
                "12px";

            box.style.background =
                "rgba(7,17,24,.75)";

            box.style.color =
                "#718792";

            box.style.fontSize =
                "10px";

            box.style.lineHeight =
                "1.6";

            section.appendChild(box);
        }

        box.innerHTML = `
            <strong style="color:#edf9fb;">
                AI explanation
            </strong>

            <div style="margin-top:5px;">
                ${escapeHtml(explanation)}
            </div>
        `;
    }

    function renderCaseReference(data) {

        const summary =
            document.querySelector(
                ".result-summary"
            );

        if (!summary) {
            return;
        }

        let box =
            summary.querySelector(
                ".netra-step5a-case"
            );

        if (!box) {

            box = document.createElement("div");

            box.className =
                "netra-step5a-case";

            box.style.marginTop =
                "8px";

            box.style.color =
                "#526973";

            box.style.fontSize =
                "8px";

            summary.appendChild(box);
        }

        const reference =
            data.case_reference ||
            data.case_id;

        if (
            reference !== undefined &&
            reference !== null
        ) {
            box.textContent =
                `CASE • ${reference}`;
        }
    }

    function clearResult() {

        const empty =
            document.getElementById(
                "analysisEmpty"
            );

        const result =
            document.getElementById(
                "analysisResult"
            );

        if (empty) {

            empty.style.display =
                "block";

            empty.innerHTML = `
                <div class="empty-icon">◎</div>

                <h3>
                    Waiting for retinal image
                </h3>

                <p>
                    Upload an image to see image quality,
                    DR severity, lesion evidence and explainability.
                </p>
            `;
        }

        if (result) {
            result.style.display =
                "none";
        }
    }

    function showError(message) {

        const empty =
            document.getElementById(
                "analysisEmpty"
            );

        const result =
            document.getElementById(
                "analysisResult"
            );

        if (result) {
            result.style.display =
                "none";
        }

        if (empty) {

            empty.style.display =
                "block";

            empty.innerHTML = `
                <div class="empty-icon">⚠</div>

                <h3>
                    Screening could not be completed
                </h3>

                <p>
                    ${escapeHtml(
                        message ||
                        "Please check the backend and try again."
                    )}
                </p>
            `;
        }
    }

    function resetScreening(
        updateStatus = true
    ) {

        selectedFile = null;

        if (selectedPreviewUrl) {

            URL.revokeObjectURL(
                selectedPreviewUrl
            );

            selectedPreviewUrl =
                null;
        }

        const input =
            document.getElementById(
                "imageInput"
            );

        const preview =
            document.getElementById(
                "previewImage"
            );

        const previewBox =
            document.getElementById(
                "imagePreview"
            );

        const uploadContent =
            document.getElementById(
                "uploadContent"
            );

        const analyzeButton =
            document.getElementById(
                "analyzeButton"
            );

        if (input) {
            input.value = "";
        }

        if (preview) {
            preview.src = "";
        }

        if (previewBox) {
            previewBox.style.display =
                "none";
        }

        if (uploadContent) {
            uploadContent.style.display =
                "";
        }

        if (analyzeButton) {

            analyzeButton.disabled =
                true;

            analyzeButton.innerHTML =
                "Analyze Retina <span>→</span>";
        }

        clearResult();

        if (updateStatus) {
            setStatus(
                "Ready for image"
            );
        }
    }

    function setLoading(isLoading) {

        const button =
            document.getElementById(
                "analyzeButton"
            );

        if (!button) {
            return;
        }

        button.disabled =
            isLoading;

        button.innerHTML =
            isLoading
                ? `<span class="loading-spinner"></span> Analyzing...`
                : "Analyze Again <span>→</span>";
    }

    function setStatus(
        message,
        isError = false
    ) {

        const status =
            document.getElementById(
                "analysisStatus"
            );

        if (!status) {
            return;
        }

        status.textContent =
            message || "";

        status.classList.toggle(
            "error",
            Boolean(isError)
        );
    }

    function setText(
        id,
        value
    ) {

        const element =
            document.getElementById(id);

        if (element) {
            element.textContent =
                value ?? "—";
        }
    }

    function toPercent(value) {

        let number =
            Number(value);

        if (!Number.isFinite(number)) {
            return "—";
        }

        if (
            number >= 0 &&
            number <= 1
        ) {
            number *= 100;
        }

        return `${number.toFixed(1)}%`;
    }

    function clampPercent(value) {

        let number =
            Number(value);

        if (!Number.isFinite(number)) {
            return 0;
        }

        if (
            number >= 0 &&
            number <= 1
        ) {
            number *= 100;
        }

        return Math.min(
            100,
            Math.max(
                0,
                number
            )
        );
    }

    function assetUrl(path) {

        if (!path) {
            return "";
        }

        if (
            /^https?:\/\//i.test(path)
        ) {
            return path;
        }

        return path.startsWith("/")
            ? path
            : `/${path}`;
    }

    function escapeHtml(value) {

        return String(
            value ?? ""
        )
            .replaceAll(
                "&",
                "&amp;"
            )
            .replaceAll(
                "<",
                "&lt;"
            )
            .replaceAll(
                ">",
                "&gt;"
            )
            .replaceAll(
                '"',
                "&quot;"
            )
            .replaceAll(
                "'",
                "&#039;"
            );
    }

    window.NETRA_STEP5A = {
        runScreening,
        resetScreening
    };
})();
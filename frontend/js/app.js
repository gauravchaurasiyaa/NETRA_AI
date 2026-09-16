/* ============================================================
   NETRA — Explainable Retinal AI
   STEP 7 — FRONTEND / BACKEND INTEGRATION
   ============================================================ */

const API = "/api";

let selectedImage = null;
let currentCaseId = null;
let currentCase = null;
let allCases = [];
let currentFilter = "All";


/* ============================================================
   BASIC HELPERS
   ============================================================ */

function $(selector) {
    return document.querySelector(selector);
}

function $$(selector) {
    return document.querySelectorAll(selector);
}

function escapeHTML(value) {

    if (value === null || value === undefined) {
        return "";
    }

    return String(value)
        .replace(/&/g, "&amp;")
        .replace(/</g, "&lt;")
        .replace(/>/g, "&gt;")
        .replace(/"/g, "&quot;")
        .replace(/'/g, "&#039;");
}


async function apiFetch(url, options = {}) {

    const response = await fetch(url, options);

    let data = {};

    try {
        data = await response.json();
    } catch (error) {
        data = {};
    }

    if (!response.ok) {

        throw new Error(
            data.error ||
            data.message ||
            `Request failed (${response.status})`
        );
    }

    return data;
}


function showMessage(message) {
    console.log("NETRA:", message);
}


/* ============================================================
   PAGE NAVIGATION
   ============================================================ */

const pageNames = {
    dashboard: "Dashboard",
    screening: "New Screening",
    cases: "Patient Cases",
    analytics: "AI Analytics",
    workflow: "Rural Network",
    reports: "Reports"
};


function showPage(pageId) {

    const pages = $$(".page");
    const navItems = $$(".nav-item");

    pages.forEach(page => {

        page.classList.toggle(
            "active",
            page.id === pageId
        );
    });

    navItems.forEach(item => {

        item.classList.toggle(
            "active",
            item.dataset.page === pageId
        );
    });

    const pageName = $("#pageName");

    if (pageName) {

        pageName.textContent =
            pageNames[pageId] || pageId;
    }

    if (pageId === "cases") {
        loadCases();
    }

    if (pageId === "analytics") {
        loadAnalytics();
    }

    if (pageId === "workflow") {
        loadNetwork();
    }

    if (pageId === "reports") {
        loadLatestReport();
    }
}


function setupNavigation() {

    $$(".nav-item").forEach(button => {

        button.addEventListener(
            "click",
            () => {

                showPage(
                    button.dataset.page
                );
            }
        );
    });


    $$("[data-go]").forEach(button => {

        button.addEventListener(
            "click",
            () => {

                showPage(
                    button.dataset.go
                );
            }
        );
    });


    const startScreening =
        $("#startScreening");

    if (startScreening) {

        startScreening.addEventListener(
            "click",
            () => {

                showPage(
                    "screening"
                );
            }
        );
    }
}


/* ============================================================
   SCREENING IMAGE UPLOAD
   ============================================================ */

function setupImageUpload() {

    const uploadArea =
        $("#uploadArea");

    const imageInput =
        $("#imageInput");

    const uploadContent =
        $("#uploadContent");

    const imagePreview =
        $("#imagePreview");

    const previewImage =
        $("#previewImage");

    const removeImage =
        $("#removeImage");

    const analyzeButton =
        $("#analyzeButton");


    if (!uploadArea || !imageInput) {

        console.warn(
            "NETRA: Image upload elements not found."
        );

        return;
    }


    /*
       CLICK TO BROWSE

       The entire upload box opens the
       native file picker.
    */

    uploadArea.addEventListener(
        "click",
        event => {

            /*
               Do not reopen the picker when
               clicking the remove button.
            */

            if (
                event.target.closest(
                    "#removeImage"
                )
            ) {
                return;
            }

            /*
               Do not trigger another picker
               if the click already originated
               from the native input.
            */

            if (
                event.target === imageInput
            ) {
                return;
            }

            imageInput.click();
        }
    );


    /*
       FILE SELECTED FROM DEVICE
    */

    imageInput.addEventListener(
        "change",
        () => {

            const file =
                imageInput.files &&
                imageInput.files[0];

            if (file) {

                handleSelectedImage(
                    file
                );
            }
        }
    );


    /*
       DRAG OVER
    */

    uploadArea.addEventListener(
        "dragover",
        event => {

            event.preventDefault();

            event.stopPropagation();

            uploadArea.classList.add(
                "dragging"
            );
        }
    );


    /*
       DRAG LEAVE
    */

    uploadArea.addEventListener(
        "dragleave",
        event => {

            event.preventDefault();

            uploadArea.classList.remove(
                "dragging"
            );
        }
    );


    /*
       DROP IMAGE
    */

    uploadArea.addEventListener(
        "drop",
        event => {

            event.preventDefault();

            event.stopPropagation();

            uploadArea.classList.remove(
                "dragging"
            );

            const files =
                event.dataTransfer?.files;

            if (
                !files ||
                !files.length
            ) {
                return;
            }

            const file =
                files[0];

            handleSelectedImage(
                file
            );
        }
    );


    /*
       REMOVE SELECTED IMAGE
    */

    if (removeImage) {

        removeImage.addEventListener(
            "click",
            event => {

                event.preventDefault();

                event.stopPropagation();

                selectedImage =
                    null;

                imageInput.value =
                    "";

                if (previewImage) {

                    previewImage.src =
                        "";
                }

                if (imagePreview) {

                    imagePreview.classList.remove(
                        "visible"
                    );

                    imagePreview.style.display =
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
                        `Analyze Retina <span>→</span>`;
                }

                setAnalysisStatus(
                    "Ready for image"
                );
            }
        );
    }
}


/* ============================================================
   HANDLE SELECTED IMAGE
   ============================================================ */

function handleSelectedImage(file) {

    if (!file) {
        return;
    }


    /*
       Validate image type.
    */

    if (
        !file.type ||
        !file.type.startsWith(
            "image/"
        )
    ) {

        alert(
            "Please select a retinal image."
        );

        return;
    }


    /*
       Supported image formats.
    */

    const allowedTypes = [
        "image/jpeg",
        "image/jpg",
        "image/png",
        "image/webp"
    ];


    if (
        !allowedTypes.includes(
            file.type.toLowerCase()
        )
    ) {

        alert(
            "Please select a JPG, JPEG, PNG or WEBP image."
        );

        return;
    }


    /*
       Maximum 16 MB.
    */

    if (
        file.size >
        16 * 1024 * 1024
    ) {

        alert(
            "Image is too large. Maximum size is 16 MB."
        );

        return;
    }


    /*
       Store the actual File object.
    */

    selectedImage =
        file;


    /*
       Keep dropped file available
       through the native input where
       the browser permits it.
    */

    const imageInput =
        $("#imageInput");

    if (
        imageInput &&
        typeof DataTransfer !==
        "undefined"
    ) {

        try {

            const transfer =
                new DataTransfer();

            transfer.items.add(
                file
            );

            imageInput.files =
                transfer.files;

        } catch (error) {

            /*
               Some browsers may prevent
               programmatic assignment.

               selectedImage remains the
               source of truth.
            */

            console.log(
                "NETRA: Native input assignment unavailable.",
                error
            );
        }
    }


    /*
       Create local preview.
    */

    const reader =
        new FileReader();


    reader.onload =
        event => {

            const previewImage =
                $("#previewImage");

            const imagePreview =
                $("#imagePreview");

            const uploadContent =
                $("#uploadContent");

            const analyzeButton =
                $("#analyzeButton");


            if (previewImage) {

                previewImage.src =
                    event.target.result;

                previewImage.style.display =
                    "block";
            }


            if (imagePreview) {

                imagePreview.classList.add(
                    "visible"
                );

                imagePreview.style.display =
                    "block";
            }


            if (uploadContent) {

                uploadContent.style.display =
                    "none";
            }


            if (analyzeButton) {

                analyzeButton.disabled =
                    false;

                analyzeButton.innerHTML =
                    `Analyze Retina <span>→</span>`;
            }


            setAnalysisStatus(
                `Image ready • ${file.name}`
            );


            /*
               Clear old result when a new
               image is selected.
            */

            clearAnalysisResult();
        };


    reader.onerror =
        () => {

            alert(
                "Unable to read this image. Please try another image."
            );

            selectedImage =
                null;
        };


    reader.readAsDataURL(
        file
    );
}


/* ============================================================
   CLEAR OLD ANALYSIS RESULT
   ============================================================ */

function clearAnalysisResult() {

    const analysisEmpty =
        $("#analysisEmpty");

    const analysisResult =
        $("#analysisResult");


    if (analysisEmpty) {

        analysisEmpty.style.display =
            "block";

        analysisEmpty.innerHTML = `
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


    if (analysisResult) {

        analysisResult.style.display =
            "none";
    }
}


/* ============================================================
   SCREENING
   ============================================================ */

function setupScreening() {

    const analyzeButton =
        $("#analyzeButton");


    if (!analyzeButton) {

        console.warn(
            "NETRA: Analyze button not found."
        );

        return;
    }


    analyzeButton.addEventListener(
        "click",
        submitScreening
    );
}


async function submitScreening() {

    /*
       Make sure an image exists.
    */

    if (!selectedImage) {

        const imageInput =
            $("#imageInput");

        if (
            imageInput &&
            imageInput.files &&
            imageInput.files.length
        ) {

            selectedImage =
                imageInput.files[0];
        }
    }


    if (!selectedImage) {

        alert(
            "Please select a retinal image first."
        );

        return;
    }


    const analyzeButton =
        $("#analyzeButton");


    if (analyzeButton) {

        analyzeButton.disabled =
            true;

        analyzeButton.innerHTML =
            `<span class="loading-spinner"></span> Analyzing...`;
    }


    setAnalysisStatus(
        "Uploading retinal image..."
    );


    const formData =
        new FormData();


    formData.append(
        "image",
        selectedImage
    );


    /*
       Optional patient fields.

       The interface may not contain
       these fields. Therefore they are
       read safely.
    */

    const patientName =
        getFieldValue(
            [
                "#patientName",
                "#patient_name",
                "[name='patient_name']"
            ]
        );


    const age =
        getFieldValue(
            [
                "#patientAge",
                "#age",
                "[name='age']"
            ]
        );


    const sex =
        getFieldValue(
            [
                "#patientSex",
                "#sex",
                "[name='sex']"
            ]
        );


    const location =
        getFieldValue(
            [
                "#patientLocation",
                "#location",
                "[name='location']"
            ]
        );


    const notes =
        getFieldValue(
            [
                "#patientNotes",
                "#notes",
                "[name='notes']"
            ]
        );


    formData.append(
        "patient_name",
        patientName
    );

    formData.append(
        "age",
        age
    );

    formData.append(
        "sex",
        sex
    );

    formData.append(
        "location",
        location
    );

    formData.append(
        "notes",
        notes
    );


    try {

        setAnalysisStatus(
            "NETRA AI is analyzing the image..."
        );


        const data =
            await apiFetch(
                `${API}/screen`,
                {
                    method: "POST",
                    body: formData
                }
            );


        /*
           Save current case.
        */

        currentCaseId =
            data.case_id ||
            data.id;


        currentCase =
            data;


        /*
           Display result.
        */

        renderScreeningResult(
            data
        );


        setAnalysisStatus(
            "Analysis complete"
        );


        /*
           Refresh live data.
        */

        await loadCases();

        await loadAnalytics();

        await loadDashboardStats();


        /*
           Notify any optional modules.
        */

        try {

            window.dispatchEvent(
                new CustomEvent(
                    "netra:screening-complete",
                    {
                        detail: data
                    }
                )
            );

        } catch (error) {

            console.log(
                "NETRA event notification skipped."
            );
        }


    } catch (error) {

        console.error(
            "Screening error:",
            error
        );


        setAnalysisStatus(
            "Analysis failed"
        );


        const analysisEmpty =
            $("#analysisEmpty");

        const analysisResult =
            $("#analysisResult");


        if (analysisResult) {

            analysisResult.style.display =
                "none";
        }


        if (analysisEmpty) {

            analysisEmpty.style.display =
                "block";

            analysisEmpty.innerHTML = `
                <div class="empty-icon">⚠</div>

                <h3>
                    Screening failed
                </h3>

                <p>
                    ${escapeHTML(
                        error.message ||
                        "Could not analyze image."
                    )}
                </p>
            `;
        }


        alert(
            error.message ||
            "Could not analyze image."
        );


    } finally {

        if (analyzeButton) {

            analyzeButton.disabled =
                false;

            analyzeButton.innerHTML =
                `Analyze Retina <span>→</span>`;
        }
    }
}


function getFieldValue(selectors) {

    for (
        const selector of selectors
    ) {

        const element =
            $(selector);

        if (element) {

            return (
                element.value ||
                ""
            );
        }
    }

    return "";
}


function setAnalysisStatus(message) {

    const status =
        $("#analysisStatus");

    if (status) {

        status.textContent =
            message;
    }
}


/* ============================================================
   SCREENING RESULT
   ============================================================ */

function renderScreeningResult(data) {

    const analysisEmpty =
        $("#analysisEmpty");

    const analysisResult =
        $("#analysisResult");


    if (analysisEmpty) {

        analysisEmpty.style.display =
            "none";
    }


    if (analysisResult) {

        analysisResult.style.display =
            "block";
    }


    /*
       Result image.
    */

    const resultImage =
        $("#resultImage");


    if (
        resultImage &&
        data.image_url
    ) {

        resultImage.src =
            data.image_url +
            "?t=" +
            Date.now();

        resultImage.style.display =
            "block";
    }


    /*
       Grad-CAM XAI image.
    */

    const xaiImage =
        $("#xaiImage");


    if (
        xaiImage &&
        data.xai_url
    ) {

        xaiImage.src =
            data.xai_url +
            "?t=" +
            Date.now();

        xaiImage.style.display =
            "block";
    }


    /*
       Severity.
    */

    const severityResult =
        $("#severityResult");


    if (severityResult) {

        severityResult.textContent =
            `Level ${data.level ?? "—"} — ${data.severity || "Unknown"}`;
    }


    /*
       Confidence.
    */

    const confidenceValue =
        $("#confidenceValue");


    if (confidenceValue) {

        const confidence =
            Number(
                data.confidence
            );


        if (
            Number.isFinite(
                confidence
            )
        ) {

            const percent =
                confidence <= 1
                    ? confidence * 100
                    : confidence;

            confidenceValue.textContent =
                `${percent.toFixed(1)}%`;

        } else {

            confidenceValue.textContent =
                "—";
        }
    }


    /*
       Image quality.
    */

    const qualityValue =
        $("#qualityValue");


    if (qualityValue) {

        qualityValue.textContent =
            formatQuality(
                data.image_quality
            );
    }


    /*
       Quality bar.
    */

    const qualityBar =
        $("#qualityBar");


    if (qualityBar) {

        qualityBar.style.width =
            qualityToPercent(
                data.image_quality
            ) + "%";
    }


    /*
       Quality message.
    */

    const qualityMessage =
        $("#qualityMessage");


    if (qualityMessage) {

        qualityMessage.textContent =
            qualityMessageText(
                data.image_quality
            );
    }


    /*
       Referral.
    */

    renderReferral(
        data.referral
    );


    /*
       Evidence.
    */

    renderEvidence(
        data.evidence || []
    );


    /*
       Report button.
    */

    const reportButton =
        $("#reportButton");


    if (reportButton) {

        reportButton.disabled =
            !currentCaseId;

        reportButton.textContent =
            "Generate Screening Report";
    }


    /*
       Evidence explanation.
    */

    updateEvidenceExplanation(
        data.evidence || []
    );
}


/* ============================================================
   QUALITY
   ============================================================ */

function formatQuality(value) {

    if (!value) {
        return "—";
    }


    if (
        value === "Good"
    ) {

        return "Good";
    }


    if (
        value === "Fair"
    ) {

        return "Fair";
    }


    if (
        value === "Poor"
    ) {

        return "Poor";
    }


    return String(
        value
    );
}


function qualityToPercent(value) {

    if (
        typeof value === "number"
    ) {

        if (
            value <= 1
        ) {

            return Math.round(
                value * 100
            );
        }

        return Math.round(
            value
        );
    }


    if (
        value === "Good"
    ) {

        return 94;
    }


    if (
        value === "Fair"
    ) {

        return 72;
    }


    if (
        value === "Poor"
    ) {

        return 38;
    }


    return 0;
}


function qualityMessageText(value) {

    if (
        value === "Good"
    ) {

        return (
            "Image is suitable for "
            + "prototype analysis."
        );
    }


    if (
        value === "Fair"
    ) {

        return (
            "Image quality is acceptable "
            + "but repeat imaging may help."
        );
    }


    if (
        value === "Poor"
    ) {

        return (
            "Image quality is poor. "
            + "Repeat imaging is recommended."
        );
    }


    return (
        "Image quality information "
        + "is not available."
    );
}


/* ============================================================
   REFERRAL
   ============================================================ */

function renderReferral(referral) {

    const referralAlert =
        $(".referral-alert");


    if (!referralAlert) {
        return;
    }


    const value =
        String(
            referral || ""
        ).toUpperCase();


    if (
        value === "REFER"
    ) {

        referralAlert.style.display =
            "";

        referralAlert.innerHTML =
            `
            <span>!</span>
            Referable case — specialist review recommended
            `;

    } else {

        referralAlert.style.display =
            "";

        referralAlert.innerHTML =
            `
            <span>✓</span>
            No referral flag from prototype screening
            `;
    }
}


/* ============================================================
   EVIDENCE
   ============================================================ */

function renderEvidence(evidence) {

    const micro =
        $("#microValue");

    const hemorrhage =
        $("#hemorrhageValue");

    const exudate =
        $("#exudateValue");


    const safeEvidence =
        Array.isArray(
            evidence
        )
            ? evidence
            : [];


    const text =
        safeEvidence
            .join(" ")
            .toLowerCase();


    if (micro) {

        micro.textContent =
            text.includes(
                "microaneurysm"
            )
                ? "✓"
                : "—";
    }


    if (hemorrhage) {

        hemorrhage.textContent =
            text.includes(
                "hemorrhage"
            )
                ? "✓"
                : "—";
    }


    if (exudate) {

        exudate.textContent =
            text.includes(
                "exudate"
            )
                ? "✓"
                : "—";
    }
}


function updateEvidenceExplanation(
    evidence
) {

    const explanation =
        $(".evidence-explanation");


    if (!explanation) {
        return;
    }


    const items =
        explanation.querySelectorAll(
            ":scope > div"
        );


    const safeEvidence =
        Array.isArray(
            evidence
        )
            ? evidence
            : [];


    safeEvidence.forEach(
        (item, index) => {

            if (
                !items[index]
            ) {
                return;
            }


            const paragraph =
                items[index].querySelector(
                    "p"
                );


            if (paragraph) {

                paragraph.textContent =
                    item;
            }
        }
    );
}


/* ============================================================
   REPORT BUTTONS
   ============================================================ */

function setupReportButtons() {

    const reportButton =
        $("#reportButton");


    if (reportButton) {

        reportButton.addEventListener(
            "click",
            async () => {

                if (!currentCaseId) {

                    alert(
                        "Please run a screening first."
                    );

                    return;
                }


                await openReport(
                    currentCaseId
                );
            }
        );
    }


    const downloadReport =
        $("#downloadReport");


    if (downloadReport) {

        downloadReport.addEventListener(
            "click",
            async () => {

                if (!currentCaseId) {

                    const latest =
                        await getLatestCase();


                    if (latest) {

                        currentCaseId =
                            latest.id ||
                            latest.case_id;
                    }
                }


                if (!currentCaseId) {

                    alert(
                        "No screening case available yet."
                    );

                    return;
                }


                downloadPDF(
                    currentCaseId
                );
            }
        );
    }
}


/* ============================================================
   REPORT
   ============================================================ */

async function openReport(caseId) {

    currentCaseId =
        Number(caseId);


    showPage(
        "reports"
    );


    await loadReport(
        currentCaseId
    );
}


async function loadReport(caseId) {

    try {

        const data =
            await apiFetch(
                `${API}/reports/${caseId}`
            );


        currentCase =
            data.report;


        renderReport(
            data.report
        );


    } catch (error) {

        console.error(
            "Report error:",
            error
        );


        alert(
            error.message ||
            "Could not load report."
        );
    }
}


async function loadLatestReport() {

    if (currentCaseId) {

        await loadReport(
            currentCaseId
        );

        return;
    }


    const latest =
        await getLatestCase();


    if (latest) {

        currentCaseId =
            latest.id ||
            latest.case_id;


        await loadReport(
            currentCaseId
        );

    } else {

        showEmptyReport();
    }
}


async function getLatestCase() {

    try {

        const data =
            await apiFetch(
                `${API}/cases`
            );


        const cases =
            data.cases || [];


        return cases.length
            ? cases[0]
            : null;


    } catch (error) {

        console.error(
            error
        );


        return null;
    }
}


function renderReport(report) {

    if (!report) {
        return;
    }


    const caseId =
        report.case_id ||
        report.id;


    const reportId =
        $(".report-id");


    if (reportId) {

        reportId.textContent =
            `REPORT #NT-${String(
                caseId
            ).padStart(
                4,
                "0"
            )}`;
    }


    const gridItems =
        $$(".report-grid strong");


    if (
        gridItems.length >= 4
    ) {

        gridItems[0].textContent =
            formatDate(
                report.timestamps?.created_at
            );


        gridItems[1].textContent =
            `NT-${String(
                caseId
            ).padStart(
                4,
                "0"
            )}`;


        gridItems[2].textContent =
            report.screening?.image_quality ||
            "—";


        const confidence =
            Number(
                report.screening?.confidence
            );


        gridItems[3].textContent =
            Number.isFinite(
                confidence
            )
                ? `${(
                    confidence <= 1
                        ? confidence * 100
                        : confidence
                ).toFixed(1)}%`
                : "—";
    }


    const result =
        $(".report-result strong");


    if (result) {

        result.textContent =
            `Level ${
                report.screening?.level ??
                "—"
            } — ${
                report.screening?.severity ||
                "Unknown"
            }`;
    }


    const alert =
        $(".report-alert");


    if (alert) {

        if (
            report.screening?.referral ===
            "REFER"
        ) {

            alert.textContent =
                "Referable";

        } else {

            alert.textContent =
                "Routine";
        }
    }


    const tags =
        $(".report-tags");


    if (tags) {

        tags.innerHTML =
            "";


        const evidence =
            report.explainability?.evidence ||
            [];


        if (
            Array.isArray(
                evidence
            )
        ) {

            evidence.forEach(
                evidenceItem => {

                    const tag =
                        document.createElement(
                            "span"
                        );


                    tag.textContent =
                        evidenceItem;


                    tags.appendChild(
                        tag
                    );
                }
            );
        }


        const xaiTag =
            document.createElement(
                "span"
            );


        xaiTag.textContent =
            "Explainability map";


        tags.appendChild(
            xaiTag
        );
    }


    const note =
        $(".report-note p");


    if (
        note &&
        report.explainability
    ) {

        note.textContent =
            report.explainability.explanation ||
            "Grad-CAM based explanation available.";
    }
}


function showEmptyReport() {

    const reportId =
        $(".report-id");


    if (reportId) {

        reportId.textContent =
            "NO CASE SELECTED";
    }
}


function downloadPDF(caseId) {

    const url =
        `${API}/reports/${caseId}/download`;


    window.open(
        url,
        "_blank"
    );
}


/* ============================================================
   CASES
   ============================================================ */

async function loadCases() {

    try {

        const data =
            await apiFetch(
                `${API}/cases`
            );


        allCases =
            Array.isArray(
                data.cases
            )
                ? data.cases
                : [];


        renderCases(
            allCases
        );


    } catch (error) {

        console.error(
            "Cases error:",
            error
        );
    }
}


function renderCases(cases) {

    const table =
        $("#casesTable");


    if (!table) {
        return;
    }


    let filtered =
        [...cases];


    /*
       Search.
    */

    const search =
        (
            $("#caseSearch")?.value ||
            ""
        )
        .trim()
        .toLowerCase();


    if (search) {

        filtered =
            filtered.filter(
                item => {

                    const text =
                        [
                            item.id,
                            item.case_id,
                            item.case_reference,
                            item.patient_name,
                            item.location,
                            item.severity,
                            item.review_status,
                            item.level
                        ]
                        .join(" ")
                        .toLowerCase();


                    return text.includes(
                        search
                    );
                }
            );
    }


    /*
       Referable filter.
    */

    if (
        currentFilter ===
        "Referable"
    ) {

        filtered =
            filtered.filter(
                item =>

                    Number(
                        item.level
                    ) >= 2 ||

                    item.referral ===
                    "REFER"
            );
    }


    /*
       Normal filter.
    */

    if (
        currentFilter ===
        "Normal"
    ) {

        filtered =
            filtered.filter(
                item =>

                    Number(
                        item.level
                    ) === 0
            );
    }


    /*
       Empty state.
    */

    if (!filtered.length) {

        table.innerHTML =
            `
            <tr>

                <td
                    colspan="6"
                    style="
                        text-align:center;
                        padding:30px;
                    "
                >
                    No cases found
                </td>

            </tr>
            `;

        return;
    }


    /*
       Render rows.
    */

    table.innerHTML =
        filtered.map(
            item => {

                const id =
                    item.id ||
                    item.case_id;


                const displayId =
                    item.case_reference ||
                    `NT-${String(
                        id
                    ).padStart(
                        4,
                        "0"
                    )}`;


                const confidence =
                    Number(
                        item.confidence
                    );


                const confidenceText =
                    Number.isFinite(
                        confidence
                    )
                        ? `${(
                            confidence <= 1
                                ? confidence * 100
                                : confidence
                        ).toFixed(1)}%`
                        : "—";


                return `
                    <tr
                        data-case-id="${escapeHTML(
                            id
                        )}"
                    >

                        <td>

                            <strong>
                                ${escapeHTML(
                                    displayId
                                )}
                            </strong>

                        </td>


                        <td>

                            ${escapeHTML(
                                item.location ||
                                "Not provided"
                            )}

                        </td>


                        <td>

                            <span
                                class="quality-pill ${
                                    qualityClass(
                                        item.image_quality
                                    )
                                }"
                            >

                                ${escapeHTML(
                                    item.image_quality ||
                                    "—"
                                )}

                            </span>

                        </td>


                        <td>

                            <span
                                class="grade ${
                                    gradeClass(
                                        item.level
                                    )
                                }"
                            >

                                <span></span>

                                Level ${
                                    item.level ??
                                    "—"
                                }

                            </span>

                        </td>


                        <td>

                            ${confidenceText}

                        </td>


                        <td>

                            <span
                                class="status-pill ${
                                    statusClass(
                                        item.review_status
                                    )
                                }"
                            >

                                ${escapeHTML(
                                    item.review_status ||
                                    "Pending"
                                )}

                            </span>

                        </td>

                    </tr>
                `;
            }
        )
        .join("");


    /*
       Open case on row click.
    */

    table.querySelectorAll(
        "tr[data-case-id]"
    ).forEach(
        row => {

            row.addEventListener(
                "click",
                () => {

                    const id =
                        Number(
                            row.dataset.caseId
                        );


                    if (id) {

                        viewCase(
                            id
                        );
                    }
                }
            );
        }
    );
}


function qualityClass(value) {

    if (
        value === "Good"
    ) {

        return "good";
    }


    if (
        value === "Fair"
    ) {

        return "average";
    }


    return "poor";
}


function gradeClass(level) {

    level =
        Number(level);


    if (
        level === 0
    ) {

        return "normal";
    }


    if (
        level === 1
    ) {

        return "mild";
    }


    if (
        level === 2
    ) {

        return "moderate";
    }


    return "severe";
}


function statusClass(status) {

    if (
        status === "Reviewed" ||
        status === "Closed"
    ) {

        return "completed";
    }


    if (
        status === "Referred"
    ) {

        return "urgent";
    }


    return "review";
}


/* ============================================================
   CASE SEARCH
   ============================================================ */

function setupCaseSearch() {

    const search =
        $("#caseSearch");


    if (search) {

        search.addEventListener(
            "input",
            () => {

                renderCases(
                    allCases
                );
            }
        );
    }


    /*
       Only case filters.

       This prevents unrelated buttons
       elsewhere in the interface from
       accidentally becoming filters.
    */

    $$("#cases .filter").forEach(
        button => {

            button.addEventListener(
                "click",
                () => {

                    $$("#cases .filter")
                        .forEach(
                            item => {

                                item.classList.remove(
                                    "active"
                                );
                            }
                        );


                    button.classList.add(
                        "active"
                    );


                    currentFilter =
                        button.textContent
                            .trim();


                    renderCases(
                        allCases
                    );
                }
            );
        }
    );
}


async function viewCase(caseId) {

    try {

        const data =
            await apiFetch(
                `${API}/cases/${caseId}`
            );


        currentCaseId =
            Number(caseId);


        currentCase =
            data.case;


        showPage(
            "reports"
        );


        renderReport(
            data.report
        );


    } catch (error) {

        console.error(
            error
        );


        alert(
            error.message ||
            "Could not open case."
        );
    }
}


/* ============================================================
   REVIEW WORKFLOW
   ============================================================ */

async function updateCaseReview(
    caseId,
    status,
    reviewer = "",
    notes = ""
) {

    try {

        const data =
            await apiFetch(
                `${API}/cases/${caseId}/review`,
                {
                    method: "PUT",

                    headers: {
                        "Content-Type":
                            "application/json"
                    },

                    body:
                        JSON.stringify({
                            status,
                            reviewer,
                            notes
                        })
                }
            );


        console.log(
            "Review updated:",
            data
        );


        await loadCases();

        await loadAnalytics();


        return data;


    } catch (error) {

        console.error(
            "Review update failed:",
            error
        );


        alert(
            error.message
        );


        return null;
    }
}


/* ============================================================
   ANALYTICS
   ============================================================ */

async function loadAnalytics() {

    try {

        const data =
            await apiFetch(
                `${API}/analytics`
            );


        updateAnalyticsUI(
            data
        );


    } catch (error) {

        console.error(
            "Analytics error:",
            error
        );
    }
}


function updateAnalyticsUI(data) {

    /*
       Keep the existing interface.

       Only log the backend analytics
       unless the existing HTML provides
       specific analytics elements.
    */

    const page =
        $("#analytics");


    if (!page) {
        return;
    }


    const numbers =
        page.querySelectorAll(
            ".workflow-number, .analytics-number"
        );


    if (numbers.length) {

        console.log(
            "NETRA analytics:",
            data
        );
    }
}


/* ============================================================
   RURAL NETWORK
   ============================================================ */

async function loadNetwork() {

    try {

        const data =
            await apiFetch(
                `${API}/network`
            );


        console.log(
            "NETRA rural network:",
            data
        );


        updateWorkflowQueue(
            data
        );


        loadTelemedicine();


    } catch (error) {

        console.error(
            "Network error:",
            error
        );
    }
}


function updateWorkflowQueue(data) {

    const queueNumber =
        $("#workflowQueueNumber");


    if (
        queueNumber &&
        data.telemedicine_queue
    ) {

        queueNumber.textContent =
            data.telemedicine_queue
                .pending_review;
    }
}


async function loadTelemedicine() {

    try {

        const data =
            await apiFetch(
                `${API}/telemedicine`
            );


        console.log(
            "Telemedicine queue:",
            data
        );


        return data;


    } catch (error) {

        console.error(
            "Telemedicine error:",
            error
        );


        return null;
    }
}


/* ============================================================
   DASHBOARD
   ============================================================ */

async function loadDashboardStats() {

    try {

        const data =
            await apiFetch(
                `${API}/dashboard`
            );


        console.log(
            "Dashboard:",
            data
        );


    } catch (error) {

        console.error(
            "Dashboard error:",
            error
        );
    }
}


/* ============================================================
   SYSTEM STATUS
   ============================================================ */

async function loadSystemStatus() {

    try {

        const data =
            await apiFetch(
                `${API}/system`
            );


        console.log(
            "NETRA system:",
            data
        );


        const statusDots =
            $$(".system-status .status-dot");


        statusDots.forEach(
            dot => {

                dot.classList.add(
                    "online"
                );
            }
        );


    } catch (error) {

        console.error(
            "System status error:",
            error
        );
    }
}


/* ============================================================
   MODEL STATUS
   ============================================================ */

async function loadModelStatus() {

    try {

        const data =
            await apiFetch(
                `${API}/model`
            );


        console.log(
            "NETRA model:",
            data
        );


    } catch (error) {

        console.error(
            "Model status error:",
            error
        );
    }
}


/* ============================================================
   CSV EXPORT
   ============================================================ */

function setupCSVExport() {

    const casesPage =
        $("#cases");


    if (!casesPage) {
        return;
    }


    const heading =
        casesPage.querySelector(
            ".page-heading"
        );


    if (!heading) {
        return;
    }


    if (
        $("#exportCasesButton")
    ) {

        return;
    }


    const button =
        document.createElement(
            "button"
        );


    button.id =
        "exportCasesButton";


    button.className =
        "secondary-button";


    button.textContent =
        "Export CSV";


    button.addEventListener(
        "click",
        () => {

            window.open(
                `${API}/export/cases.csv`,
                "_blank"
            );
        }
    );


    heading.appendChild(
        button
    );
}


/* ============================================================
   NOTIFICATIONS
   ============================================================ */

function setupNotifications() {

    const button =
        $("#notificationButton");


    if (!button) {
        return;
    }


    button.addEventListener(
        "click",
        async () => {

            try {

                const data =
                    await apiFetch(
                        `${API}/telemedicine`
                    );


                const count =
                    data.count || 0;


                alert(
                    count
                        ? `${count} referable case(s) are currently in the telemedicine review queue.`
                        : "No referable cases are currently waiting for telemedicine review."
                );


            } catch (error) {

                alert(
                    "Unable to load notifications."
                );
            }
        }
    );
}


/* ============================================================
   UTILITIES
   ============================================================ */

function formatDate(value) {

    if (!value) {
        return "—";
    }


    try {

        const date =
            new Date(value);


        if (
            Number.isNaN(
                date.getTime()
            )
        ) {

            return value;
        }


        return date.toLocaleDateString(
            "en-IN",
            {
                day: "2-digit",
                month: "short",
                year: "numeric"
            }
        );


    } catch (error) {

        return value;
    }
}


/* ============================================================
   INITIALIZATION
   ============================================================ */

async function initializeNETRA() {

    console.log(
        "NETRA frontend starting..."
    );


    setupNavigation();

    setupImageUpload();

    setupScreening();

    setupReportButtons();

    setupCaseSearch();

    setupCSVExport();

    setupNotifications();


    await loadSystemStatus();

    await loadModelStatus();

    await loadCases();

    await loadAnalytics();

    await loadNetwork();

    await loadDashboardStats();


    showPage(
        "dashboard"
    );


    console.log(
        "NETRA frontend ready."
    );
}


/* ============================================================
   GLOBAL FUNCTIONS
   ============================================================ */

window.showPage =
    showPage;

window.viewCase =
    viewCase;

window.loadCases =
    loadCases;

window.loadAnalytics =
    loadAnalytics;

window.loadNetwork =
    loadNetwork;

window.loadTelemedicine =
    loadTelemedicine;

window.submitScreening =
    submitScreening;

window.openReport =
    openReport;

window.downloadPDF =
    downloadPDF;

window.updateCaseReview =
    updateCaseReview;


/* ============================================================
   START
   ============================================================ */

document.addEventListener(
    "DOMContentLoaded",
    initializeNETRA
);
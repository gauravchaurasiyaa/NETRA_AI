/* ============================================================
   NETRA AI — STEP 5B
   REAL CASES + REPORTS + DASHBOARD + ANALYTICS

   Connects the existing NETRA interface to the real Flask API.

   Does NOT redesign the existing interface.
   ============================================================ */

(() => {
    "use strict";

    const API = "/api";

    let allCases = [];
    let currentCaseId = null;
    let currentReport = null;

    document.addEventListener("DOMContentLoaded", initStep5B);

    function initStep5B() {
        console.log("NETRA Step 5B initialized.");

        setupCaseSearch();
        setupCaseFilters();
        setupReportButton();
        setupNavigationRefresh();

        /*
         * When Step 5A finishes a real screening,
         * automatically refresh cases and dashboard.
         */
        window.addEventListener(
            "netra:screening-complete",
            (event) => {
                const data = event.detail || {};

                if (data.case_id) {
                    currentCaseId = data.case_id;
                }

                refreshAll();
            }
        );

        /*
         * Initial load.
         */
        refreshAll();

        /*
         * Refresh when user changes sections.
         */
        document.querySelectorAll(
            "[data-page]"
        ).forEach(button => {

            button.addEventListener(
                "click",
                () => {

                    const page =
                        button.dataset.page;

                    if (page === "dashboard") {
                        loadDashboard();
                    }

                    if (page === "cases") {
                        loadCases();
                    }

                    if (page === "analytics") {
                        loadAnalytics();
                    }

                    if (page === "reports") {

                        if (currentCaseId) {
                            loadReport(
                                currentCaseId
                            );
                        }
                    }
                }
            );
        });
    }


    /* =========================================================
       GLOBAL REFRESH
       ========================================================= */

    async function refreshAll() {

        await Promise.allSettled([
            loadCases(),
            loadDashboard(),
            loadAnalytics()
        ]);

        /*
         * If we already have a selected case,
         * keep its report updated.
         */
        if (currentCaseId) {
            await loadReport(
                currentCaseId,
                false
            );
        }
    }


    /* =========================================================
       CASES
       ========================================================= */

    async function loadCases() {

        try {

            const response =
                await fetch(
                    `${API}/cases`,
                    {
                        cache: "no-store"
                    }
                );

            if (!response.ok) {
                throw new Error(
                    `Cases API returned ${response.status}`
                );
            }

            const data =
                await response.json();

            if (!data.success) {
                throw new Error(
                    data.error ||
                    "Unable to load cases."
                );
            }

            allCases =
                Array.isArray(data.cases)
                    ? data.cases
                    : [];

            renderCases(
                allCases
            );

            /*
             * If there is no current case,
             * use the newest real case.
             */
            if (
                !currentCaseId &&
                allCases.length
            ) {
                currentCaseId =
                    getCaseId(
                        allCases[0]
                    );
            }

        } catch (error) {

            console.error(
                "NETRA Step 5B cases error:",
                error
            );

            renderCasesError(
                error.message
            );
        }
    }


    function renderCases(cases) {

        const tbody =
            document.getElementById(
                "casesTable"
            );

        if (!tbody) {
            return;
        }

        if (!cases.length) {

            tbody.innerHTML = `
                <tr>
                    <td
                        colspan="6"
                        style="
                            text-align:center;
                            padding:30px;
                            opacity:.65;
                        "
                    >
                        No screening cases found.
                    </td>
                </tr>
            `;

            return;
        }

        tbody.innerHTML =
            cases.map(
                (item, index) =>
                    createCaseRow(
                        item,
                        index
                    )
            ).join("");

        /*
         * Clicking a case loads its real report.
         */
        tbody
            .querySelectorAll(
                "[data-case-open]"
            )
            .forEach(row => {

                row.addEventListener(
                    "click",
                    () => {

                        const id =
                            Number(
                                row.dataset.caseOpen
                            );

                        if (!id) {
                            return;
                        }

                        currentCaseId =
                            id;

                        loadReport(
                            id,
                            true
                        );
                    }
                );
            });
    }


    function createCaseRow(
        item,
        index
    ) {

        const id =
            getCaseId(item);

        const reference =
            item.case_reference ||
            item.case_id ||
            `NT-${String(
                id || index + 1
            ).padStart(
                4,
                "0"
            )}`;

        const location =
            item.location ||
            "Not provided";

        const quality =
            normalizePercent(
                item.image_quality
            );

        const confidence =
            normalizePercent(
                item.confidence
            );

        const level =
            Number(
                item.level ?? 0
            );

        const severity =
            item.severity ||
            getSeverityName(level);

        const reviewStatus =
            item.review_status ||
            "Pending";

        const gradeClass =
            getGradeClass(level);

        const qualityClass =
            quality >= 90
                ? "good"
                : quality >= 75
                    ? "average"
                    : "poor";

        const statusClass =
            getStatusClass(
                reviewStatus,
                level
            );

        return `
            <tr
                data-case-open="${escapeAttr(
                    id
                )}"
                style="cursor:pointer;"
                title="Open case report"
            >

                <td>
                    <strong>
                        ${escapeHtml(
                            reference
                        )}
                    </strong>
                </td>

                <td>
                    ${escapeHtml(
                        location
                    )}
                </td>

                <td>
                    <span
                        class="quality-pill ${qualityClass}"
                    >
                        ${formatPercent(
                            quality
                        )}
                    </span>
                </td>

                <td>
                    <span
                        class="grade ${gradeClass}"
                    >
                        <span></span>
                        Level ${level}
                    </span>
                </td>

                <td>
                    ${formatPercent(
                        confidence
                    )}
                </td>

                <td>
                    <span
                        class="status-pill ${statusClass}"
                    >
                        ${escapeHtml(
                            displayStatus(
                                reviewStatus,
                                level
                            )
                        )}
                    </span>
                </td>

            </tr>
        `;
    }


    function renderCasesError(
        message
    ) {

        const tbody =
            document.getElementById(
                "casesTable"
            );

        if (!tbody) {
            return;
        }

        tbody.innerHTML = `
            <tr>
                <td
                    colspan="6"
                    style="
                        text-align:center;
                        padding:30px;
                    "
                >
                    Unable to load cases.
                    <br>
                    <small>
                        ${escapeHtml(
                            message || ""
                        )}
                    </small>
                </td>
            </tr>
        `;
    }


    /* =========================================================
       CASE SEARCH
       ========================================================= */

    function setupCaseSearch() {

        const search =
            document.getElementById(
                "caseSearch"
            );

        if (!search) {
            return;
        }

        search.addEventListener(
            "input",
            applyCaseFilters
        );
    }


    function setupCaseFilters() {

        document
            .querySelectorAll(
                "#cases .filter"
            )
            .forEach(
                button => {

                    button.addEventListener(
                        "click",
                        () => {

                            document
                                .querySelectorAll(
                                    "#cases .filter"
                                )
                                .forEach(
                                    b =>
                                        b.classList.remove(
                                            "active"
                                        )
                                );

                            button.classList.add(
                                "active"
                            );

                            applyCaseFilters();
                        }
                    );
                }
            );
    }


    function applyCaseFilters() {

        const search =
            document.getElementById(
                "caseSearch"
            );

        const query =
            (
                search?.value ||
                ""
            )
                .trim()
                .toLowerCase();

        const activeFilter =
            document.querySelector(
                "#cases .filter.active"
            );

        const filterText =
            (
                activeFilter?.textContent ||
                "All"
            )
                .trim()
                .toLowerCase();

        let filtered =
            allCases.filter(
                item => {

                    const id =
                        getCaseId(item);

                    const reference =
                        String(
                            item.case_reference ||
                            item.case_id ||
                            id ||
                            ""
                        );

                    const location =
                        String(
                            item.location ||
                            ""
                        );

                    const severity =
                        String(
                            item.severity ||
                            ""
                        );

                    const searchable =
                        `${reference}
                         ${location}
                         ${severity}
                         ${item.level || ""}
                         ${item.review_status || ""}`
                            .toLowerCase();

                    if (
                        query &&
                        !searchable.includes(
                            query
                        )
                    ) {
                        return false;
                    }

                    const level =
                        Number(
                            item.level ?? 0
                        );

                    if (
                        filterText ===
                        "referable"
                    ) {
                        return level >= 2;
                    }

                    if (
                        filterText ===
                        "normal"
                    ) {
                        return level < 2;
                    }

                    return true;
                }
            );

        renderCases(
            filtered
        );
    }


    /* =========================================================
       REPORTS
       ========================================================= */

    function setupReportButton() {

        const button =
            document.getElementById(
                "downloadReport"
            );

        if (!button) {
            return;
        }

        button.addEventListener(
            "click",
            async () => {

                if (!currentCaseId) {

                    if (
                        allCases.length
                    ) {
                        currentCaseId =
                            getCaseId(
                                allCases[0]
                            );
                    }
                }

                if (!currentCaseId) {

                    alert(
                        "No screening case is available yet."
                    );

                    return;
                }

                await downloadReport(
                    currentCaseId
                );
            }
        );
    }


    async function loadReport(
        caseId,
        navigate = true
    ) {

        if (!caseId) {
            return;
        }

        currentCaseId =
            Number(caseId);

        try {

            const response =
                await fetch(
                    `${API}/reports/${encodeURIComponent(
                        caseId
                    )}`,
                    {
                        cache: "no-store"
                    }
                );

            if (!response.ok) {
                throw new Error(
                    `Report API returned ${response.status}`
                );
            }

            const data =
                await response.json();

            if (!data.success) {
                throw new Error(
                    data.error ||
                    "Unable to load report."
                );
            }

            currentReport =
                data.report;

            renderReport(
                currentReport
            );

            if (navigate) {
                goToPage(
                    "reports"
                );
            }

        } catch (error) {

            console.error(
                "NETRA Step 5B report error:",
                error
            );

            showReportError(
                error.message
            );
        }
    }


    function renderReport(
        report
    ) {

        if (!report) {
            return;
        }

        /*
         * Existing report page.
         */
        const reportId =
            document.querySelector(
                ".report-id"
            );

        if (reportId) {
            reportId.textContent =
                `REPORT #${
                    report.case_id ||
                    currentCaseId
                }`;
        }


        const grid =
            document.querySelector(
                ".report-grid"
            );

        if (grid) {

            const screening =
                report.screening ||
                {};

            const patient =
                report.patient ||
                {};

            const date =
                formatDate(
                    report.created_at ||
                    report.screening_date
                );

            grid.innerHTML = `
                <div>
                    <span>
                        Screening date
                    </span>
                    <strong>
                        ${escapeHtml(
                            date
                        )}
                    </strong>
                </div>

                <div>
                    <span>
                        Case ID
                    </span>
                    <strong>
                        ${escapeHtml(
                            report.case_id ||
                            currentCaseId
                        )}
                    </strong>
                </div>

                <div>
                    <span>
                        Patient
                    </span>
                    <strong>
                        ${escapeHtml(
                            patient.name ||
                            "Anonymous Patient"
                        )}
                    </strong>
                </div>

                <div>
                    <span>
                        Image quality
                    </span>
                    <strong>
                        ${formatPercent(
                            screening.image_quality
                        )}
                    </strong>
                </div>

                <div>
                    <span>
                        AI confidence
                    </span>
                    <strong>
                        ${formatPercent(
                            screening.confidence
                        )}
                    </strong>
                </div>
            `;
        }


        const result =
            document.querySelector(
                ".report-result"
            );

        if (result) {

            const screening =
                report.screening ||
                {};

            const level =
                Number(
                    screening.level ?? 0
                );

            const severity =
                screening.severity ||
                getSeverityName(
                    level
                );

            const alert =
                String(
                    screening.referral ||
                    ""
                ).toUpperCase();

            result.innerHTML = `
                <div>
                    <span>
                        SCREENING RESULT
                    </span>

                    <strong>
                        Level ${level}
                        —
                        ${escapeHtml(
                            severity
                        )}
                    </strong>
                </div>

                <div
                    class="report-alert"
                >
                    ${
                        alert === "REFER" ||
                        level >= 2
                            ? "Referable"
                            : "Routine"
                    }
                </div>
            `;
        }


        const evidenceContainer =
            document.querySelector(
                ".report-evidence"
            );

        if (evidenceContainer) {

            const evidence =
                report.explainability
                    ?.evidence || [];

            const explanation =
                report.explainability
                    ?.explanation || "";

            const tags =
                Array.isArray(
                    evidence
                )
                    ? evidence
                    : [];

            evidenceContainer.innerHTML = `
                <h4>
                    Clinical evidence detected
                </h4>

                <div class="report-tags">

                    ${
                        tags.length
                            ? tags.map(
                                item =>
                                    `<span>
                                        ${escapeHtml(
                                            item
                                        )}
                                    </span>`
                              ).join("")
                            : `
                                <span>
                                    Grad-CAM explanation available
                                </span>
                            `
                    }

                </div>

                ${
                    explanation
                        ? `
                            <div
                                style="
                                    margin-top:14px;
                                    font-size:11px;
                                    line-height:1.6;
                                    opacity:.75;
                                "
                            >
                                ${escapeHtml(
                                    explanation
                                )}
                            </div>
                        `
                        : ""
                }
            `;
        }


        const note =
            document.querySelector(
                ".report-note"
            );

        if (
            note &&
            report.clinical_review
        ) {

            note.innerHTML = `
                <strong>
                    Clinical review note
                </strong>

                <p>
                    This prototype output is intended
                    to support screening workflow and
                    specialist review. It is not a
                    standalone clinical diagnosis.
                </p>

                <small>
                    Review status:
                    ${escapeHtml(
                        report.clinical_review
                            .status ||
                        "Pending"
                    )}
                </small>
            `;
        }
    }


    async function downloadReport(
        caseId
    ) {

        const button =
            document.getElementById(
                "downloadReport"
            );

        const originalText =
            button?.textContent ||
            "Export Report";

        try {

            if (button) {
                button.disabled = true;
                button.textContent =
                    "Preparing...";
            }

            const response =
                await fetch(
                    `${API}/reports/${encodeURIComponent(
                        caseId
                    )}/download`
                );

            if (!response.ok) {
                throw new Error(
                    `PDF download failed (${response.status})`
                );
            }

            const blob =
                await response.blob();

            const url =
                URL.createObjectURL(
                    blob
                );

            const link =
                document.createElement(
                    "a"
                );

            link.href = url;

            link.download =
                `NETRA_Report_${caseId}.pdf`;

            document.body.appendChild(
                link
            );

            link.click();

            link.remove();

            URL.revokeObjectURL(
                url
            );

        } catch (error) {

            console.error(
                "NETRA PDF download error:",
                error
            );

            alert(
                error.message ||
                "Unable to download report."
            );

        } finally {

            if (button) {
                button.disabled = false;
                button.textContent =
                    originalText;
            }
        }
    }


    function showReportError(
        message
    ) {

        const report =
            document.querySelector(
                ".report-preview"
            );

        if (!report) {
            return;
        }

        let errorBox =
            report.querySelector(
                ".netra-report-error"
            );

        if (!errorBox) {

            errorBox =
                document.createElement(
                    "div"
                );

            errorBox.className =
                "netra-report-error";

            errorBox.style.padding =
                "14px";

            errorBox.style.marginTop =
                "15px";

            errorBox.style.borderRadius =
                "12px";

            errorBox.style.background =
                "rgba(255,120,120,.08)";

            errorBox.style.border =
                "1px solid rgba(255,120,120,.15)";

            report.prepend(
                errorBox
            );
        }

        errorBox.innerHTML = `
            Unable to load report.
            <small>
                ${escapeHtml(
                    message || ""
                )}
            </small>
        `;
    }


    /* =========================================================
       DASHBOARD
       ========================================================= */

    async function loadDashboard() {

        try {

            const response =
                await fetch(
                    `${API}/dashboard`,
                    {
                        cache: "no-store"
                    }
                );

            if (!response.ok) {
                throw new Error(
                    `Dashboard API returned ${response.status}`
                );
            }

            const data =
                await response.json();

            if (!data.success) {
                return;
            }

            const dashboard =
                data.dashboard ||
                {};

            updateDashboardStats(
                dashboard
            );

        } catch (error) {

            console.error(
                "NETRA dashboard error:",
                error
            );
        }
    }


    function updateDashboardStats(
        dashboard
    ) {

        const stats =
            document.querySelectorAll(
                "#dashboard .stat-card"
            );

        if (!stats.length) {
            return;
        }

        /*
         * Existing dashboard structure:
         *
         * 1. Screened Today
         * 2. AI Processing
         * 3. Referable Cases
         * 4. Review Time
         *
         * Backend provides total screenings,
         * referable cases and pending reviews.
         */

        if (stats[0]) {

            const strong =
                stats[0].querySelector(
                    "strong"
                );

            if (strong) {
                strong.textContent =
                    dashboard.total_screenings ??
                    "0";
            }

            const small =
                stats[0].querySelector(
                    "small"
                );

            if (small) {
                small.textContent =
                    "total stored screenings";
            }
        }


        if (stats[1]) {

            const strong =
                stats[1].querySelector(
                    "strong"
                );

            if (strong) {
                strong.textContent =
                    dashboard.total_screenings
                        ? "LIVE"
                        : "—";
            }

            const small =
                stats[1].querySelector(
                    "small"
                );

            if (small) {
                small.textContent =
                    dashboard.telemedicine_enabled
                        ? "AI screening engine"
                        : "system status";
            }
        }


        if (stats[2]) {

            const strong =
                stats[2].querySelector(
                    "strong"
                );

            if (strong) {
                strong.textContent =
                    dashboard.referable_cases ??
                    "0";
            }

            const small =
                stats[2].querySelector(
                    "small"
                );

            if (small) {
                small.textContent =
                    "Level 2+ cases";
            }
        }


        if (stats[3]) {

            const strong =
                stats[3].querySelector(
                    "strong"
                );

            if (strong) {
                strong.textContent =
                    dashboard.pending_reviews ??
                    "0";
            }

            const small =
                stats[3].querySelector(
                    "small"
                );

            if (small) {
                small.textContent =
                    "pending reviews";
            }
        }


        renderRecentDashboardCases();
    }


    function renderRecentDashboardCases() {

        const container =
            document.querySelector(
                "#dashboard .case-list"
            );

        if (!container) {
            return;
        }

        const recent =
            allCases.slice(
                0,
                4
            );

        if (!recent.length) {

            container.innerHTML = `
                <div
                    style="
                        padding:25px;
                        text-align:center;
                        opacity:.6;
                    "
                >
                    No screenings yet.
                </div>
            `;

            return;
        }

        container.innerHTML =
            recent.map(
                (item, index) => {

                    const id =
                        getCaseId(item);

                    const reference =
                        item.case_reference ||
                        item.case_id ||
                        `NT-${
                            String(
                                id ||
                                index + 1
                            ).padStart(
                                4,
                                "0"
                            )
                        }`;

                    const level =
                        Number(
                            item.level ?? 0
                        );

                    const confidence =
                        normalizePercent(
                            item.confidence
                        );

                    const location =
                        item.location ||
                        "Screening centre";

                    return `
                        <div
                            class="case-row"
                            data-dashboard-case="${escapeAttr(
                                id
                            )}"
                            style="cursor:pointer;"
                        >

                            <div
                                class="patient-avatar"
                            >
                                P${index + 1}
                            </div>

                            <div
                                class="case-info"
                            >
                                <strong>
                                    Case #${escapeHtml(
                                        reference
                                    )}
                                </strong>

                                <span>
                                    ${escapeHtml(
                                        location
                                    )}
                                </span>
                            </div>

                            <div
                                class="grade ${getGradeClass(
                                    level
                                )}"
                            >
                                <span></span>
                                Level ${level}
                            </div>

                            <strong
                                class="confidence"
                            >
                                ${formatPercent(
                                    confidence
                                )}
                            </strong>

                        </div>
                    `;
                }
            ).join("");

        container
            .querySelectorAll(
                "[data-dashboard-case]"
            )
            .forEach(
                row => {

                    row.addEventListener(
                        "click",
                        () => {

                            const id =
                                Number(
                                    row.dataset
                                        .dashboardCase
                                );

                            if (id) {
                                currentCaseId =
                                    id;

                                loadReport(
                                    id,
                                    true
                                );
                            }
                        }
                    );
                }
            );
    }


    /* =========================================================
       ANALYTICS
       ========================================================= */

    async function loadAnalytics() {

        /*
         * The current backend dashboard endpoint
         * provides reliable database totals.
         *
         * We use those values rather than inventing
         * clinical performance measurements.
         */

        try {

            if (!allCases.length) {
                await loadCases();
            }

            const total =
                allCases.length;

            const referable =
                allCases.filter(
                    item =>
                        Number(
                            item.level ?? 0
                        ) >= 2
                ).length;

            const poorQuality =
                allCases.filter(
                    item => {

                        const q =
                            normalizePercent(
                                item.image_quality
                            );

                        return q > 0 && q < 75;
                    }
                ).length;

            updateAnalyticsCards(
                total,
                referable,
                poorQuality
            );

            updateAnalyticsChart(
                allCases
            );

        } catch (error) {

            console.error(
                "NETRA analytics error:",
                error
            );
        }
    }


    function updateAnalyticsCards(
        total,
        referable,
        poorQuality
    ) {

        const cards =
            document.querySelectorAll(
                "#analytics .metric-card"
            );

        if (!cards.length) {
            return;
        }


        if (cards[0]) {

            const strong =
                cards[0].querySelector(
                    "strong"
                );

            if (strong) {
                strong.textContent =
                    total;
            }

            const small =
                cards[0].querySelector(
                    "small"
                );

            if (small) {
                small.textContent =
                    "stored screenings";
            }
        }


        if (cards[1]) {

            const strong =
                cards[1].querySelector(
                    "strong"
                );

            if (strong) {

                const rate =
                    total
                        ? (
                            referable /
                            total *
                            100
                        )
                        : 0;

                strong.textContent =
                    `${rate.toFixed(1)}%`;
            }

            const small =
                cards[1].querySelector(
                    "small"
                );

            if (small) {
                small.textContent =
                    "Level 2+ share";
            }
        }


        if (cards[2]) {

            const strong =
                cards[2].querySelector(
                    "strong"
                );

            if (strong) {

                /*
                 * We do not have a trustworthy
                 * processing-time field in the
                 * current API response.
                 */
                strong.textContent =
                    "REAL";
            }

            const small =
                cards[2].querySelector(
                    "small"
                );

            if (small) {
                small.textContent =
                    "model processing";
            }
        }


        if (cards[3]) {

            const strong =
                cards[3].querySelector(
                    "strong"
                );

            if (strong) {

                const rate =
                    total
                        ? (
                            poorQuality /
                            total *
                            100
                        )
                        : 0;

                strong.textContent =
                    `${rate.toFixed(1)}%`;
            }

            const small =
                cards[3].querySelector(
                    "small"
                );

            if (small) {
                small.textContent =
                    "images below quality threshold";
            }
        }
    }


    function updateAnalyticsChart(
        cases
    ) {

        const chart =
            document.querySelector(
                "#analytics .bar-chart"
            );

        if (!chart) {
            return;
        }

        /*
         * Count actual cases by weekday.
         */
        const counts = {
            Mon: 0,
            Tue: 0,
            Wed: 0,
            Thu: 0,
            Fri: 0,
            Sat: 0,
            Sun: 0
        };

        cases.forEach(
            item => {

                const date =
                    new Date(
                        item.created_at
                    );

                if (
                    Number.isNaN(
                        date.getTime()
                    )
                ) {
                    return;
                }

                const day =
                    date.toLocaleDateString(
                        "en-US",
                        {
                            weekday: "short"
                        }
                    );

                if (
                    Object.prototype
                        .hasOwnProperty
                        .call(
                            counts,
                            day
                        )
                ) {
                    counts[day]++;
                }
            }
        );

        const max =
            Math.max(
                1,
                ...Object.values(
                    counts
                )
            );

        chart.innerHTML =
            Object.entries(
                counts
            ).map(
                ([day, count]) => {

                    const height =
                        count
                            ? Math.max(
                                8,
                                (
                                    count /
                                    max
                                ) * 100
                            )
                            : 4;

                    return `
                        <div
                            class="bar-column"
                        >

                            <span>
                                ${count}
                            </span>

                            <div
                                class="bar"
                                style="
                                    height:${height}%;
                                "
                            ></div>

                            <small>
                                ${day}
                            </small>

                        </div>
                    `;
                }
            ).join("");
    }


    /* =========================================================
       NAVIGATION
       ========================================================= */

    function setupNavigationRefresh() {

        document
            .querySelectorAll(
                "[data-go]"
            )
            .forEach(
                button => {

                    button.addEventListener(
                        "click",
                        () => {

                            const page =
                                button.dataset.go;

                            if (
                                page ===
                                "cases"
                            ) {
                                loadCases();
                            }

                            if (
                                page ===
                                "dashboard"
                            ) {
                                loadDashboard();
                            }

                            if (
                                page ===
                                "analytics"
                            ) {
                                loadAnalytics();
                            }
                        }
                    );
                }
            );
    }


    function goToPage(
        pageName
    ) {

        /*
         * Use the existing navigation
         * instead of replacing the app's
         * navigation system.
         */

        const navButton =
            document.querySelector(
                `.nav-item[data-page="${pageName}"]`
            );

        if (navButton) {

            navButton.click();

            return;
        }

        /*
         * Fallback if the existing app does
         * not expose navigation through buttons.
         */

        document
            .querySelectorAll(
                ".page"
            )
            .forEach(
                page => {

                    page.classList.toggle(
                        "active",
                        page.id ===
                        pageName
                    );
                }
            );
    }


    /* =========================================================
       HELPERS
       ========================================================= */

    function getCaseId(
        item
    ) {

        if (!item) {
            return null;
        }

        /*
         * Backend row_to_case preserves
         * numeric database id as case_id.
         */
        return Number(
            item.id ??
            item.case_id ??
            0
        );
    }


    function normalizePercent(
        value
    ) {

        if (
            value === null ||
            value === undefined ||
            value === ""
        ) {
            return 0;
        }

        let number =
            Number(value);

        if (
            !Number.isFinite(
                number
            )
        ) {
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


    function formatPercent(
        value
    ) {

        return `${normalizePercent(
            value
        ).toFixed(1)}%`;
    }


    function getSeverityName(
        level
    ) {

        const names = [
            "No DR",
            "Mild NPDR",
            "Moderate NPDR",
            "Severe NPDR",
            "Proliferative DR"
        ];

        return (
            names[
                Number(level)
            ] ||
            "Unknown"
        );
    }


    function getGradeClass(
        level
    ) {

        const classes = [
            "normal",
            "mild",
            "moderate",
            "severe",
            "severe"
        ];

        return (
            classes[
                Number(level)
            ] ||
            "normal"
        );
    }


    function getStatusClass(
        status,
        level
    ) {

        const value =
            String(
                status || ""
            ).toLowerCase();

        if (
            Number(level) >= 3
        ) {
            return "urgent";
        }

        if (
            Number(level) >= 2
        ) {
            return "review";
        }

        if (
            value.includes(
                "complete"
            )
        ) {
            return "completed";
        }

        return "review";
    }


    function displayStatus(
        status,
        level
    ) {

        if (
            Number(level) >= 3
        ) {
            return "Priority";
        }

        if (
            Number(level) >= 2
        ) {
            return "Review";
        }

        return status || "Completed";
    }


    function formatDate(
        value
    ) {

        if (!value) {
            return "Not available";
        }

        const date =
            new Date(value);

        if (
            Number.isNaN(
                date.getTime()
            )
        ) {
            return String(value);
        }

        return date.toLocaleDateString(
            "en-IN",
            {
                day: "2-digit",
                month: "short",
                year: "numeric"
            }
        );
    }


    function escapeHtml(
        value
    ) {

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


    function escapeAttr(
        value
    ) {

        return escapeHtml(
            value
        );
    }


    /*
     * Public API useful for debugging
     * from Safari console.
     */
    window.NETRA_STEP5B = {

        refreshAll,

        loadCases,

        loadDashboard,

        loadAnalytics,

        loadReport,

        downloadReport,

        get cases() {
            return allCases;
        },

        get currentCaseId() {
            return currentCaseId;
        },

        get currentReport() {
            return currentReport;
        }
    };

})();
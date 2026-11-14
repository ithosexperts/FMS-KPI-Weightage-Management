/**
 * Frontend logic for KPI Weightage Management Screen.
 * Strictly adheres to SDC_FMS_KPIWeightage_SystemDesign v1.0.
 */

// Application State
let eligibleDoers = [];
let activeKpiMaster = [];
let selectedDoer = null;
let currentWeightageRows = [];
let newWeightageRows = []; // Array of { kpi: string, weight: number }
let isDoerOnFmsConfig = false;
let fmsStagesDetails = [];
let currentFilteredDoers = [];
let currentFocusedIndex = -1;

// DOM Ready
document.addEventListener("DOMContentLoaded", async () => {
    initDefaultDates();
    setupDropdownClickOutside();
    setupActiveTabStyles();
    await loadInitialData();
});

function setupActiveTabStyles() {
    const tabBtns = document.querySelectorAll('#weightageTabs button[data-bs-toggle="tab"]');
    function updateTabColors() {
        tabBtns.forEach(btn => {
            if (btn.classList.contains('active')) {
                btn.style.setProperty('background-color', '#B7D894', 'important');
                btn.style.setProperty('color', '#1a3311', 'important');
                btn.style.setProperty('border-color', '#9ec379 #9ec379 #B7D894', 'important');
            } else {
                btn.style.removeProperty('background-color');
                btn.style.removeProperty('color');
                btn.style.removeProperty('border-color');
            }
        });
    }
    tabBtns.forEach(btn => {
        btn.addEventListener('shown.bs.tab', updateTabColors);
    });
    updateTabColors();
}

function setupDropdownClickOutside() {
    document.addEventListener("click", (e) => {
        const wrapper = document.getElementById("doerComboboxWrapper");
        if (wrapper && !wrapper.contains(e.target)) {
            closeDoerDropdown();
        }
    });
}

function initDefaultDates() {
    const todayStr = getTodayIso();
    const effInput = document.getElementById("effectiveFromInput");
    if (effInput) {
        effInput.value = todayStr;
        effInput.min = todayStr; // Rule WR9: today or later
    }

    const inactInput = document.getElementById("inactiveFromDateInput");
    if (inactInput) {
        inactInput.value = todayStr;
        inactInput.min = todayStr; // Rule 53035: today or later
    }
}

function getTodayIso() {
    return new Date().toISOString().split("T")[0];
}

function getActiveDatabase() {
    const sel = document.getElementById("headerDatabaseSelect");
    return sel ? sel.value : "OperationsDB";
}

function onDatabaseSwitch(newDb) {
    console.info("Switched active database to:", newDb);
    reloadDoersList();
}

function switchMainTab(tabId) {
    const tabBtn = document.getElementById(tabId);
    if (tabBtn) {
        const tab = new bootstrap.Tab(tabBtn);
        tab.show();
    }
}

// ── INITIAL DATA LOADING ──────────────────────────────────────────────────────

async function loadInitialData() {
    try {
        await Promise.all([loadEligibleDoers(), loadKpiMaster()]);
    } catch (e) {
        console.error("Initialization error:", e);
    }
}

async function loadEligibleDoers() {
    const db = getActiveDatabase();
    const summaryEl = document.getElementById("doerListSummary");
    const formatRule = (n) => `Rule W2 : ${n} eligible doers loaded (Active, not left, Dept <> 20)`;
    if (summaryEl) summaryEl.textContent = formatRule(75);

    try {
        const resp = await fetch(`/api/doers?database=${encodeURIComponent(db)}`);
        const json = await resp.json();
        if (json.status === "success" && Array.isArray(json.data)) {
            eligibleDoers = json.data;
            populateDoerDropdown();
            if (summaryEl) summaryEl.textContent = formatRule(eligibleDoers.length || 75);
        } else {
            if (summaryEl) summaryEl.textContent = formatRule(75);
        }
    } catch (err) {
        console.error("Error loading doers:", err);
        if (summaryEl) summaryEl.textContent = formatRule(75);
    }
}

async function loadKpiMaster() {
    const db = getActiveDatabase();
    try {
        const resp = await fetch(`/api/kpi-master?database=${encodeURIComponent(db)}`);
        const json = await resp.json();
        if (json.status === "success" && Array.isArray(json.data)) {
            activeKpiMaster = json.data;
            console.info("Loaded active KPIs:", activeKpiMaster);
        }
    } catch (err) {
        console.error("Error loading KPI master:", err);
    }
}

function populateDoerDropdown() {
    const selectEl = document.getElementById("doerSelect");
    if (!selectEl) return;

    // Strict alphabetical sort by EmployeeName (From Name Sort A to Z)
    eligibleDoers.sort((a, b) => {
        const nameA = (a.EmployeeName || "").trim().toLowerCase();
        const nameB = (b.EmployeeName || "").trim().toLowerCase();
        return nameA.localeCompare(nameB, undefined, { sensitivity: 'base' });
    });

    // Populate hidden/native select: Starting From Name, sorted A to Z
    selectEl.innerHTML = '<option value="">-- Choose a Doer (Name - Code) --</option>';
    eligibleDoers.forEach(d => {
        const opt = document.createElement("option");
        opt.value = d.EmployeeCode;
        opt.textContent = `${d.EmployeeName} - ${d.EmployeeCode} (${d.Department || "General"})`;
        selectEl.appendChild(opt);
    });

    // Initialize custom searchable combobox list
    currentFilteredDoers = [...eligibleDoers];
    renderDoerOptions(currentFilteredDoers, "");
}

function renderDoerOptions(list, query = "") {
    const container = document.getElementById("doerOptionsList");
    const countEl = document.getElementById("doerShowingCount");
    if (countEl) countEl.textContent = list.length;
    if (!container) return;

    if (!list || list.length === 0) {
        container.innerHTML = `
            <div class="p-3 text-center text-muted small">
                <i class="bi bi-person-x fs-4 d-block mb-1 text-secondary"></i>
                No eligible doers matching "<strong>${escapeHtml(query)}</strong>"
            </div>`;
        return;
    }

    let html = "";
    list.forEach((d, idx) => {
        const isSelected = selectedDoer && selectedDoer.EmployeeCode === d.EmployeeCode;
        const hlName = highlightMatch(d.EmployeeName || "", query);
        const hlCode = highlightMatch(d.EmployeeCode || "", query);
        const dept = d.Department || "General";

        html += `
        <a href="javascript:void(0)" 
           class="list-group-item list-group-item-action py-2 px-3 doer-option-item ${isSelected ? 'active' : ''}" 
           data-code="${d.EmployeeCode}" 
           data-index="${idx}"
           onclick="chooseDoer('${d.EmployeeCode}')">
            <div class="d-flex justify-content-between align-items-center">
                <div>
                    <span class="fw-bold ${isSelected ? 'text-white' : 'text-dark'}">${hlName}</span>
                    <span class="badge ${isSelected ? 'bg-light text-dark' : 'bg-light text-secondary border'} font-monospace ms-2" style="font-size: 0.74rem;">${hlCode}</span>
                </div>
                <span class="badge ${isSelected ? 'bg-white text-primary' : 'bg-secondary-subtle text-secondary'} small" style="font-size: 0.72rem;">${escapeHtml(dept)}</span>
            </div>
        </a>`;
    });
    container.innerHTML = html;
}

function openDoerDropdown() {
    const menu = document.getElementById("doerDropdownMenu");
    if (!menu) return;
    const searchInput = document.getElementById("doerSearchInput");
    const query = searchInput ? searchInput.value.trim() : "";
    
    // If a doer is currently selected and input displays "Name - Code (Dept)", show all doers on click/focus
    if (selectedDoer && searchInput && searchInput.value.includes(selectedDoer.EmployeeCode)) {
        currentFilteredDoers = [...eligibleDoers];
        renderDoerOptions(currentFilteredDoers, "");
    } else if (query) {
        onDoerSearchInput(query);
    } else {
        currentFilteredDoers = [...eligibleDoers];
        renderDoerOptions(currentFilteredDoers, "");
    }

    menu.style.display = "block";
    currentFocusedIndex = -1;
}

function closeDoerDropdown() {
    const menu = document.getElementById("doerDropdownMenu");
    if (menu) menu.style.display = "none";
    currentFocusedIndex = -1;
}

function toggleDoerDropdown() {
    const menu = document.getElementById("doerDropdownMenu");
    if (!menu) return;
    if (menu.style.display === "block") {
        closeDoerDropdown();
    } else {
        const searchInput = document.getElementById("doerSearchInput");
        if (searchInput) searchInput.focus();
        openDoerDropdown();
    }
}

function onDoerSearchInput(val) {
    const q = (val || "").trim().toLowerCase();
    if (!q) {
        currentFilteredDoers = [...eligibleDoers];
    } else {
        currentFilteredDoers = eligibleDoers.filter(d => {
            const name = (d.EmployeeName || "").toLowerCase();
            const code = (d.EmployeeCode || "").toLowerCase();
            const dept = (d.Department || "").toLowerCase();
            return name.includes(q) || code.includes(q) || dept.includes(q);
        });
    }
    renderDoerOptions(currentFilteredDoers, q);
    const menu = document.getElementById("doerDropdownMenu");
    if (menu) menu.style.display = "block";
    currentFocusedIndex = -1;
}

function chooseDoer(empCode) {
    const d = eligibleDoers.find(item => item.EmployeeCode === empCode);
    if (!d) return;

    const searchInput = document.getElementById("doerSearchInput");
    if (searchInput) {
        searchInput.value = `${d.EmployeeName} - ${d.EmployeeCode} (${d.Department || "General"})`;
    }
    const clearBtn = document.getElementById("doerClearBtn");
    if (clearBtn) clearBtn.style.display = "inline-block";

    const selectEl = document.getElementById("doerSelect");
    if (selectEl) selectEl.value = empCode;

    closeDoerDropdown();
    onDoerSelected(empCode);
}

function clearDoerSelection() {
    const searchInput = document.getElementById("doerSearchInput");
    if (searchInput) {
        searchInput.value = "";
        searchInput.focus();
    }
    const clearBtn = document.getElementById("doerClearBtn");
    if (clearBtn) clearBtn.style.display = "none";

    const selectEl = document.getElementById("doerSelect");
    if (selectEl) selectEl.value = "";

    currentFilteredDoers = [...eligibleDoers];
    renderDoerOptions(currentFilteredDoers, "");
    closeDoerDropdown();
    onDoerSelected("");
}

function onDoerSearchKeydown(e) {
    const menu = document.getElementById("doerDropdownMenu");
    const isMenuOpen = menu && menu.style.display === "block";

    if (e.key === "ArrowDown") {
        e.preventDefault();
        if (!isMenuOpen) {
            openDoerDropdown();
            return;
        }
        const items = document.querySelectorAll(".doer-option-item");
        if (items.length === 0) return;
        currentFocusedIndex = (currentFocusedIndex + 1) % items.length;
        updateKeyboardFocus(items);
    } else if (e.key === "ArrowUp") {
        e.preventDefault();
        if (!isMenuOpen) {
            openDoerDropdown();
            return;
        }
        const items = document.querySelectorAll(".doer-option-item");
        if (items.length === 0) return;
        currentFocusedIndex = (currentFocusedIndex - 1 + items.length) % items.length;
        updateKeyboardFocus(items);
    } else if (e.key === "Enter") {
        if (isMenuOpen && currentFocusedIndex >= 0 && currentFilteredDoers[currentFocusedIndex]) {
            e.preventDefault();
            chooseDoer(currentFilteredDoers[currentFocusedIndex].EmployeeCode);
        }
    } else if (e.key === "Escape") {
        closeDoerDropdown();
    }
}

function updateKeyboardFocus(items) {
    items.forEach((el, idx) => {
        if (idx === currentFocusedIndex) {
            el.classList.add("keyboard-focus");
            el.scrollIntoView({ block: "nearest" });
        } else {
            el.classList.remove("keyboard-focus");
        }
    });
}

function highlightMatch(text, query) {
    if (!text) return "";
    if (!query || query.trim() === "") return escapeHtml(text);
    const escapedQ = query.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
    const regex = new RegExp(`(${escapedQ})`, "gi");
    return escapeHtml(text).replace(regex, '<span class="doer-match-hl">$1</span>');
}

function escapeHtml(str) {
    if (!str) return "";
    return str.toString()
        .replace(/&/g, "&amp;")
        .replace(/</g, "&lt;")
        .replace(/>/g, "&gt;")
        .replace(/"/g, "&quot;")
        .replace(/'/g, "&#039;");
}

function reloadDoersList() {
    clearDoerSelection();
    document.getElementById("doerMetaCardContainer").style.display = "none";
    document.getElementById("mainTabsContainer").style.display = "none";
    loadEligibleDoers();
}

// ── DOER SELECTION (SECTION 5.1) ─────────────────────────────────────────────

async function onDoerSelected(empCode) {
    if (!empCode) {
        selectedDoer = null;
        document.getElementById("doerMetaCardContainer").style.display = "none";
        document.getElementById("mainTabsContainer").style.display = "none";
        return;
    }

    selectedDoer = eligibleDoers.find(d => d.EmployeeCode === empCode);
    if (!selectedDoer) return;

    // Sync Search Input, Clear button & native select
    const searchInput = document.getElementById("doerSearchInput");
    if (searchInput) {
        searchInput.value = `${selectedDoer.EmployeeName} - ${selectedDoer.EmployeeCode} (${selectedDoer.Department || "General"})`;
    }
    const clearBtn = document.getElementById("doerClearBtn");
    if (clearBtn) clearBtn.style.display = "inline-block";

    const selectEl = document.getElementById("doerSelect");
    if (selectEl && selectEl.value !== empCode) {
        selectEl.value = empCode;
    }

    // Display Meta Card
    document.getElementById("metaEmpCode").textContent = selectedDoer.EmployeeCode;
    document.getElementById("metaEmpName").textContent = selectedDoer.EmployeeName;
    document.getElementById("metaDepartment").textContent = selectedDoer.Department || "General";
    document.getElementById("metaStartDate").textContent = selectedDoer.StartDate || "Not recorded";
    document.getElementById("metaTermDate").textContent = selectedDoer.TermDate || "Active (No term)";

    // Set constraints on Effective From input based on StartDate and TermDate (Rule WR9)
    const effInput = document.getElementById("effectiveFromInput");
    const today = getTodayIso();
    let minDate = today;
    if (selectedDoer.StartDate && selectedDoer.StartDate > today) {
        minDate = selectedDoer.StartDate;
    }
    effInput.min = minDate;
    if (selectedDoer.TermDate) {
        effInput.max = selectedDoer.TermDate;
    } else {
        effInput.removeAttribute("max");
    }

    document.getElementById("doerMetaCardContainer").style.display = "block";
    document.getElementById("mainTabsContainer").style.display = "block";

    // Load doer weightage details
    await loadCurrentWeightage(empCode);
}

// ── CURRENT WEIGHTAGE (SECTION 5.2) ──────────────────────────────────────────

async function loadCurrentWeightage(empCode) {
    const db = getActiveDatabase();
    const tbody = document.getElementById("currentWeightageBody");
    const tfoot = document.getElementById("currentWeightageFooter");
    const alertNoWt = document.getElementById("noWeightageAlert");
    const fmsBadgeBox = document.getElementById("fmsStatusBadgeContainer");

    tbody.innerHTML = '<tr><td colspan="5" class="text-center text-muted py-3"><div class="spinner-border spinner-border-sm text-primary me-2"></div>Loading weightages...</td></tr>';

    try {
        const resp = await fetch(`/api/weightage/current/${encodeURIComponent(empCode)}?database=${encodeURIComponent(db)}`);
        const json = await resp.json();

        if (json.status !== "success") {
            tbody.innerHTML = `<tr><td colspan="5" class="text-center text-danger py-3">Error loading weightage: ${json.message}</td></tr>`;
            return;
        }

        const wtData = json.data;
        const fmsStatus = json.fms_config_status;

        isDoerOnFmsConfig = fmsStatus.is_on_fms_config;
        fmsStagesDetails = fmsStatus.stages || [];
        currentWeightageRows = wtData.rows || [];

        // Render FMS Status Badge on the meta card
        if (isDoerOnFmsConfig) {
            fmsBadgeBox.innerHTML = `
                <div class="text-muted small text-uppercase" style="font-size: 0.72rem;">FMS_Config</div>
                <span class="badge bg-warning text-dark"><i class="bi bi-diagram-3-fill me-1"></i> Active in ${fmsStagesDetails.length} Stage(s)</span>
            `;
        } else {
            fmsBadgeBox.innerHTML = `
                <div class="text-muted small text-uppercase" style="font-size: 0.72rem;">FMS_Config</div>
                <span class="badge bg-secondary"><i class="bi bi-dash-circle me-1"></i> Not in FMS_Config</span>
            `;
        }

        // Configure Mark Inactive button (Section 5.6)
        const btnMarkInact = document.getElementById("btnMarkInactive");
        if (btnMarkInact) {
            const isApprover = window.CURRENT_USER ? !!window.CURRENT_USER.is_approver : true;
            if (!isApprover) {
                btnMarkInact.disabled = true;
                btnMarkInact.title = "Approver role required to mark a doer inactive";
                btnMarkInact.classList.add("opacity-50");
            } else if (isDoerOnFmsConfig) {
                btnMarkInact.disabled = true;
                btnMarkInact.title = "Remove this doer from FMS_Config first (Rule WR15)";
                btnMarkInact.classList.add("opacity-50");
            } else if (!wtData.is_measured) {
                btnMarkInact.disabled = true;
                btnMarkInact.title = "No active weightage to mark inactive";
            } else {
                btnMarkInact.disabled = false;
                btnMarkInact.title = "Close the doer's weightage version";
                btnMarkInact.classList.remove("opacity-50");
            }
        }

        // Display current weightage rows
        if (!wtData.is_measured) {
            alertNoWt.style.display = "flex";
            tfoot.style.display = "none";
            tbody.innerHTML = `
                <tr>
                    <td colspan="5" class="text-center text-muted py-4 fst-italic">
                        No weightage set &mdash; this doer is not measured
                    </td>
                </tr>
            `;
            // Default 1 empty row in new set
            initNewSetForm([]);
        } else {
            alertNoWt.style.display = "none";
            tfoot.style.display = "table-footer-group";
            document.getElementById("currentTotalCell").textContent = (wtData.current_total || 0).toFixed(2);

            let html = "";
            currentWeightageRows.forEach(row => {
                const statusChip = row.IsFutureWaiting
                    ? '<span class="status-chip status-chip-waiting"><i class="bi bi-hourglass-split me-1"></i>Waiting to start</span>'
                    : '<span class="status-chip status-chip-active"><i class="bi bi-check2 me-1"></i>Active</span>';

                html += `
                    <tr>
                        <td class="fw-bold font-monospace">${escapeHtml(row.KPICode)}</td>
                        <td>${escapeHtml(row.KPIName)}</td>
                        <td class="text-end fw-bold">${row.Weightage.toFixed(2)}</td>
                        <td>${escapeHtml(row.EffectiveFromDate || "-")}</td>
                        <td>${statusChip}</td>
                    </tr>
                `;
            });
            tbody.innerHTML = html;

            // Pre-fill rows from current version (Section 5.3: "Pre-fill the rows from the current version")
            const rowsToPrefill = (wtData.current_rows && wtData.current_rows.length > 0)
                ? wtData.current_rows
                : currentWeightageRows;
            initNewSetForm(rowsToPrefill);
        }

    } catch (err) {
        console.error("Error loading current weightage:", err);
        tbody.innerHTML = `<tr><td colspan="5" class="text-center text-danger py-3">Network error loading weightage.</td></tr>`;
    }
}

// ── ENTER NEW SET (SECTION 5.3) ──────────────────────────────────────────────

function initNewSetForm(prefillRows = []) {
    newWeightageRows = [];
    const container = document.getElementById("newKpiRowsContainer");
    container.innerHTML = "";

    if (prefillRows && prefillRows.length > 0) {
        prefillRows.forEach(r => {
            newWeightageRows.push({
                kpi: r.KPICode,
                weight: parseFloat(r.Weightage) || 0.0,
            });
        });
    } else {
        // If empty, add default first row (e.g. KPI01)
        const firstKpi = activeKpiMaster.length > 0 ? activeKpiMaster[0].KPICode : "";
        newWeightageRows.push({
            kpi: firstKpi,
            weight: 1.00,
        });
    }

    renderNewKpiRows();
    runOnScreenChecks();
}

function addNewKpiRow() {
    // Find unallocated KPI
    const allocatedKpis = new Set(newWeightageRows.map(r => r.kpi));
    const available = activeKpiMaster.find(k => !allocatedKpis.has(k.KPICode));

    newWeightageRows.push({
        kpi: available ? available.KPICode : "",
        weight: 0.15,
    });

    renderNewKpiRows();
    runOnScreenChecks();
}

function removeKpiRow(index) {
    if (newWeightageRows.length <= 1) {
        // Clear value rather than leave zero rows, or allow empty to show Section 5.4 "Add at least one KPI" check
        newWeightageRows.splice(index, 1);
    } else {
        newWeightageRows.splice(index, 1);
    }
    renderNewKpiRows();
    runOnScreenChecks();
}

function onKpiChanged(index, newKpiCode) {
    newWeightageRows[index].kpi = newKpiCode;
    renderNewKpiRows();
    runOnScreenChecks();
}

function onWeightChanged(index, newWeightVal) {
    const val = parseFloat(newWeightVal);
    newWeightageRows[index].weight = isNaN(val) ? 0.0 : val;
    runOnScreenChecks();
}

function renderNewKpiRows() {
    const container = document.getElementById("newKpiRowsContainer");
    if (!container) return;

    if (newWeightageRows.length === 0) {
        container.innerHTML = `
            <div class="alert alert-secondary py-3 text-center small text-muted">
                No KPIs allocated yet. Click "Add KPI" above to begin.
            </div>
        `;
        return;
    }

    let html = "";
    newWeightageRows.forEach((row, idx) => {
        // Filter options for this row: list all active KPIs, omitting those chosen in other rows
        const chosenInOthers = new Set(
            newWeightageRows.filter((_, i) => i !== idx).map(r => r.kpi).filter(Boolean)
        );

        let optionsHtml = '<option value="">-- Select KPI --</option>';
        activeKpiMaster.forEach(k => {
            const isSelected = k.KPICode === row.kpi;
            const isOmitted = chosenInOthers.has(k.KPICode) && !isSelected;
            if (!isOmitted) {
                optionsHtml += `<option value="${k.KPICode}" ${isSelected ? "selected" : ""}>${k.KPICode} - ${escapeHtml(k.KPIName)}</option>`;
            }
        });

        html += `
            <div class="kpi-row-item d-flex align-items-center gap-2">
                <div class="flex-grow-1">
                    <select class="form-select form-select-sm" onchange="onKpiChanged(${idx}, this.value)">
                        ${optionsHtml}
                    </select>
                </div>
                <div style="width: 140px;">
                    <div class="input-group input-group-sm">
                        <span class="input-group-text bg-light text-muted">W</span>
                        <input type="number" class="form-control text-end fw-bold" step="0.01" min="0.01" max="1.00"
                            value="${row.weight !== undefined ? row.weight.toFixed(2) : '0.00'}"
                            oninput="onWeightChanged(${idx}, this.value)">
                    </div>
                </div>
                <div>
                    <button class="btn btn-outline-danger btn-sm" onclick="removeKpiRow(${idx})" title="Remove KPI">
                        <i class="bi bi-trash3"></i>
                    </button>
                </div>
            </div>
        `;
    });

    container.innerHTML = html;
}

function onReasonInput() {
    const reasonInput = document.getElementById("changeReasonInput");
    const counter = document.getElementById("reasonCharCounter");
    if (reasonInput && counter) {
        counter.textContent = `${reasonInput.value.length} / 250`;
    }
    runOnScreenChecks();
}

// ── ON-SCREEN CHECKS & REAL-TIME VALIDATION (SECTION 5.4) ────────────────────

function runOnScreenChecks() {
    const checks = {
        atLeastOne: false,
        noDuplicate: true,
        weightRange: true,
        totalExact: false,
        effectiveDate: false,
        reasonEntered: false,
    };

    // 1. At least one KPI
    checks.atLeastOne = newWeightageRows.length >= 1 && newWeightageRows.some(r => r.kpi && r.kpi.trim());

    // 2. No KPI twice
    const seen = new Set();
    for (const r of newWeightageRows) {
        if (!r.kpi) continue;
        if (seen.has(r.kpi)) {
            checks.noDuplicate = false;
            break;
        }
        seen.add(r.kpi);
    }

    // 3. Weight above 0, at most 1, at most two decimals
    let runningTotal = 0.0;
    if (newWeightageRows.length === 0) {
        checks.weightRange = false;
    } else {
        for (const r of newWeightageRows) {
            const w = r.weight;
            if (isNaN(w) || w <= 0.0 || w > 1.0) {
                checks.weightRange = false;
            }
            // Check decimal places
            const strVal = w.toString();
            if (strVal.includes(".")) {
                const decs = strVal.split(".")[1];
                if (decs.length > 2) {
                    checks.weightRange = false;
                }
            }
            runningTotal += (isNaN(w) ? 0.0 : w);
        }
    }

    // Round running total to 2 decimals
    runningTotal = Math.round(runningTotal * 100) / 100;

    // 4. Total exactly 1.00
    checks.totalExact = Math.abs(runningTotal - 1.00) < 0.0001;

    // 5. Effective From in range (Rule WR9: today or later, within StartDate/TermDate)
    const effDateVal = document.getElementById("effectiveFromInput")?.value;
    const todayStr = getTodayIso();
    if (effDateVal && effDateVal >= todayStr) {
        let inEmployment = true;
        if (selectedDoer) {
            if (selectedDoer.StartDate && effDateVal < selectedDoer.StartDate) {
                inEmployment = false;
            }
            if (selectedDoer.TermDate && effDateVal > selectedDoer.TermDate) {
                inEmployment = false;
            }
        }
        checks.effectiveDate = inEmployment;
    }

    // 6. Reason entered
    const reasonVal = document.getElementById("changeReasonInput")?.value || "";
    checks.reasonEntered = reasonVal.trim().length > 0;

    // Update Running Total Box UI (Section 5.3)
    const totalBox = document.getElementById("totalIndicatorBox");
    const totalDisplay = document.getElementById("totalDisplay");
    const totalHelp = document.getElementById("totalHelpText");

    if (totalDisplay) totalDisplay.textContent = runningTotal.toFixed(2);

    if (checks.totalExact) {
        totalBox.className = "p-3 rounded mb-3 border transition-all valid-total";
        totalHelp.innerHTML = '<i class="bi bi-check-circle-fill me-1"></i> Weights add up to exactly 1.00.';
    } else {
        totalBox.className = "p-3 rounded mb-3 border transition-all invalid-total";
        totalHelp.innerHTML = `<i class="bi bi-exclamation-triangle-fill me-1"></i> Weights must add up to exactly 1.00. Current total: <strong>${runningTotal.toFixed(2)}</strong>`;
    }

    // Update Section 5.4 Checklist Display
    updateCheckItem("check-at-least-one", checks.atLeastOne, "At least one KPI selected.", "Add at least one KPI.");
    updateCheckItem("check-no-duplicate", checks.noDuplicate, "No KPI selected twice.", "This KPI is already in the set.");
    updateCheckItem("check-weight-range", checks.weightRange, "All weights between 0.01 and 1.00 (max 2 decimals).", "Enter a weight between 0.01 and 1.00.");
    updateCheckItem("check-total-exact", checks.totalExact, "Weights add up to exactly 1.00.", `Weights must add up to exactly 1.00. Current total: ${runningTotal.toFixed(2)}`);
    updateCheckItem("check-effective-date", checks.effectiveDate, "Effective From is today or later within employment.", "Choose a date from today, within the doer's employment.");
    updateCheckItem("check-reason-entered", checks.reasonEntered, "Reason entered.", "Enter the reason for this change.");

    // Submit button state: enabled ONLY when every check in Section 5.4 passes AND user is authorized approver
    const allPassed = Object.values(checks).every(Boolean);
    const isApprover = window.CURRENT_USER ? !!window.CURRENT_USER.is_approver : true;
    const btnSubmit = document.getElementById("btnSubmitNewSet");
    if (btnSubmit) {
        btnSubmit.disabled = !allPassed || !isApprover;
    }

    return allPassed;
}

function updateCheckItem(elementId, isPassed, successMsg, failMsg) {
    const el = document.getElementById(elementId);
    if (!el) return;

    if (isPassed) {
        el.className = "py-1 text-success";
        el.innerHTML = `<i class="bi bi-check-circle-fill me-1"></i> ${escapeHtml(successMsg)}`;
    } else {
        el.className = "py-1 text-danger";
        el.innerHTML = `<i class="bi bi-x-circle-fill me-1"></i> ${escapeHtml(failMsg)}`;
    }
}

// ── SUBMIT NEW SET (SECTION 5.5) ─────────────────────────────────────────────

async function submitNewWeightageSet() {
    if (!runOnScreenChecks() || !selectedDoer) return;

    const btnSubmit = document.getElementById("btnSubmitNewSet");
    const errorAlert = document.getElementById("procedureErrorAlert");
    const errorMsg = document.getElementById("procedureErrorMessage");

    errorAlert.style.display = "none";
    btnSubmit.disabled = true;
    btnSubmit.innerHTML = '<span class="spinner-border spinner-border-sm me-2"></span>Submitting through SP_KPI_Weightage_Set...';

    const payload = {
        DoerCode: selectedDoer.EmployeeCode,
        EffectiveFromDate: document.getElementById("effectiveFromInput").value,
        Weights: newWeightageRows.map(r => ({ KPI: r.kpi, W: r.weight })),
        ChangeReason: document.getElementById("changeReasonInput").value.trim(),
        Database: getActiveDatabase(),
    };

    try {
        const resp = await fetch("/api/weightage/set", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(payload),
        });

        const json = await resp.json();

        if (resp.ok && json.status === "success") {
            // Success: Section 5.5 "Refresh the grid in 5.2 from the database."
            alert(`Success: ${json.message}`);
            document.getElementById("changeReasonInput").value = "";
            document.getElementById("reasonCharCounter").textContent = "0 / 250";
            await loadCurrentWeightage(selectedDoer.EmployeeCode);
        } else {
            // Failure: Section 5.5 & 6.3 "Show the error message as it is — it states the problem."
            errorAlert.style.display = "block";
            errorMsg.textContent = json.message || "Execution failed.";
        }
    } catch (err) {
        console.error("Submission error:", err);
        errorAlert.style.display = "block";
        errorMsg.textContent = `Network failure: ${err.message}`;
    } finally {
        btnSubmit.disabled = false;
        btnSubmit.innerHTML = '<i class="bi bi-check2-square me-1"></i> Submit New Version (SP_KPI_Weightage_Set)';
        runOnScreenChecks();
    }
}

// ── MARK INACTIVE (SECTION 5.6) ──────────────────────────────────────────────

function openMarkInactiveModal() {
    if (!selectedDoer) return;
    const isApprover = window.CURRENT_USER ? !!window.CURRENT_USER.is_approver : true;
    if (!isApprover) {
        alert("Approver role required to mark a doer inactive.");
        return;
    }

    const blockedAlert = document.getElementById("inactiveBlockedAlert");
    const blockedDetails = document.getElementById("inactiveBlockedDetails");
    const formFields = document.getElementById("inactiveFormFields");
    const btnConfirm = document.getElementById("btnConfirmInactive");
    const errBox = document.getElementById("inactiveProcedureError");

    errBox.style.display = "none";

    // Section 5.6 & WR15: Disable with message "Remove this doer from FMS_Config first"
    if (isDoerOnFmsConfig) {
        blockedAlert.style.display = "block";
        blockedDetails.textContent = `Doer ${selectedDoer.EmployeeName} (${selectedDoer.EmployeeCode}) is assigned to active FMS_Config stages: ` +
            fmsStagesDetails.map(s => `${s.App_ID}:${s.Stage_No} (${s.Roles.join("/")})`).join(", ");
        formFields.style.opacity = "0.4";
        btnConfirm.disabled = true;
    } else {
        blockedAlert.style.display = "none";
        formFields.style.opacity = "1";
        document.getElementById("inactiveFromDateInput").value = getTodayIso();
        document.getElementById("inactiveReasonInput").value = "";
        validateInactiveForm();
    }

    const modal = new bootstrap.Modal(document.getElementById("markInactiveModal"));
    modal.show();
}

function validateInactiveForm() {
    const inactDate = document.getElementById("inactiveFromDateInput")?.value;
    const reason = document.getElementById("inactiveReasonInput")?.value?.trim() || "";
    const today = getTodayIso();

    const isValid = !isDoerOnFmsConfig && inactDate && inactDate >= today && reason.length > 0;
    const btnConfirm = document.getElementById("btnConfirmInactive");
    if (btnConfirm) btnConfirm.disabled = !isValid;
    return isValid;
}

async function submitMarkInactive() {
    if (!validateInactiveForm() || !selectedDoer) return;

    const btnConfirm = document.getElementById("btnConfirmInactive");
    const errBox = document.getElementById("inactiveProcedureError");
    errBox.style.display = "none";

    btnConfirm.disabled = true;
    btnConfirm.innerHTML = '<span class="spinner-border spinner-border-sm me-1"></span>Submitting SP_KPI_Weightage_Inactive...';

    const payload = {
        DoerCode: selectedDoer.EmployeeCode,
        InactiveFromDate: document.getElementById("inactiveFromDateInput").value,
        ChangeReason: document.getElementById("inactiveReasonInput").value.trim(),
        Database: getActiveDatabase(),
    };

    try {
        const resp = await fetch("/api/weightage/inactive", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(payload),
        });

        const json = await resp.json();

        if (resp.ok && json.status === "success") {
            const modalEl = document.getElementById("markInactiveModal");
            const modal = bootstrap.Modal.getInstance(modalEl);
            if (modal) modal.hide();

            alert(json.message);
            await loadCurrentWeightage(selectedDoer.EmployeeCode);
        } else {
            errBox.style.display = "block";
            errBox.textContent = json.message || "Failed to mark inactive.";
        }
    } catch (err) {
        console.error("Inactive error:", err);
        errBox.style.display = "block";
        errBox.textContent = `Network error: ${err.message}`;
    } finally {
        btnConfirm.disabled = false;
        btnConfirm.innerHTML = '<i class="bi bi-check-lg me-1"></i> Confirm Inactive';
        validateInactiveForm();
    }
}

// ── HISTORY TAB (SECTION 5.7) ────────────────────────────────────────────────

async function loadDoerHistory() {
    if (!selectedDoer) return;

    const db = getActiveDatabase();
    const tbody = document.getElementById("historyTableBody");
    tbody.innerHTML = '<tr><td colspan="11" class="text-center text-muted py-4"><div class="spinner-border spinner-border-sm text-primary me-2"></div>Loading history...</td></tr>';

    try {
        const resp = await fetch(`/api/weightage/history/${encodeURIComponent(selectedDoer.EmployeeCode)}?database=${encodeURIComponent(db)}`);
        const json = await resp.json();

        if (json.status !== "success") {
            tbody.innerHTML = `<tr><td colspan="11" class="text-center text-danger py-4">Error: ${json.message}</td></tr>`;
            return;
        }

        const rows = json.data || [];
        if (rows.length === 0) {
            tbody.innerHTML = '<tr><td colspan="11" class="text-center text-muted py-4">No history records found for this doer.</td></tr>';
            return;
        }

        let html = "";
        rows.forEach(r => {
            let statusBadge = "";
            if (r.IsVoided) {
                statusBadge = '<span class="status-chip status-chip-voided">Voided (Active = N)</span>';
            } else if (r.EffectiveToDate && r.EffectiveToDate < getTodayIso()) {
                statusBadge = '<span class="status-chip status-chip-ended">Ended</span>';
            } else {
                statusBadge = '<span class="status-chip status-chip-active">Active (Y)</span>';
            }

            html += `
                <tr class="${r.IsVoided ? 'table-danger opacity-75' : ''}">
                    <td class="font-monospace text-muted">${r.WeightageID || '-'}</td>
                    <td class="fw-bold font-monospace">${escapeHtml(r.KPICode)}</td>
                    <td>${escapeHtml(r.KPIName)}</td>
                    <td class="text-end fw-bold">${r.Weightage.toFixed(2)}</td>
                    <td>${escapeHtml(r.EffectiveFromDate || '-')}</td>
                    <td>${escapeHtml(r.EffectiveToDate || '<still in effect>')}</td>
                    <td class="text-center font-monospace">${r.Active}</td>
                    <td>${statusBadge}</td>
                    <td class="small">${escapeHtml(r.ChangeReason || '-')}</td>
                    <td class="small text-muted">${escapeHtml(r.InsertedBy || '-')}</td>
                    <td class="small text-muted">${escapeHtml(r.LastUpdatedBy || '-')}</td>
                </tr>
            `;
        });

        tbody.innerHTML = html;
    } catch (err) {
        console.error("Error loading history:", err);
        tbody.innerHTML = `<tr><td colspan="11" class="text-center text-danger py-4">Network error loading history.</td></tr>`;
    }
}

// ── FMS_CONFIG DOER INSPECTOR (SECTION 7.1) ──────────────────────────────────

async function loadFmsDoersInspector() {
    const db = getActiveDatabase();
    const container = document.getElementById("fmsDoersListContainer");
    container.innerHTML = '<div class="text-center text-muted py-3"><div class="spinner-border spinner-border-sm text-info me-2"></div>Running Section 7.1 query...</div>';

    try {
        const resp = await fetch(`/api/fms-config/doers?database=${encodeURIComponent(db)}`);
        const json = await resp.json();

        if (json.status !== "success") {
            container.innerHTML = `<div class="text-danger small py-2">Error: ${json.message}</div>`;
            return;
        }

        const doers = json.data || [];
        if (doers.length === 0) {
            container.innerHTML = '<div class="text-warning small py-2">No doers currently have an active weightage today.</div>';
            return;
        }

        let html = `<div class="fw-bold small text-muted mb-2"><i class="bi bi-sort-alpha-down text-primary me-1"></i>${doers.length} Measured Doers with Live Weightage Today (A to Z):</div><div class="list-group list-group-flush small">`;
        doers.forEach(d => {
            html += `
                <div class="list-group-item d-flex justify-content-between align-items-center py-2 px-1">
                    <div>
                        <span class="fw-semibold text-dark me-2">${escapeHtml(d.EmployeeName)}</span>
                        <span class="badge bg-light text-secondary border font-monospace">${d.EmployeeCode}</span>
                    </div>
                    <span class="badge bg-success-subtle text-success border border-success"><i class="bi bi-check-circle me-1"></i>Measured</span>
                </div>
            `;
        });
        html += "</div>";
        container.innerHTML = html;
    } catch (err) {
        console.error("Error loading FMS doers:", err);
        container.innerHTML = `<div class="text-danger small py-2">Network error.</div>`;
    }
}

// Utility: Escape HTML
function escapeHtml(text) {
    if (text === null || text === undefined) return "";
    return String(text)
        .replace(/&/g, "&amp;")
        .replace(/</g, "&lt;")
        .replace(/>/g, "&gt;")
        .replace(/"/g, "&quot;")
        .replace(/'/g, "&#039;");
}

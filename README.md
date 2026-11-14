# KPI Weightage Management Application & FMS_Config Guard

Implementation of **SDC_FMS_KPIWeightage_SystemDesign v1.0** (11 November 2026).

---

## 1. Overview & Architecture

Every doer in FMS is measured on one or more KPIs (today: `KPI01` Delay Rate and `KPI02` Task Completion Rate). A doer's day score is the weighted sum of their KPI scores. A doer with no weightage is **not measured**: their tasks are timed in the queue, but none of it reaches their KPI score.

This application provides:
1. **The KPI Weightage Screen**: Searchable doer selector, read-only current/waiting version display, complete new version submission with real-time on-screen validation, Mark Inactive with FMS_Config active guard, and version history.
2. **One Write Path**: Strictly adheres to the rule that the application never runs ad-hoc SQL edits against `Z_KPI_Weightage` or `Z_KPI_Master`. All changes go through `dbo.SP_KPI_Weightage_Set` and `dbo.SP_KPI_Weightage_Inactive`.
3. **FMS_Config Guard & Doer Dropdowns**: Implements the Section 7.1 filter ensuring `FMS_Config` and the Doer Reallocation App only present doers with an active weightage today.

### Technology Stack
- **Backend**: Python 3.11+, FastAPI, HTTPX, Pydantic v2
- **Frontend**: HTML5, CSS3, JavaScript, Bootstrap 5.3, Bootstrap Icons
- **Database Targets**: `Test_OperationsDB` (Development / Test) and `OperationsDB` (Production) via Company API Gateway (`apiv2.php` / `apiv3.php`)

---

## 2. Answers to Section 7.2 Requirements

> **Question:** Which procedures edit existing FMS_Config rows, and which write the temp doer in the reallocation app? The same "weightage required" guard is to be added to them.

### A. Objects Editing Existing FMS_Config Rows
1. **`sp_Add_FMS_Config`**: Guarded with Error **53041** (`A Doer, Backup Doer or Temp Doer has no weightage in effect today`).
2. **`One_Portal` Masters Update Route (`PUT /api/masters/FMS_Config/{record_id}`)**:
   - Location: `One_Portal/ONEPORTAL/app/routers/masters.py`
   - Fields written: `Doer_EC`, `Doer_Name`, `BackupDoer_EC`, `Backup_Doer`, `TempDoer_EC`, `Temp_Doer`, `AllocatedDoer_EC`.
   - **Required Guard**: Before updating any of `Doer_EC`, `BackupDoer_EC`, or `TempDoer_EC` on an active `FMS_Config` row, execute the Section 7.1 check:
     ```sql
     IF NOT EXISTS (
         SELECT 1 FROM dbo.Z_KPI_Weightage wt
         WHERE wt.DoerCode = @EmployeeCode AND wt.Active = 'Y'
           AND wt.EffectiveFromDate <= CAST(GETDATE() AS DATE)
           AND (wt.EffectiveToDate IS NULL OR wt.EffectiveToDate >= CAST(GETDATE() AS DATE))
     )
     THROW 53041, 'A Doer, Backup Doer or Temp Doer has no weightage in effect today.', 1;
     ```

### B. Objects Writing Temp Doer in the Doer Reallocation App
1. **`Doer_Reallocation_System` (`APP000073`)**:
   - Render web application (`https://doer-reallocation-system.onrender.com/`)
   - Writes `TempDoer_EC`, `Temp_Doer`, `I_FromDateTime`, and `I_ToDateTime` into `FMS_Config`.
2. **`Doer Re-Allocation Control Panel` (`APP000008`)**:
   - Google Apps Script interface (`AKfycby893LnVhO1QN0d...`)
   - Writes temp doer allocations during employee leave or reassignment.
3. **Database Stored Procedures**:
   - `SP_FMS_Reallocate_Doer` / `SP_FMS_TempDoer_Set`: Any custom procedure invoked by the reallocation apps to assign temp doers must incorporate Error 53041.

---

## 3. Section 7.1 Doer Dropdown Query

Both the `FMS_Config` screen and the Doer Reallocation App must use this query for their `Doer`, `Backup Doer`, and `Temp Doer` dropdowns:

```sql
SELECT DISTINCT e.EmployeeCode, e.EmployeeName
FROM dbo.VM_EmployeeMaster e
WHERE EXISTS (
    SELECT 1 FROM dbo.Z_KPI_Weightage wt
    WHERE wt.DoerCode = e.EmployeeCode AND wt.Active = 'Y'
      AND wt.EffectiveFromDate <= CAST(GETDATE() AS DATE)
      AND (wt.EffectiveToDate IS NULL OR wt.EffectiveToDate >= CAST(GETDATE() AS DATE))
);
```

---

## 4. Summary of Business Rules (WR1 &ndash; WR16)

| Rule ID | Description | Enforced By |
|---|---|---|
| **WR1** | Doer is selected first. | UI &amp; API |
| **WR2** | Doer list: Is Employed = 'Y', TermDate empty or &ge; today, DeptCode &ne; 20 (Management). | UI &amp; Service |
| **WR3** | Current version and waiting versions shown read-only. | UI &amp; Table |
| **WR4** | Posted row is never edited or deleted. Every change is a new version. | Architecture |
| **WR5** | Complete new set: only allocated KPIs, each once. | UI &amp; SP |
| **WR6** | KPIs chosen from `Z_KPI_Master` dropdown. No typing. | UI |
| **WR7** | Each weight &gt; 0 and &le; 1, at most 2 decimals. Unused KPI left out. | UI &amp; SP |
| **WR8** | Weights add up to exactly 1.00. | UI &amp; SP |
| **WR9** | Effective From is today or later, not before StartDate, not after TermDate. | UI &amp; SP |
| **WR10** | EffectiveToDate never entered; filled automatically as new start date minus 1 day. | SP |
| **WR11** | Unstarted future version on or after new start date is voided (`Active = 'N'`). | SP |
| **WR12** | Closing old version and inserting new version happen in a single transaction. | SP |
| **WR13** | Concurrency control (two users cannot corrupt the same doer). | SP |
| **WR14** | Change reason is mandatory (max 250 chars). User code taken from session. | UI &amp; SP |
| **WR15** | Mark Inactive refused while doer is on active `FMS_Config` (Error 53037). | UI &amp; SP |
| **WR16** | Role-based access: only approving roles (Role 1, 2) can open screen or submit. | App &amp; API |

---

## 5. Procedure Contracts & Error Codes

### `SP_KPI_Weightage_Set`
- `@DoerCode NVARCHAR(20)`
- `@EffectiveFromDate DATE`
- `@Weights NVARCHAR(MAX)` (JSON array `[{"KPI":"KPI01","W":0.70},{"KPI":"KPI02","W":0.30}]`)
- `@ChangeReason NVARCHAR(250)`
- `@UserCode NVARCHAR(50)`

### `SP_KPI_Weightage_Inactive`
- `@DoerCode NVARCHAR(20)`
- `@InactiveFromDate DATE`
- `@ChangeReason NVARCHAR(250)`
- `@UserCode NVARCHAR(50)`

### Error Codes Reference (Section 6.3)
- `53001-53004`: Required value missing (doer, date, reason, user)
- `53005`: Doer not found, not employed, already left, or in Management
- `53006-53008`: Effective From before today, before StartDate, or after TermDate
- `53009-53011`: Weights not valid JSON, empty, or row without KPI/weight
- `53012`: KPI appears twice
- `53013`: Unknown or inactive KPI
- `53014-53015`: Weight &le; 0, &gt; 1, or more than two decimal places
- `53016`: Weights do not add up to exactly 1.00
- `53031-53035`: Inactive required value missing, or date before today
- `53036`: No weightage in effect from that date
- `53037`: Doer still on active FMS_Config row
- `53041`: Doer has no weightage in effect today (on `sp_Add_FMS_Config`)

---

## 6. How to Run Locally

```bash
# 1. Navigate to application folder
cd C:\Users\Himanshu\.gemini\antigravity\scratch\KPI_Weightage

# 2. Run with Python
uv run uvicorn app.main:app --port 8000 --reload
```

Open browser at `http://127.0.0.1:8000`.

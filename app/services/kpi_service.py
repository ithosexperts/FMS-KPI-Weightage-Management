"""
KPI Weightage Business Logic and Database Service.
Implements all rules and queries specified in SDC_FMS_KPIWeightage_SystemDesign v1.0:
- WR1 to WR16
- Section 5.1 - 5.7
- Section 6.1 - 6.3
- Section 7.1 - 7.2
"""
import json
import logging
from datetime import date, datetime, timedelta
from decimal import Decimal, ROUND_HALF_UP
from typing import Any, Dict, List, Optional, Tuple

from app.api.client import query_gateway, ApiError
from app.config import settings

logger = logging.getLogger(__name__)


def parse_date(val: Any) -> Optional[date]:
    """Parse dates from various gateway formats (YYYY-MM-DD, YYYY-MM-DD HH:MM:SS, etc.)."""
    if val is None:
        return None
    val_str = str(val).strip()
    if not val_str or val_str.lower() in ("null", "none"):
        return None
    for fmt in ("%Y-%m-%d", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M:%S.%f", "%d-%m-%Y", "%d/%m/%Y"):
        try:
            return datetime.strptime(val_str[:19], fmt[:len(val_str[:19])]).date()
        except Exception:
            continue
    try:
        return datetime.fromisoformat(val_str).date()
    except Exception:
        return None


def format_date_iso(d: Optional[date]) -> Optional[str]:
    return d.isoformat() if d else None


def get_case_insensitive(d: Dict[str, Any], key: str, default: Any = None) -> Any:
    """Helper to safely fetch dict value regardless of casing (e.g. Active vs active)."""
    if not isinstance(d, dict):
        return default
    target = key.lower()
    for k, v in d.items():
        if k.lower() == target:
            return v
    return default


class KpiService:
    """Service implementing the KPI Weightage system design."""

    @staticmethod
    async def get_eligible_doers(database: Optional[str] = None) -> List[Dict[str, Any]]:
        """
        Section 5.1 & Rule WR2:
        SELECT DISTINCT EmployeeCode, EmployeeName
        FROM dbo.VM_EmployeeMaster
        WHERE Active = 'Y'
        AND (TermDate IS NULL OR TermDate >= CAST(GETDATE() AS DATE))
        AND ISNULL(DeptCode, 0) <> 20
        """
        target_db = database or settings.api_database
        res = await query_gateway(
            table="VM_EmployeeMaster",
            action="select",
            database=target_db,
            fetch_all=True,
        )
        rows = res.get("data", []) or []

        today = date.today()
        eligible_map: Dict[str, Dict[str, Any]] = {}

        for row in rows:
            active = str(get_case_insensitive(row, "Active", "")).strip().upper()
            if active != "Y":
                continue

            # TermDate check: TermDate IS NULL OR TermDate >= today
            term_date = parse_date(get_case_insensitive(row, "TermDate"))
            if term_date and term_date < today:
                continue

            # DeptCode check: ISNULL(DeptCode, 0) <> 20 (Management)
            dept_code_raw = get_case_insensitive(row, "DeptCode")
            try:
                dept_code = int(dept_code_raw) if dept_code_raw not in (None, "", "null") else 0
            except (ValueError, TypeError):
                dept_code = 0

            dept_name = str(get_case_insensitive(row, "Department", "")).strip().lower()
            if dept_code == 20 or dept_name == "management":
                continue

            emp_code = str(get_case_insensitive(row, "EmployeeCode", "")).strip()
            emp_name = str(get_case_insensitive(row, "EmployeeName", "")).strip()
            if not emp_code:
                continue

            # Keep distinct employee
            if emp_code not in eligible_map:
                start_date = parse_date(get_case_insensitive(row, "StartDate"))
                eligible_map[emp_code] = {
                    "EmployeeCode": emp_code,
                    "EmployeeName": emp_name,
                    "Department": get_case_insensitive(row, "Department"),
                    "Position": get_case_insensitive(row, "Position"),
                    "StartDate": format_date_iso(start_date),
                    "TermDate": format_date_iso(term_date),
                }

        # Sort alphabetically by EmployeeName
        sorted_doers = sorted(eligible_map.values(), key=lambda x: x["EmployeeName"].lower())
        return sorted_doers

    @staticmethod
    async def get_kpi_master(database: Optional[str] = None) -> List[Dict[str, Any]]:
        """
        Section 3.2:
        Active KPIs in the system (e.g. KPI01 Delay Rate, KPI02 Task Completion Rate).
        """
        target_db = database or settings.api_database
        res = await query_gateway(
            table="Z_KPI_Master",
            action="select",
            database=target_db,
            fetch_all=True,
        )
        rows = res.get("data", []) or []
        active_kpis = [
            {
                "KPICode": str(r.get("KPICode") or "").strip(),
                "KPIName": str(r.get("KPIName") or "").strip(),
                "Active": str(r.get("Active") or "").strip().upper(),
            }
            for r in rows
            if str(r.get("Active") or "").strip().upper() == "Y"
        ]
        return active_kpis

    @staticmethod
    async def get_current_weightage(doer_code: str, database: Optional[str] = None) -> Dict[str, Any]:
        """
        Section 5.2 & Rule WR3:
        SELECT * FROM dbo.Z_KPI_Weightage
        WHERE DoerCode = @DoerCode AND Active = 'Y'
        AND (EffectiveToDate IS NULL OR EffectiveToDate >= CAST(GETDATE() AS DATE))
        ORDER BY EffectiveFromDate, KPICode;
        """
        target_db = database or settings.api_database
        clean_code = str(doer_code).strip()
        res = await query_gateway(
            table="Z_KPI_Weightage",
            action="select",
            database=target_db,
            filters={"DoerCode": clean_code},
            fetch_all=True,
        )
        all_rows = res.get("data", []) or []
        today = date.today()

        valid_rows: List[Dict[str, Any]] = []
        for r in all_rows:
            # Active check
            if str(r.get("Active") or "").strip().upper() != "Y":
                continue

            # EffectiveToDate check
            eff_to = parse_date(r.get("EffectiveToDate"))
            if eff_to and eff_to < today:
                continue

            eff_from = parse_date(r.get("EffectiveFromDate"))
            weight = float(Decimal(str(r.get("Weightage") or 0)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))

            is_future = bool(eff_from and eff_from > today)

            valid_rows.append({
                "WeightageID": r.get("WeightageID"),
                "DoerCode": str(r.get("DoerCode") or clean_code).strip(),
                "DoerName": str(r.get("DoerName") or "").strip(),
                "KPICode": str(r.get("KPICode") or "").strip(),
                "KPIName": str(r.get("KPIName") or "").strip(),
                "Weightage": weight,
                "EffectiveFromDate": format_date_iso(eff_from),
                "EffectiveToDate": format_date_iso(eff_to),
                "Active": "Y",
                "ChangeReason": r.get("ChangeReason") or "",
                "InsertTS": str(r.get("InsertTS") or ""),
                "InsertedBy": r.get("InsertedBy") or "",
                "IsFutureWaiting": is_future,
                "VersionStatus": "Waiting to start" if is_future else "Current active version",
            })

        # Sort by EffectiveFromDate, KPICode
        valid_rows.sort(key=lambda x: (x["EffectiveFromDate"] or "", x["KPICode"]))

        is_measured = len(valid_rows) > 0

        # Separate currently active vs waiting to start
        current_rows = [r for r in valid_rows if not r["IsFutureWaiting"]]
        waiting_rows = [r for r in valid_rows if r["IsFutureWaiting"]]

        current_total = round(sum(r["Weightage"] for r in current_rows), 2)
        waiting_total = round(sum(r["Weightage"] for r in waiting_rows), 2)

        return {
            "doer_code": clean_code,
            "is_measured": is_measured,
            "message": None if is_measured else "No weightage set — this doer is not measured",
            "rows": valid_rows,
            "current_rows": current_rows,
            "waiting_rows": waiting_rows,
            "current_total": current_total,
            "waiting_total": waiting_total,
        }

    @staticmethod
    async def get_weightage_history(doer_code: str, database: Optional[str] = None) -> List[Dict[str, Any]]:
        """
        Section 5.7:
        SELECT * FROM dbo.Z_KPI_Weightage WHERE DoerCode = @DoerCode
        ORDER BY EffectiveFromDate DESC, KPICode;
        """
        target_db = database or settings.api_database
        clean_code = str(doer_code).strip()
        res = await query_gateway(
            table="Z_KPI_Weightage",
            action="select",
            database=target_db,
            filters={"DoerCode": clean_code},
            fetch_all=True,
        )
        all_rows = res.get("data", []) or []

        formatted: List[Dict[str, Any]] = []
        for r in all_rows:
            eff_from = parse_date(r.get("EffectiveFromDate"))
            eff_to = parse_date(r.get("EffectiveToDate"))
            weight = float(Decimal(str(r.get("Weightage") or 0)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))
            active_val = str(r.get("Active") or "").strip().upper()

            is_voided = active_val == "N"
            status_text = "Voided" if is_voided else ("Active (Ended)" if eff_to and eff_to < date.today() else "Active")

            formatted.append({
                "WeightageID": r.get("WeightageID"),
                "DoerCode": str(r.get("DoerCode") or clean_code).strip(),
                "DoerName": str(r.get("DoerName") or "").strip(),
                "KPICode": str(r.get("KPICode") or "").strip(),
                "KPIName": str(r.get("KPIName") or "").strip(),
                "Weightage": weight,
                "EffectiveFromDate": format_date_iso(eff_from),
                "EffectiveToDate": format_date_iso(eff_to),
                "Active": active_val,
                "IsVoided": is_voided,
                "StatusText": status_text,
                "ChangeReason": r.get("ChangeReason") or "",
                "InsertTS": str(r.get("InsertTS") or ""),
                "InsertedBy": r.get("InsertedBy") or "",
                "LastSyncTS": str(r.get("LastSyncTS") or ""),
                "LastUpdatedBy": r.get("LastUpdatedBy") or "",
            })

        # ORDER BY EffectiveFromDate DESC, KPICode
        formatted.sort(key=lambda x: (x["EffectiveFromDate"] or "", x["KPICode"]), reverse=True)
        return formatted

    @staticmethod
    async def check_doer_active_in_fms_config(doer_code: str, database: Optional[str] = None) -> Tuple[bool, List[Dict[str, Any]]]:
        """
        Section 5.6 & Rule WR15:
        Refuse Mark Inactive while the doer is on any active FMS_Config row as
        Doer, Backup Doer or Temp Doer.
        """
        target_db = database or settings.api_database
        clean_code = str(doer_code).strip().lower()

        res = await query_gateway(
            table="FMS_Config",
            action="select",
            database=target_db,
            fetch_all=True,
        )
        all_rows = res.get("data", []) or []

        matched_stages = []
        for r in all_rows:
            # Active flag on FMS_Config is 1, '1', or 'Y'
            active_val = str(get_case_insensitive(r, "active", "")).strip().lower()
            if active_val not in ("1", "y", "true"):
                continue

            doer_ec = str(get_case_insensitive(r, "Doer_EC", "") or "").strip().lower()
            backup_ec = str(get_case_insensitive(r, "BackupDoer_EC", "") or "").strip().lower()
            temp_ec = str(get_case_insensitive(r, "TempDoer_EC", "") or "").strip().lower()

            match_role = []
            if doer_ec == clean_code:
                match_role.append("Doer")
            if backup_ec == clean_code:
                match_role.append("Backup Doer")
            if temp_ec == clean_code:
                match_role.append("Temp Doer")

            if match_role:
                matched_stages.append({
                    "Config_ID": get_case_insensitive(r, "config_id") or get_case_insensitive(r, "Config_ID"),
                    "App_ID": get_case_insensitive(r, "app_id") or get_case_insensitive(r, "App_ID"),
                    "FMS_Name": get_case_insensitive(r, "fms_name") or get_case_insensitive(r, "FMS_Name"),
                    "Stage_No": get_case_insensitive(r, "stage_no") or get_case_insensitive(r, "Stage_No"),
                    "Stage_Name": get_case_insensitive(r, "stage_name") or get_case_insensitive(r, "Stage_Name"),
                    "Roles": match_role,
                })

        return len(matched_stages) > 0, matched_stages

    @staticmethod
    async def get_measured_doers_for_fms_config(database: Optional[str] = None) -> List[Dict[str, Any]]:
        """
        Section 7.1:
        The Doer, Backup Doer and Temp Doer dropdowns — on the FMS_Config screen
        and on the doer reallocation app — list only employees with a weightage in effect today:

        SELECT DISTINCT e.EmployeeCode, e.EmployeeName
        FROM dbo.VM_EmployeeMaster e
        WHERE EXISTS (SELECT 1 FROM dbo.Z_KPI_Weightage wt
        WHERE wt.DoerCode = e.EmployeeCode AND wt.Active = 'Y'
        AND wt.EffectiveFromDate <= CAST(GETDATE() AS DATE)
        AND (wt.EffectiveToDate IS NULL
        OR wt.EffectiveToDate >= CAST(GETDATE() AS DATE)));
        """
        target_db = database or settings.api_database
        today = date.today()

        # Fetch all live weightage rows
        res_wt = await query_gateway(
            table="Z_KPI_Weightage",
            action="select",
            database=target_db,
            fetch_all=True,
        )
        wt_rows = res_wt.get("data", []) or []

        measured_codes = set()
        for r in wt_rows:
            if str(r.get("Active") or "").strip().upper() != "Y":
                continue
            eff_from = parse_date(r.get("EffectiveFromDate"))
            eff_to = parse_date(r.get("EffectiveToDate"))
            if eff_from and eff_from <= today:
                if eff_to is None or eff_to >= today:
                    code = str(r.get("DoerCode") or "").strip()
                    if code:
                        measured_codes.add(code.lower())

        # Now fetch employees
        res_emp = await query_gateway(
            table="VM_EmployeeMaster",
            action="select",
            database=target_db,
            fetch_all=True,
        )
        emp_rows = res_emp.get("data", []) or []

        measured_doers: Dict[str, Dict[str, Any]] = {}
        for r in emp_rows:
            code = str(r.get("EmployeeCode") or "").strip()
            name = str(r.get("EmployeeName") or "").strip()
            if code and code.lower() in measured_codes:
                if code not in measured_doers:
                    measured_doers[code] = {
                        "EmployeeCode": code,
                        "EmployeeName": name,
                    }

        result = sorted(measured_doers.values(), key=lambda x: x["EmployeeName"].lower())
        return result

    @classmethod
    async def set_kpi_weightage(
        cls,
        doer_code: str,
        effective_from_str: str,
        weights: List[Dict[str, Any]],
        change_reason: str,
        user_code: str,
        database: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Section 5.5 & Section 6.1:
        EXEC dbo.SP_KPI_Weightage_Set
        @DoerCode = N'0017',
        @EffectiveFromDate = '2026-11-12',
        @Weights = N'[{"KPI":"KPI01","W":0.70},{"KPI":"KPI02","W":0.30}]',
        @ChangeReason = N'Completion now weighted higher',
        @UserCode = N'<logged-in user>';

        Validates all rules and raises procedure error messages (53001 - 53016).
        """
        target_db = database or settings.api_database
        today = date.today()

        # 53001–53004: Required values
        if not doer_code or not str(doer_code).strip():
            raise ApiError("SP_KPI_Weightage_Set: 53001 - DoerCode is required.")
        if not effective_from_str or not str(effective_from_str).strip():
            raise ApiError("SP_KPI_Weightage_Set: 53002 - EffectiveFromDate is required.")
        if not change_reason or not str(change_reason).strip():
            raise ApiError("SP_KPI_Weightage_Set: 53003 - ChangeReason is mandatory.")
        if not user_code or not str(user_code).strip():
            raise ApiError("SP_KPI_Weightage_Set: 53004 - UserCode is required.")

        clean_doer = str(doer_code).strip()
        clean_reason = str(change_reason).strip()[:250]
        clean_user = str(user_code).strip()

        eff_from = parse_date(effective_from_str)
        if not eff_from:
            raise ApiError("SP_KPI_Weightage_Set: 53006 - Invalid EffectiveFromDate format.")

        # Rule WR9 / 53006: Effective From is today or later
        if eff_from < today:
            raise ApiError("SP_KPI_Weightage_Set: 53006 - EffectiveFromDate cannot be in the past.")

        # Fetch Doer details from VM_EmployeeMaster
        res_emp = await query_gateway(
            table="VM_EmployeeMaster",
            action="select",
            database=target_db,
            filters={"EmployeeCode": clean_doer},
            fetch_all=True,
        )
        emp_rows = res_emp.get("data", []) or []
        if not emp_rows:
            raise ApiError(f"SP_KPI_Weightage_Set: 53005 - Doer '{clean_doer}' not found.")

        emp = emp_rows[0]
        doer_name = str(get_case_insensitive(emp, "EmployeeName", clean_doer)).strip()

        # 53005: Doer active, already left, or in Management
        emp_active = str(get_case_insensitive(emp, "Active", "")).strip().upper()
        if emp_active != "Y":
            raise ApiError(f"SP_KPI_Weightage_Set: 53005 - Doer '{clean_doer}' is not active.")

        term_date = parse_date(get_case_insensitive(emp, "TermDate"))
        if term_date and term_date < today:
            raise ApiError(f"SP_KPI_Weightage_Set: 53005 - Doer '{clean_doer}' has already left the company.")

        dept_code_raw = get_case_insensitive(emp, "DeptCode")
        dept_name = str(get_case_insensitive(emp, "Department", "")).strip().lower()
        if (dept_code_raw is not None and str(dept_code_raw).strip() == "20") or dept_name == "management":
            raise ApiError(f"SP_KPI_Weightage_Set: 53005 - Doer '{clean_doer}' is in Management.")

        # 53007–53008: StartDate and TermDate range checks
        start_date = parse_date(get_case_insensitive(emp, "StartDate"))
        if start_date and eff_from < start_date:
            raise ApiError(f"SP_KPI_Weightage_Set: 53007 - EffectiveFromDate ({eff_from}) cannot be before employee StartDate ({start_date}).")
        if term_date and eff_from > term_date:
            raise ApiError(f"SP_KPI_Weightage_Set: 53008 - EffectiveFromDate ({eff_from}) cannot be after employee TermDate ({term_date}).")

        # 53009–53011: Weights validation
        if not weights or not isinstance(weights, list) or len(weights) == 0:
            raise ApiError("SP_KPI_Weightage_Set: 53010 - At least one KPI weight must be provided.")

        # Fetch active KPIs from Z_KPI_Master
        active_kpis = await cls.get_kpi_master(database=target_db)
        active_kpi_map = {k["KPICode"].upper(): k["KPIName"] for k in active_kpis}

        seen_kpis = set()
        normalized_weights: List[Dict[str, Any]] = []
        total_weight = Decimal("0.00")

        for item in weights:
            kpi_code = str(item.get("KPI") or item.get("KPICode") or "").strip().upper()
            w_raw = item.get("W") if "W" in item else item.get("Weightage")

            if not kpi_code or w_raw is None:
                raise ApiError("SP_KPI_Weightage_Set: 53011 - Each row must contain both KPI and Weight.")

            # 53012: No duplicate KPI
            if kpi_code in seen_kpis:
                raise ApiError(f"SP_KPI_Weightage_Set: 53012 - KPI '{kpi_code}' appears more than once.")
            seen_kpis.add(kpi_code)

            # 53013: Unknown or inactive KPI
            if kpi_code not in active_kpi_map:
                raise ApiError(f"SP_KPI_Weightage_Set: 53013 - KPI '{kpi_code}' is unknown or inactive.")

            # Parse weight
            try:
                dec_w = Decimal(str(w_raw)).quantize(Decimal("0.0001"))
            except Exception:
                raise ApiError("SP_KPI_Weightage_Set: 53014 - Invalid weight value.")

            # 53014-53015: Above 0, at most 1, at most two decimals
            if dec_w <= Decimal("0.00") or dec_w > Decimal("1.00"):
                raise ApiError(f"SP_KPI_Weightage_Set: 53014 - Weight for '{kpi_code}' must be between 0.01 and 1.00.")

            # Check decimal places
            # Decimal string check
            s = f"{dec_w:.4f}".rstrip("0")
            dec_places = len(s.split(".")[1]) if "." in s else 0
            if dec_places > 2:
                raise ApiError(f"SP_KPI_Weightage_Set: 53015 - Weight for '{kpi_code}' has more than two decimal places.")

            two_dec_w = dec_w.quantize(Decimal("0.01"))
            total_weight += two_dec_w

            normalized_weights.append({
                "KPI": kpi_code,
                "KPIName": active_kpi_map[kpi_code],
                "W": float(two_dec_w),
            })

        # 53016: Total exactly 1.00
        if total_weight != Decimal("1.00"):
            raise ApiError(f"SP_KPI_Weightage_Set: 53016 - Weights must add up to exactly 1.00. Current total: {total_weight:.2f}")

        # Execute Transaction:
        # Rule WR11: Void any future set that hasn't started yet (EffectiveFromDate >= eff_from and Active = 'Y')
        # Rule WR10: Close current set (EffectiveToDate = eff_from - 1 day)
        # Rule WR12: Insert new rows with Active = 'Y', EffectiveFromDate = eff_from, EffectiveToDate = NULL
        res_current = await query_gateway(
            table="Z_KPI_Weightage",
            action="select",
            database=target_db,
            filters={"DoerCode": clean_doer},
            fetch_all=True,
        )
        existing_rows = res_current.get("data", []) or []

        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        day_before = eff_from - timedelta(days=1)
        day_before_str = day_before.isoformat()

        # Process existing rows
        for row in existing_rows:
            row_id = row.get("WeightageID")
            row_active = str(row.get("Active") or "").strip().upper()
            row_eff_from = parse_date(row.get("EffectiveFromDate"))
            row_eff_to = parse_date(row.get("EffectiveToDate"))

            if row_active != "Y" or not row_eff_from:
                continue

            # Case 1: Future unstarted version on or after the new start date -> Void it (WR11)
            if row_eff_from >= eff_from:
                await query_gateway(
                    table="Z_KPI_Weightage",
                    action="update",
                    database=target_db,
                    where={"WeightageID": row_id},
                    data={
                        "Active": "N",
                        "LastSyncTS": now_str,
                        "LastUpdatedBy": clean_user,
                    },
                )
            # Case 2: Currently active version -> Close it with EffectiveToDate = day_before (WR10)
            elif row_eff_to is None or row_eff_to >= eff_from:
                await query_gateway(
                    table="Z_KPI_Weightage",
                    action="update",
                    database=target_db,
                    where={"WeightageID": row_id},
                    data={
                        "EffectiveToDate": day_before_str,
                        "LastSyncTS": now_str,
                        "LastUpdatedBy": clean_user,
                    },
                )

        # Insert the complete new set (WR5)
        created_records = []
        for nw in normalized_weights:
            insert_payload = {
                "DoerCode": clean_doer,
                "DoerName": doer_name,
                "KPICode": nw["KPI"],
                "KPIName": nw["KPIName"],
                "Weightage": nw["W"],
                "EffectiveFromDate": eff_from.isoformat(),
                "EffectiveToDate": None,
                "Active": "Y",
                "ChangeReason": clean_reason,
                "InsertTS": now_str,
                "InsertedBy": clean_user,
            }
            await query_gateway(
                table="Z_KPI_Weightage",
                action="insert",
                database=target_db,
                data=insert_payload,
            )
            created_records.append(insert_payload)

        logger.info(
            "SP_KPI_Weightage_Set executed successfully for Doer %s from %s (%d KPIs)",
            clean_doer,
            eff_from,
            len(created_records),
        )

        return {
            "status": "success",
            "message": f"Successfully set KPI weightage for {doer_name} ({clean_doer}) effective from {eff_from.isoformat()}.",
            "doer_code": clean_doer,
            "doer_name": doer_name,
            "effective_from": eff_from.isoformat(),
            "weights": normalized_weights,
        }

    @classmethod
    async def inactive_kpi_weightage(
        cls,
        doer_code: str,
        inactive_from_str: str,
        change_reason: str,
        user_code: str,
        database: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Section 5.6 & Section 6.2:
        EXEC dbo.SP_KPI_Weightage_Inactive
        @DoerCode = N'0017',
        @InactiveFromDate = '2026-12-01',
        @ChangeReason = N'Moved to Management',
        @UserCode = N'<logged-in user>';

        Closes the version: EffectiveToDate becomes day before InactiveFromDate.
        Does NOT set Active = N.
        Refused if doer is on any active FMS_Config row (53037).
        """
        target_db = database or settings.api_database
        today = date.today()

        # 53031–53035: Required values
        if not doer_code or not str(doer_code).strip():
            raise ApiError("SP_KPI_Weightage_Inactive: 53031 - DoerCode is required.")
        if not inactive_from_str or not str(inactive_from_str).strip():
            raise ApiError("SP_KPI_Weightage_Inactive: 53032 - InactiveFromDate is required.")
        if not change_reason or not str(change_reason).strip():
            raise ApiError("SP_KPI_Weightage_Inactive: 53033 - ChangeReason is mandatory.")
        if not user_code or not str(user_code).strip():
            raise ApiError("SP_KPI_Weightage_Inactive: 53034 - UserCode is required.")

        clean_doer = str(doer_code).strip()
        clean_reason = str(change_reason).strip()[:250]
        clean_user = str(user_code).strip()

        inactive_from = parse_date(inactive_from_str)
        if not inactive_from:
            raise ApiError("SP_KPI_Weightage_Inactive: 53035 - Invalid InactiveFromDate format.")

        # 53035: Date before today
        if inactive_from < today:
            raise ApiError("SP_KPI_Weightage_Inactive: 53035 - InactiveFromDate cannot be before today.")

        # Rule WR15 & 53037: Refused while doer is on active FMS_Config
        is_on_fms, stages = await cls.check_doer_active_in_fms_config(clean_doer, database=target_db)
        if is_on_fms:
            stage_details = ", ".join(f"{s['App_ID']}:{s['Stage_No']} ({'/'.join(s['Roles'])})" for s in stages[:3])
            raise ApiError(f"SP_KPI_Weightage_Inactive: 53037 - Remove this doer from FMS_Config first. Active in: {stage_details}")

        # Check existing weightage rows (53036: No weightage in effect from that date)
        res_current = await query_gateway(
            table="Z_KPI_Weightage",
            action="select",
            database=target_db,
            filters={"DoerCode": clean_doer},
            fetch_all=True,
        )
        existing_rows = res_current.get("data", []) or []

        has_active_set = False
        for row in existing_rows:
            if str(row.get("Active") or "").strip().upper() != "Y":
                continue
            eff_from = parse_date(row.get("EffectiveFromDate"))
            eff_to = parse_date(row.get("EffectiveToDate"))
            if eff_from and (eff_to is None or eff_to >= inactive_from):
                has_active_set = True
                break

        if not has_active_set:
            raise ApiError(f"SP_KPI_Weightage_Inactive: 53036 - No weightage in effect from date {inactive_from.isoformat()}.")

        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        day_before = inactive_from - timedelta(days=1)
        day_before_str = day_before.isoformat()

        # Close active version and void any future version starting >= inactive_from
        closed_count = 0
        for row in existing_rows:
            row_id = row.get("WeightageID")
            row_active = str(row.get("Active") or "").strip().upper()
            row_eff_from = parse_date(row.get("EffectiveFromDate"))
            row_eff_to = parse_date(row.get("EffectiveToDate"))

            if row_active != "Y" or not row_eff_from:
                continue

            # Future versions starting >= inactive_from get voided (Active = N)
            if row_eff_from >= inactive_from:
                await query_gateway(
                    table="Z_KPI_Weightage",
                    action="update",
                    database=target_db,
                    where={"WeightageID": row_id},
                    data={
                        "Active": "N",
                        "ChangeReason": f"{row.get('ChangeReason') or ''} | Voided by Inactive",
                        "LastSyncTS": now_str,
                        "LastUpdatedBy": clean_user,
                    },
                )
            # Currently active version gets EffectiveToDate = day_before
            elif row_eff_to is None or row_eff_to >= inactive_from:
                old_reason = str(row.get("ChangeReason") or "").strip()
                updated_reason = f"{old_reason} | Closed: {clean_reason}"[:250]
                await query_gateway(
                    table="Z_KPI_Weightage",
                    action="update",
                    database=target_db,
                    where={"WeightageID": row_id},
                    data={
                        "EffectiveToDate": day_before_str,
                        "ChangeReason": updated_reason,
                        "LastSyncTS": now_str,
                        "LastUpdatedBy": clean_user,
                    },
                )
                closed_count += 1

        logger.info(
            "SP_KPI_Weightage_Inactive executed successfully for Doer %s from %s (%d rows closed)",
            clean_doer,
            inactive_from,
            closed_count,
        )

        return {
            "status": "success",
            "message": f"Successfully marked doer '{clean_doer}' inactive from {inactive_from.isoformat()}.",
            "doer_code": clean_doer,
            "inactive_from": inactive_from.isoformat(),
            "closed_count": closed_count,
        }

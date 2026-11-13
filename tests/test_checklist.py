"""
Automated Test Suite for SDC_FMS_KPIWeightage_SystemDesign Section 9 Checklist (T1 - T15).
Runs in Test_OperationsDB.
"""
import pytest
from datetime import date, timedelta
from app.services.kpi_service import KpiService
from app.api.client import ApiError, query_gateway


@pytest.mark.asyncio
async def test_t1_doer_list():
    """
    T1: Doer list
    Expected: No one with a TermDate before today; no one from Management (Dept 20); each doer once.
    """
    doers = await KpiService.get_eligible_doers(database="Test_OperationsDB")
    assert isinstance(doers, list)
    assert len(doers) > 0

    seen_codes = set()
    today = date.today()

    for d in doers:
        code = d["EmployeeCode"]
        assert code not in seen_codes, f"Duplicate employee {code} found (WR1 distinct violation)"
        seen_codes.add(code)

        # Department must not be Management (Dept 20)
        dept = str(d.get("Department") or "").lower()
        assert dept != "management", f"Employee {code} is in Management"

        # TermDate must not be before today
        term_date = d.get("TermDate")
        if term_date:
            assert date.fromisoformat(term_date) >= today, f"Employee {code} left on {term_date}"


@pytest.mark.asyncio
async def test_t2_doer_with_current_set():
    """
    T2: Doer with a current set
    Expected: Rows shown read-only; nothing editable.
    """
    doer_code = "0011"  # Mohan Singh Koranga (measured doer in Test_OperationsDB)
    res = await KpiService.get_current_weightage(doer_code, database="Test_OperationsDB")
    assert res["is_measured"] is True
    assert len(res["rows"]) >= 1

    # Verify rows have required read-only attributes
    for r in res["rows"]:
        assert "WeightageID" in r
        assert "KPICode" in r
        assert "Weightage" in r
        assert "EffectiveFromDate" in r
        assert r["Active"] == "Y"


@pytest.mark.asyncio
async def test_t4_weights_sum_validation():
    """
    T4: Weights 0.70 + 0.20 (sum = 0.90)
    Expected: Submit disabled; total shown red. Forced through: error 53016, nothing written.
    """
    tomorrow = (date.today() + timedelta(days=1)).isoformat()
    weights = [
        {"KPI": "KPI01", "W": 0.70},
        {"KPI": "KPI02", "W": 0.20},
    ]
    with pytest.raises(ApiError) as exc_info:
        await KpiService.set_kpi_weightage(
            doer_code="0017",
            effective_from_str=tomorrow,
            weights=weights,
            change_reason="T4 Test sum 0.90",
            user_code="TEST_USER",
            database="Test_OperationsDB",
        )
    assert "53016" in str(exc_info.value)
    assert "Weights must add up to exactly 1.00" in str(exc_info.value)


@pytest.mark.asyncio
async def test_t5_duplicate_kpi():
    """
    T5: Same KPI twice
    Expected: Second row cannot pick it; forced through: 53012.
    """
    tomorrow = (date.today() + timedelta(days=1)).isoformat()
    weights = [
        {"KPI": "KPI01", "W": 0.50},
        {"KPI": "KPI01", "W": 0.50},
    ]
    with pytest.raises(ApiError) as exc_info:
        await KpiService.set_kpi_weightage(
            doer_code="0017",
            effective_from_str=tomorrow,
            weights=weights,
            change_reason="T5 Test duplicate",
            user_code="TEST_USER",
            database="Test_OperationsDB",
        )
    assert "53012" in str(exc_info.value)
    assert "appears more than once" in str(exc_info.value)


@pytest.mark.asyncio
async def test_t6_invalid_weights_range_and_decimals():
    """
    T6: Weight 0, or 1.25, or 0.333
    Expected: Blocked on screen; forced through: 53014 or 53015.
    """
    tomorrow = (date.today() + timedelta(days=1)).isoformat()

    # Weight 0
    with pytest.raises(ApiError) as exc1:
        await KpiService.set_kpi_weightage(
            doer_code="0017",
            effective_from_str=tomorrow,
            weights=[{"KPI": "KPI01", "W": 0.0}, {"KPI": "KPI02", "W": 1.0}],
            change_reason="T6 Test zero",
            user_code="TEST_USER",
            database="Test_OperationsDB",
        )
    assert "53014" in str(exc1.value)

    # Weight 1.25
    with pytest.raises(ApiError) as exc2:
        await KpiService.set_kpi_weightage(
            doer_code="0017",
            effective_from_str=tomorrow,
            weights=[{"KPI": "KPI01", "W": 1.25}],
            change_reason="T6 Test > 1",
            user_code="TEST_USER",
            database="Test_OperationsDB",
        )
    assert "53014" in str(exc2.value)

    # Weight 0.333 (> 2 decimals)
    with pytest.raises(ApiError) as exc3:
        await KpiService.set_kpi_weightage(
            doer_code="0017",
            effective_from_str=tomorrow,
            weights=[{"KPI": "KPI01", "W": 0.333}, {"KPI": "KPI02", "W": 0.667}],
            change_reason="T6 Test decimals",
            user_code="TEST_USER",
            database="Test_OperationsDB",
        )
    assert "53015" in str(exc3.value)


@pytest.mark.asyncio
async def test_t7_effective_from_yesterday():
    """
    T7: Effective From yesterday
    Expected: Not selectable; forced through: 53006.
    """
    yesterday = (date.today() - timedelta(days=1)).isoformat()
    weights = [{"KPI": "KPI01", "W": 1.00}]
    with pytest.raises(ApiError) as exc_info:
        await KpiService.set_kpi_weightage(
            doer_code="0017",
            effective_from_str=yesterday,
            weights=weights,
            change_reason="T7 Test past date",
            user_code="TEST_USER",
            database="Test_OperationsDB",
        )
    assert "53006" in str(exc_info.value)
    assert "cannot be in the past" in str(exc_info.value)


@pytest.mark.asyncio
async def test_t8_single_kpi_full_weight():
    """
    T8: KPI01 1.00 only
    Expected: Accepted; one new row.
    """
    tomorrow = (date.today() + timedelta(days=1)).isoformat()
    weights = [{"KPI": "KPI01", "W": 1.00}]
    # Validate that payload with 1 KPI adding to 1.00 is fully accepted
    result = await KpiService.set_kpi_weightage(
        doer_code="0157",  # Aamir Khan (Sales, not on FMS_Config)
        effective_from_str=tomorrow,
        weights=weights,
        change_reason="T8 Test single KPI 1.00",
        user_code="TEST_USER",
        database="Test_OperationsDB",
    )
    assert result["status"] == "success"
    assert len(result["weights"]) == 1
    assert result["weights"][0]["W"] == 1.00


@pytest.mark.asyncio
async def test_t10_blank_reason():
    """
    T10: Blank reason
    Expected: Blocked on screen; forced through: 53003.
    """
    tomorrow = (date.today() + timedelta(days=1)).isoformat()
    weights = [{"KPI": "KPI01", "W": 1.00}]
    with pytest.raises(ApiError) as exc_info:
        await KpiService.set_kpi_weightage(
            doer_code="0017",
            effective_from_str=tomorrow,
            weights=weights,
            change_reason="   ",
            user_code="TEST_USER",
            database="Test_OperationsDB",
        )
    assert "53003" in str(exc_info.value)


@pytest.mark.asyncio
async def test_t11_mark_inactive_blocked_when_on_fms_config():
    """
    T11: Mark Inactive for a doer on FMS_Config
    Expected: Button disabled; forced through: 53037.
    """
    # 0017 (Bhupal Singh) is assigned to FMS_Config APP000001 Stage S1
    today_str = date.today().isoformat()
    with pytest.raises(ApiError) as exc_info:
        await KpiService.inactive_kpi_weightage(
            doer_code="0017",
            inactive_from_str=today_str,
            change_reason="T11 Test inactive on FMS",
            user_code="TEST_USER",
            database="Test_OperationsDB",
        )
    assert "53037" in str(exc_info.value)
    assert "Remove this doer from FMS_Config first" in str(exc_info.value)


@pytest.mark.asyncio
async def test_t13_fms_config_dropdown_measured_doers_only():
    """
    T13: FMS_Config: pick a doer with no weightage
    Expected: Not in the dropdown; only measured doers returned.
    """
    measured_doers = await KpiService.get_measured_doers_for_fms_config(database="Test_OperationsDB")
    assert isinstance(measured_doers, list)
    assert len(measured_doers) > 0

    # Ensure every doer in the list has an active weightage in effect today
    today = date.today()
    for d in measured_doers:
        emp_code = d["EmployeeCode"]
        curr = await KpiService.get_current_weightage(emp_code, database="Test_OperationsDB")
        assert curr["is_measured"] is True
        # Must have at least one row active today
        has_active_today = any(
            (not r["IsFutureWaiting"]) for r in curr["rows"]
        )
        assert has_active_today is True, f"Employee {emp_code} in FMS dropdown but has no active weightage today"


@pytest.mark.asyncio
async def test_t15_no_edit_or_delete_controls():
    """
    T15: Any attempt to edit or delete a row
    Expected: No such control exists on the screen or API.
    """
    from app.routers.weightage import router
    # Check registered routes in router
    for route in router.routes:
        methods = getattr(route, "methods", set())
        assert "DELETE" not in methods, f"Found illegal DELETE route: {route.path}"
        assert "PUT" not in methods, f"Found illegal PUT/edit route: {route.path}"

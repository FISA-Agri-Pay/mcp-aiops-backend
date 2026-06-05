import pytest

from aiops_platform.farm_advisory.service import (
    FarmAdvisoryService,
    FarmAdvisoryValidationError,
)
from aiops_platform.farmer_bnpl.service import FarmerBnplService


def test_crop_calendar_returns_planning_to_harvest_stages() -> None:
    service = FarmAdvisoryService()

    result = service.get_crop_calendar(crop_type="rice", region="jeonbuk")

    assert result.crop_type == "rice"
    assert result.region == "jeonbuk"
    assert [stage.stage for stage in result.stages] == [
        "planning",
        "planting",
        "growth",
        "harvest",
    ]


def test_material_recommendations_include_bnpl_product_ids() -> None:
    service = FarmAdvisoryService()

    result = service.recommend_farming_materials(crop_type="rice", area_hectare=1.0)

    assert result.estimated_budget == 432_000
    assert result.bnpl_eligible_hint is True
    assert result.recommended_product_ids == [
        "fertilizer-organic-20kg",
        "seed-rice-10kg",
        "pesticide-safe-1l",
    ]


def test_product_bundle_cart_items_can_feed_farmer_bnpl_cart_total() -> None:
    advisory_service = FarmAdvisoryService()
    bnpl_service = FarmerBnplService()

    bundle = advisory_service.recommend_product_bundle(crop_type="rice", area_hectare=1.0)
    cart_total = bnpl_service.calculate_cart_total(items=bundle.cart_items)

    assert bundle.estimated_budget == 432_000
    assert cart_total.total_amount == bundle.estimated_budget


def test_risk_triage_income_cashflow_and_glossary_return_decision_support() -> None:
    service = FarmAdvisoryService()

    weather = service.get_weather_risk(crop_type="rice", region="jeonbuk", forecast_days=30)
    triage = service.triage_crop_disease(
        crop_type="rice",
        symptoms=["yellow leaves", "spots"],
        severity="high",
    )
    income = service.simulate_crop_income(crop_type="rice", area_hectare=1.0)
    cashflow = service.simulate_season_cashflow(
        crop_type="rice",
        area_hectare=1.0,
        starting_cash=100_000,
        bnpl_limit=1_000_000,
    )
    term = service.translate_finance_terms_for_farmer(term="interest")

    assert weather.forecast_days == 14
    assert triage.urgency == "HIGH"
    assert income.estimated_net_income == 14_518_000
    assert cashflow.recommended_bnpl_amount == 332_000
    assert term.related_terms == ["principal", "due date"]


def test_unsupported_crop_is_rejected() -> None:
    service = FarmAdvisoryService()

    with pytest.raises(FarmAdvisoryValidationError, match="crop_type is not supported"):
        service.get_crop_calendar(crop_type="unknown")

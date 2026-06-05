from __future__ import annotations

from dataclasses import dataclass

from aiops_platform.farm_advisory.schemas import (
    CashflowMonth,
    CropCalendarResult,
    CropCalendarStage,
    CropIncomeSimulationResult,
    DiseaseTriageResult,
    FertilizerRequirementResult,
    FinanceTermTranslationResult,
    MaterialRecommendation,
    MaterialRecommendationResult,
    ProductBundleItem,
    ProductBundleResult,
    RankedMaterialOption,
    RankedMaterialOptionsResult,
    SeasonCashflowResult,
    WeatherRiskItem,
    WeatherRiskResult,
)
from aiops_platform.farmer_bnpl.schemas import ProductResult
from aiops_platform.farmer_bnpl.service import PRODUCT_CATALOG


class FarmAdvisoryValidationError(ValueError):
    pass


DEFAULT_BNPL_ELIGIBLE_BUDGET = 3_000_000
MAX_RECOMMENDATION_AREA_HECTARE = 1000


@dataclass(frozen=True)
class CropProfile:
    crop_type: str
    default_season: str
    yield_kg_per_hectare: int
    price_per_kg: int
    fertilizer_bags_per_hectare: int
    seed_units_per_hectare: int
    pesticide_units_per_hectare: int


CROP_PROFILES = {
    "rice": CropProfile(
        crop_type="rice",
        default_season="spring",
        yield_kg_per_hectare=6500,
        price_per_kg=2300,
        fertilizer_bags_per_hectare=12,
        seed_units_per_hectare=3,
        pesticide_units_per_hectare=2,
    ),
    "pepper": CropProfile(
        crop_type="pepper",
        default_season="spring",
        yield_kg_per_hectare=4200,
        price_per_kg=4100,
        fertilizer_bags_per_hectare=16,
        seed_units_per_hectare=4,
        pesticide_units_per_hectare=3,
    ),
    "cabbage": CropProfile(
        crop_type="cabbage",
        default_season="fall",
        yield_kg_per_hectare=5200,
        price_per_kg=1800,
        fertilizer_bags_per_hectare=14,
        seed_units_per_hectare=3,
        pesticide_units_per_hectare=2,
    ),
}


FINANCE_TERMS = {
    "credit limit": FinanceTermTranslationResult(
        term="credit limit",
        plain_language="The maximum BNPL amount you can use for approved farm input purchases.",
        example="If your limit is 3,000,000 KRW and you used 500,000 KRW, 2,500,000 KRW remains.",
        related_terms=["available limit", "used amount"],
    ),
    "interest": FinanceTermTranslationResult(
        term="interest",
        plain_language="The extra fee paid for using BNPL money until repayment.",
        example="If interest due this month is 12,000 KRW, that is paid in addition to principal.",
        related_terms=["principal", "due date"],
    ),
    "overdue": FinanceTermTranslationResult(
        term="overdue",
        plain_language="A repayment that has passed its due date and still has not been paid.",
        example="If payment was due on June 1 and is unpaid on June 5, it is overdue.",
        related_terms=["repayment schedule", "late fee"],
    ),
}


class FarmAdvisoryService:
    def get_crop_calendar(
        self,
        *,
        crop_type: str,
        region: str | None = None,
        season: str | None = None,
    ) -> CropCalendarResult:
        profile = resolve_crop_profile(crop_type)
        resolved_season = normalize_optional_text(season) or profile.default_season
        return CropCalendarResult(
            crop_type=profile.crop_type,
            region=normalize_optional_text(region),
            season=resolved_season,
            stages=[
                CropCalendarStage(
                    stage="planning",
                    month="M-2",
                    tasks=["Confirm field area", "Estimate input budget", "Check BNPL limit"],
                ),
                CropCalendarStage(
                    stage="planting",
                    month="M",
                    tasks=["Prepare soil", "Purchase seed and base fertilizer", "Plant crop"],
                ),
                CropCalendarStage(
                    stage="growth",
                    month="M+1",
                    tasks=["Monitor weather risk", "Apply fertilizer", "Inspect disease symptoms"],
                ),
                CropCalendarStage(
                    stage="harvest",
                    month="M+3",
                    tasks=[
                        "Estimate yield",
                        "Plan repayment from sales",
                        "Review next season inputs",
                    ],
                ),
            ],
        )

    def recommend_farming_materials(
        self,
        *,
        crop_type: str,
        area_hectare: float,
        region: str | None = None,
        season: str | None = None,
    ) -> MaterialRecommendationResult:
        profile = resolve_crop_profile(crop_type)
        validate_area(area_hectare)
        recommendations = build_material_recommendations(profile, area_hectare)
        estimated_budget = sum(item.estimated_cost for item in recommendations)
        return MaterialRecommendationResult(
            crop_type=profile.crop_type,
            area_hectare=area_hectare,
            recommended_product_ids=[item.product_id for item in recommendations],
            estimated_budget=estimated_budget,
            bnpl_eligible_hint=estimated_budget <= DEFAULT_BNPL_ELIGIBLE_BUDGET,
            recommendations=recommendations,
        )

    def recommend_fertilizer_requirements(
        self,
        *,
        crop_type: str,
        area_hectare: float,
        soil_type: str | None = None,
    ) -> FertilizerRequirementResult:
        profile = resolve_crop_profile(crop_type)
        validate_area(area_hectare)
        nitrogen_kg = round(profile.fertilizer_bags_per_hectare * area_hectare * 1.6, 2)
        phosphate_kg = round(profile.fertilizer_bags_per_hectare * area_hectare * 0.9, 2)
        potassium_kg = round(profile.fertilizer_bags_per_hectare * area_hectare * 1.1, 2)
        fertilizer = get_catalog_product("fertilizer-organic-20kg")
        bag_count = quantity_for_area(profile.fertilizer_bags_per_hectare, area_hectare)
        return FertilizerRequirementResult(
            crop_type=profile.crop_type,
            area_hectare=area_hectare,
            soil_type=normalize_optional_text(soil_type),
            nitrogen_kg=nitrogen_kg,
            phosphate_kg=phosphate_kg,
            potassium_kg=potassium_kg,
            recommended_product_ids=[fertilizer.product_id],
            estimated_budget=bag_count * fertilizer.unit_price,
        )

    def rank_material_options(
        self,
        *,
        crop_type: str,
        material_type: str,
        budget: int | None = None,
    ) -> RankedMaterialOptionsResult:
        profile = resolve_crop_profile(crop_type)
        resolved_material_type = normalize_required_text(material_type, field_name="material_type")
        if budget is not None and budget < 0:
            raise FarmAdvisoryValidationError("budget must be greater than or equal to 0.")
        products = [
            product
            for product in PRODUCT_CATALOG
            if product.category == resolved_material_type
            or resolved_material_type in product.name.lower()
        ]
        options = [
            RankedMaterialOption(
                product_id=product.product_id,
                product_name=product.name,
                material_type=product.category,
                unit_price=product.unit_price,
                score=score_product(product, budget=budget),
                reason=(
                    f"Fits {profile.crop_type} planning with "
                    f"{product.stock_status.lower()} stock."
                ),
            )
            for product in products
        ]
        options.sort(key=lambda option: option.score, reverse=True)
        return RankedMaterialOptionsResult(
            crop_type=profile.crop_type,
            material_type=resolved_material_type,
            budget=budget,
            options=options,
        )

    def recommend_product_bundle(
        self,
        *,
        crop_type: str,
        area_hectare: float,
        budget: int | None = None,
    ) -> ProductBundleResult:
        profile = resolve_crop_profile(crop_type)
        validate_area(area_hectare)
        if budget is not None and budget < 0:
            raise FarmAdvisoryValidationError("budget must be greater than or equal to 0.")

        bundle_items = []
        for recommendation in build_material_recommendations(profile, area_hectare):
            product = get_catalog_product(recommendation.product_id)
            bundle_items.append(
                ProductBundleItem(
                    product_id=product.product_id,
                    product_name=product.name,
                    quantity=recommendation.quantity,
                    unit_price=product.unit_price,
                    line_total=product.unit_price * recommendation.quantity,
                )
            )
        if budget is not None:
            bundle_items = filter_bundle_by_budget(bundle_items, budget)
        estimated_budget = sum(item.line_total for item in bundle_items)
        return ProductBundleResult(
            crop_type=profile.crop_type,
            area_hectare=area_hectare,
            recommended_product_ids=[item.product_id for item in bundle_items],
            cart_items=[
                {"product_id": item.product_id, "quantity": item.quantity}
                for item in bundle_items
            ],
            estimated_budget=estimated_budget,
            bnpl_eligible_hint=estimated_budget <= DEFAULT_BNPL_ELIGIBLE_BUDGET,
            bundle_items=bundle_items,
        )

    def get_weather_risk(
        self,
        *,
        crop_type: str,
        region: str,
        forecast_days: int = 7,
    ) -> WeatherRiskResult:
        profile = resolve_crop_profile(crop_type)
        resolved_region = normalize_required_text(region, field_name="region")
        if not isinstance(forecast_days, int) or isinstance(forecast_days, bool):
            raise FarmAdvisoryValidationError("forecast_days must be an integer.")
        clamped_days = min(max(forecast_days, 1), 14)
        return WeatherRiskResult(
            crop_type=profile.crop_type,
            region=resolved_region,
            forecast_days=clamped_days,
            risks=[
                WeatherRiskItem(
                    risk_type="heavy_rain",
                    level="MEDIUM",
                    description=(
                        "Skeleton forecast indicates possible rainfall during growth stage."
                    ),
                    recommended_action=(
                        "Check drainage and delay fertilizer if heavy rain is expected."
                    ),
                ),
                WeatherRiskItem(
                    risk_type="heat",
                    level="LOW",
                    description="No severe heat signal is connected in this skeleton.",
                    recommended_action="Monitor irrigation needs during midday heat.",
                ),
            ],
        )

    def triage_crop_disease(
        self,
        *,
        crop_type: str,
        symptoms: list[str],
        severity: str = "medium",
    ) -> DiseaseTriageResult:
        profile = resolve_crop_profile(crop_type)
        normalized_symptoms = [
            normalize_required_text(item, field_name="symptom") for item in symptoms
        ]
        if not normalized_symptoms:
            raise FarmAdvisoryValidationError("symptoms must not be empty.")
        normalized_severity = normalize_required_text(severity, field_name="severity")
        urgency = {"low": "LOW", "medium": "MEDIUM", "high": "HIGH"}.get(
            normalized_severity,
            "MEDIUM",
        )
        return DiseaseTriageResult(
            crop_type=profile.crop_type,
            symptoms=normalized_symptoms,
            urgency=urgency,
            possible_conditions=["nutrient_deficiency", "fungal_disease"],
            recommended_actions=[
                "Take clear photos of affected leaves.",
                "Avoid additional pesticide until expert confirmation.",
                "Compare symptoms with local extension guidance.",
            ],
            disclaimer="This is decision-support only and not a confirmed diagnosis.",
        )

    def simulate_crop_income(
        self,
        *,
        crop_type: str,
        area_hectare: float,
        expected_yield_kg_per_hectare: int | None = None,
        expected_price_per_kg: int | None = None,
        estimated_input_cost: int | None = None,
    ) -> CropIncomeSimulationResult:
        profile = resolve_crop_profile(crop_type)
        validate_area(area_hectare)
        yield_per_hectare = expected_yield_kg_per_hectare or profile.yield_kg_per_hectare
        price_per_kg = expected_price_per_kg or profile.price_per_kg
        if yield_per_hectare <= 0 or price_per_kg < 0:
            raise FarmAdvisoryValidationError("income simulation inputs are invalid.")
        expected_yield_kg = int(yield_per_hectare * area_hectare)
        expected_revenue = expected_yield_kg * price_per_kg
        input_cost = estimated_input_cost
        if input_cost is None:
            input_cost = self.recommend_product_bundle(
                crop_type=profile.crop_type,
                area_hectare=area_hectare,
            ).estimated_budget
        if input_cost < 0:
            raise FarmAdvisoryValidationError(
                "estimated_input_cost must be greater than or equal to 0."
            )
        return CropIncomeSimulationResult(
            crop_type=profile.crop_type,
            area_hectare=area_hectare,
            expected_yield_kg=expected_yield_kg,
            expected_revenue=expected_revenue,
            estimated_input_cost=input_cost,
            estimated_net_income=expected_revenue - input_cost,
        )

    def simulate_season_cashflow(
        self,
        *,
        crop_type: str,
        area_hectare: float,
        starting_cash: int = 0,
        bnpl_limit: int = DEFAULT_BNPL_ELIGIBLE_BUDGET,
    ) -> SeasonCashflowResult:
        profile = resolve_crop_profile(crop_type)
        validate_area(area_hectare)
        if starting_cash < 0 or bnpl_limit < 0:
            raise FarmAdvisoryValidationError("cashflow inputs must be greater than or equal to 0.")
        bundle = self.recommend_product_bundle(
            crop_type=profile.crop_type,
            area_hectare=area_hectare,
        )
        income = self.simulate_crop_income(crop_type=profile.crop_type, area_hectare=area_hectare)
        recommended_bnpl_amount = min(max(bundle.estimated_budget - starting_cash, 0), bnpl_limit)
        months = [
            CashflowMonth(
                month="M",
                inflow=starting_cash + recommended_bnpl_amount,
                outflow=bundle.estimated_budget,
                net_cashflow=starting_cash + recommended_bnpl_amount - bundle.estimated_budget,
                note="Input purchase month.",
            ),
            CashflowMonth(
                month="M+1",
                inflow=0,
                outflow=int(bundle.estimated_budget * 0.1),
                net_cashflow=-int(bundle.estimated_budget * 0.1),
                note="Crop management and small follow-up purchases.",
            ),
            CashflowMonth(
                month="M+3",
                inflow=income.expected_revenue,
                outflow=recommended_bnpl_amount,
                net_cashflow=income.expected_revenue - recommended_bnpl_amount,
                note="Harvest sale and BNPL repayment planning.",
            ),
        ]
        return SeasonCashflowResult(
            crop_type=profile.crop_type,
            area_hectare=area_hectare,
            starting_cash=starting_cash,
            recommended_bnpl_amount=recommended_bnpl_amount,
            bnpl_limit=bnpl_limit,
            months=months,
        )

    def translate_finance_terms_for_farmer(self, *, term: str) -> FinanceTermTranslationResult:
        normalized_term = normalize_required_text(term, field_name="term")
        return FINANCE_TERMS.get(
            normalized_term,
            FinanceTermTranslationResult(
                term=normalized_term,
                plain_language="This term is not in the skeleton glossary yet.",
                example="Ask an advisor to confirm how this applies to your BNPL purchase.",
                related_terms=[],
            ),
        )


def resolve_crop_profile(crop_type: str) -> CropProfile:
    normalized_crop = normalize_required_text(crop_type, field_name="crop_type")
    if normalized_crop in CROP_PROFILES:
        return CROP_PROFILES[normalized_crop]
    raise FarmAdvisoryValidationError("crop_type is not supported.")


def validate_area(area_hectare: float) -> None:
    if (
        isinstance(area_hectare, int | float)
        and not isinstance(area_hectare, bool)
        and 0 < area_hectare <= MAX_RECOMMENDATION_AREA_HECTARE
    ):
        return
    raise FarmAdvisoryValidationError("area_hectare is invalid.")


def normalize_required_text(value: str, *, field_name: str) -> str:
    if not isinstance(value, str):
        raise FarmAdvisoryValidationError(f"{field_name} is invalid.")
    normalized = value.strip().lower()
    if normalized:
        return normalized
    raise FarmAdvisoryValidationError(f"{field_name} must not be empty.")


def normalize_optional_text(value: str | None) -> str | None:
    if value is None:
        return None
    return normalize_required_text(value, field_name="value")


def quantity_for_area(rate_per_hectare: int, area_hectare: float) -> int:
    return max(1, int(rate_per_hectare * area_hectare))


def get_catalog_product(product_id: str) -> ProductResult:
    for product in PRODUCT_CATALOG:
        if product.product_id == product_id:
            return product
    raise FarmAdvisoryValidationError("recommended product is not in the BNPL catalog.")


def build_material_recommendations(
    profile: CropProfile,
    area_hectare: float,
) -> list[MaterialRecommendation]:
    fertilizer = get_catalog_product("fertilizer-organic-20kg")
    seed = get_catalog_product("seed-rice-10kg")
    pesticide = get_catalog_product("pesticide-safe-1l")
    recommendations = [
        MaterialRecommendation(
            material_type="fertilizer",
            product_id=fertilizer.product_id,
            product_name=fertilizer.name,
            quantity=quantity_for_area(profile.fertilizer_bags_per_hectare, area_hectare),
            unit="bag",
            estimated_cost=quantity_for_area(
                profile.fertilizer_bags_per_hectare,
                area_hectare,
            )
            * fertilizer.unit_price,
            reason="Base fertilizer for early growth and soil preparation.",
        ),
        MaterialRecommendation(
            material_type="seed",
            product_id=seed.product_id,
            product_name=seed.name,
            quantity=quantity_for_area(profile.seed_units_per_hectare, area_hectare),
            unit="pack",
            estimated_cost=quantity_for_area(profile.seed_units_per_hectare, area_hectare)
            * seed.unit_price,
            reason="Seed quantity sized from crop and field area.",
        ),
        MaterialRecommendation(
            material_type="pesticide",
            product_id=pesticide.product_id,
            product_name=pesticide.name,
            quantity=quantity_for_area(profile.pesticide_units_per_hectare, area_hectare),
            unit="bottle",
            estimated_cost=quantity_for_area(
                profile.pesticide_units_per_hectare,
                area_hectare,
            )
            * pesticide.unit_price,
            reason="Preventive crop care item for the main growth stage.",
        ),
    ]
    return recommendations


def score_product(product: ProductResult, *, budget: int | None) -> float:
    stock_bonus = {"IN_STOCK": 0.2, "LOW_STOCK": 0.05, "OUT_OF_STOCK": -0.5}[
        product.stock_status
    ]
    price_score = max(0.0, 1.0 - (product.unit_price / 100_000))
    if budget is not None and product.unit_price > budget:
        price_score -= 0.4
    return round(price_score + stock_bonus, 3)


def filter_bundle_by_budget(
    bundle_items: list[ProductBundleItem],
    budget: int,
) -> list[ProductBundleItem]:
    selected = []
    running_total = 0
    for item in sorted(bundle_items, key=lambda bundle_item: bundle_item.line_total):
        if running_total + item.line_total <= budget:
            selected.append(item)
            running_total += item.line_total
    return selected

from typing import Literal

from pydantic import BaseModel, Field


class CropCalendarStage(BaseModel):
    stage: str
    month: str
    tasks: list[str]


class CropCalendarResult(BaseModel):
    crop_type: str
    region: str | None = None
    season: str
    stages: list[CropCalendarStage]


class MaterialRecommendation(BaseModel):
    material_type: str
    product_id: str
    product_name: str
    quantity: int
    unit: str
    estimated_cost: int
    reason: str


class MaterialRecommendationResult(BaseModel):
    crop_type: str
    area_hectare: float
    recommended_product_ids: list[str]
    estimated_budget: int
    bnpl_eligible_hint: bool
    recommendations: list[MaterialRecommendation]


class FertilizerRequirementResult(BaseModel):
    crop_type: str
    area_hectare: float
    soil_type: str | None = None
    nitrogen_kg: float
    phosphate_kg: float
    potassium_kg: float
    recommended_product_ids: list[str]
    estimated_budget: int


class RankedMaterialOption(BaseModel):
    product_id: str
    product_name: str
    material_type: str
    unit_price: int
    score: float
    reason: str


class RankedMaterialOptionsResult(BaseModel):
    crop_type: str
    material_type: str
    budget: int | None = None
    options: list[RankedMaterialOption]


class ProductBundleItem(BaseModel):
    product_id: str
    product_name: str
    quantity: int
    unit_price: int
    line_total: int


class ProductBundleResult(BaseModel):
    crop_type: str
    area_hectare: float
    recommended_product_ids: list[str]
    cart_items: list[dict[str, int | str]]
    estimated_budget: int
    bnpl_eligible_hint: bool
    bundle_items: list[ProductBundleItem]


class WeatherRiskItem(BaseModel):
    risk_type: str
    level: Literal["LOW", "MEDIUM", "HIGH"]
    description: str
    recommended_action: str


class WeatherRiskResult(BaseModel):
    crop_type: str
    region: str
    forecast_days: int
    risks: list[WeatherRiskItem]


class DiseaseTriageResult(BaseModel):
    crop_type: str
    symptoms: list[str]
    urgency: Literal["LOW", "MEDIUM", "HIGH"]
    possible_conditions: list[str]
    recommended_actions: list[str]
    disclaimer: str


class CropIncomeSimulationResult(BaseModel):
    crop_type: str
    area_hectare: float
    expected_yield_kg: int
    expected_revenue: int
    estimated_input_cost: int
    estimated_net_income: int
    currency: Literal["KRW"] = "KRW"


class CashflowMonth(BaseModel):
    month: str
    inflow: int
    outflow: int
    net_cashflow: int
    note: str


class SeasonCashflowResult(BaseModel):
    crop_type: str
    area_hectare: float
    starting_cash: int
    recommended_bnpl_amount: int
    bnpl_limit: int
    months: list[CashflowMonth]
    currency: Literal["KRW"] = "KRW"


class FinanceTermTranslationResult(BaseModel):
    term: str
    plain_language: str
    example: str
    related_terms: list[str] = Field(default_factory=list)


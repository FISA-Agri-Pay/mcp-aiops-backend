from uuid import UUID

import pytest
from pydantic import ValidationError

from aiops_platform.core.config import Settings


def test_observability_timeouts_must_be_positive() -> None:
    with pytest.raises(ValidationError):
        Settings(PROMETHEUS_TIMEOUT_SECONDS=0)

    with pytest.raises(ValidationError):
        Settings(LOKI_TIMEOUT_SECONDS=0)

    with pytest.raises(ValidationError):
        Settings(KUBERNETES_TIMEOUT_SECONDS=0)

    with pytest.raises(ValidationError):
        Settings(KAFKA_TIMEOUT_SECONDS=0)

    with pytest.raises(ValidationError):
        Settings(BATCH_TIMEOUT_SECONDS=0)

    with pytest.raises(ValidationError):
        Settings(ELASTICSEARCH_TIMEOUT_SECONDS=-1)


def test_default_checkout_product_id_must_be_uuid() -> None:
    settings = Settings()

    assert isinstance(settings.farmer_bnpl_default_checkout_product_id, UUID)

    with pytest.raises(ValidationError):
        Settings(FARMER_BNPL_DEFAULT_CHECKOUT_PRODUCT_ID="not-a-uuid")

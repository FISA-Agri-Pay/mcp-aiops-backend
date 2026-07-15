import os
import warnings
from pathlib import Path

import pytest

from aiops_platform.core.database import engine

SEED_OPT_IN_ENV = "RUN_TEST_SEEDS"
LOCAL_DB_HOSTS = {"localhost", "127.0.0.1", "::1"}
LOCAL_DB_NAMES = {"kkpp", "kkpp_test", "aiops_test"}


@pytest.fixture(scope="session", autouse=True)
def seed_local_database() -> None:
    if os.getenv(SEED_OPT_IN_ENV, "").lower() not in {"1", "true", "yes", "on"}:
        warnings.warn(
            f"Skipping local DB seed. Set {SEED_OPT_IN_ENV}=true to opt in.",
            stacklevel=2,
        )
        return

    url = engine.url
    if url.host not in LOCAL_DB_HOSTS and url.database not in LOCAL_DB_NAMES:
        pytest.skip(f"Refusing to seed non-local database URL: {url.render_as_string()}")

    seed_path = (
        Path(__file__).resolve().parents[1]
        / "tests"
        / "seed"
        / "local_dummy.sql"
    )
    sql = seed_path.read_text(encoding="utf-8")
    connection = engine.raw_connection()
    try:
        cursor = connection.cursor()
        cursor.execute(sql)
        cursor.close()
        connection.commit()
    finally:
        connection.close()

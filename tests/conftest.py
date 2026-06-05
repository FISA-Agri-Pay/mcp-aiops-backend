from pathlib import Path

import pytest

from aiops_platform.core.database import engine


@pytest.fixture(scope="session", autouse=True)
def seed_local_database() -> None:
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

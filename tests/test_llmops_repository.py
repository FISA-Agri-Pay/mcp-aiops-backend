import pytest

from aiops_platform.llmops.repository import SqlLlmOpsRepository


class FakeSession:
    def __init__(self) -> None:
        self.commits = 0
        self.rollbacks = 0

    def commit(self) -> None:
        self.commits += 1

    def rollback(self) -> None:
        self.rollbacks += 1


def test_session_scope_rolls_back_injected_session_on_error() -> None:
    session = FakeSession()
    repository = SqlLlmOpsRepository(session=session)

    with pytest.raises(RuntimeError):
        with repository._session_scope(commit=True):
            raise RuntimeError("boom")

    assert session.rollbacks == 1
    assert session.commits == 0

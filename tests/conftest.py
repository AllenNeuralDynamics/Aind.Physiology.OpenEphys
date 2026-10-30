"""Fail any attempted HTTP request in the saved-dataset mapper test suite."""

from unittest.mock import Mock

import pytest


@pytest.fixture(autouse=True)
def no_http(monkeypatch):
    request = Mock(side_effect=AssertionError("Dataset mapping must not contact the GUI"))
    monkeypatch.setattr("requests.sessions.Session.request", request)
    yield request
    request.assert_not_called()

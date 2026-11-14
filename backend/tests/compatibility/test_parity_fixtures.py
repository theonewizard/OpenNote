"""The committed Swift parity fixtures (tests/compatibility/parity) match the Python parsers."""

import pytest

from tests.compatibility.parity import PARITY, render

pytestmark = pytest.mark.compatibility


@pytest.mark.parametrize("name", sorted(render()))
def test_parity_fixture_is_current(name):
    expected = render()[name]
    assert (PARITY / name).read_text(encoding="utf-8") == expected, (
        f"{name} is stale: run `cd backend && ../.venv/bin/python -m tests.compatibility.parity`"
    )

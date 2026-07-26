"""Hub: imports using absolute form."""

from tests.fixtures.coupling.package_a.leaf import LeafValue


def _get_value() -> LeafValue:
    return LeafValue()

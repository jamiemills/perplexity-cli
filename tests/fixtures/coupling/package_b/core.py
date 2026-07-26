"""Core: uses relative import and function-local import."""

from .helper import NotMuch  # relative import


def _lazy_import_func():
    """Function-local import: must also be treated as coupling."""
    from tests.fixtures.coupling.package_a.leaf import LeafValue

    return LeafValue()


def public_api():
    return NotMuch()

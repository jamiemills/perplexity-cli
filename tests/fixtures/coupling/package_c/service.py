"""Service module that imports from package_a (cross-package coupling)."""

from tests.fixtures.coupling.package_a.leaf import LeafValue


class ServiceHandler:
    def handle(self, v: LeafValue) -> None:
        pass

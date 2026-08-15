class Concrete:
    """Concrete methods are not eligible for mutation exclusion."""

    value = 1

    def run(self) -> int:  # pragma: no mutate
        return self.value


class Another:
    def execute(self) -> None:  # pragma: no mutate
        pass


class Last:
    @staticmethod
    def skip() -> None:  # pragma: no mutate; owner: invalid
        pass

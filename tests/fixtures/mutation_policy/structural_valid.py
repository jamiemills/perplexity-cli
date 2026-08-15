from abc import abstractmethod
from typing import Protocol


class Reader(Protocol):
    def read(self) -> str:  # pragma: no mutate
        ...

    @abstractmethod
    def read_abstractly(self) -> str:  # pragma: no mutate
        ...


class BaseWriter:
    @abstractmethod
    def write(self) -> None:  # pragma: no mutate
        pass

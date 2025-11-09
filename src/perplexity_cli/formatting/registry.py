"""Formatter registry for managing available formatters."""

from perplexity_cli.formatting.base import Formatter


class FormatterRegistry:
    """Registry for formatter classes."""

    def __init__(self) -> None:
        """Initialize the registry."""
        self._formatters: dict[str, type[Formatter]] = {}

    def register(self, name: str, formatter_class: type[Formatter]) -> None:
        """Register a formatter.

        Args:
            name: The name to register the formatter under.
            formatter_class: The formatter class.
        """
        self._formatters[name] = formatter_class

    def get(self, name: str) -> Formatter:
        """Get a formatter instance by name.

        Args:
            name: The formatter name.

        Returns:
            An instance of the formatter.

        Raises:
            ValueError: If the formatter name is not found.
        """
        if name not in self._formatters:
            available = ", ".join(self.list())
            raise ValueError(f"Unknown formatter: {name}. Available: {available}")
        return self._formatters[name]()

    def list(self) -> list[str]:
        """List all registered formatter names.

        Returns:
            List of formatter names.
        """
        return sorted(self._formatters.keys())


# Global registry
_registry = FormatterRegistry()


def register_formatter(name: str, formatter_class: type[Formatter]) -> None:
    """Register a formatter in the global registry.

    Args:
        name: The formatter name.
        formatter_class: The formatter class.
    """
    _registry.register(name, formatter_class)


def get_formatter(name: str) -> Formatter:
    """Get a formatter from the global registry.

    Args:
        name: The formatter name.

    Returns:
        An instance of the formatter.

    Raises:
        ValueError: If the formatter is not found.
    """
    return _registry.get(name)


def list_formatters() -> list[str]:
    """List all registered formatters.

    Returns:
        List of formatter names.
    """
    return _registry.list()

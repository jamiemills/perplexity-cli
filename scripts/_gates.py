"""Read quality/gates.conf into a typed dictionary for analyser scripts.

All numeric thresholds and check toggles live in ``quality/gates.conf``,
which is locked from coding-agent edits by opencode.jsonc.  This module
provides a single function that scripts can call to read the current
values at runtime.

Usage::

    from _gates import load_gates

    gates = load_gates()
    max_flagged = gates.get_int("MAX_FLAGGED", fallback=10)

The ``Gates`` object returned by ``load_gates`` supports:

* ``gates[key]`` — raw string value (raises ``KeyError`` if missing).
* ``gates.get(key, default)`` — string with optional default.
* ``gates.get_int(key, fallback)`` — parsed integer.
* ``gates.get_float(key, fallback)`` — parsed float.
* ``gates.get_bool(key)`` — ``True`` if the value is ``"true"``
  (case-insensitive), ``False`` otherwise.

The config file is re-read on every call so that a
``--update-baseline`` refresh takes effect immediately.
"""

from __future__ import annotations

from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_GATES_PATH = _PROJECT_ROOT / "quality" / "gates.conf"


def _parse_line(raw: str) -> tuple[str, str] | None:
    """Parse a single KEY=VALUE line, skipping comments and blanks."""
    line = raw.strip()
    if not line or line.startswith("#"):
        return None
    key, sep, value = line.partition("=")
    if not sep:
        return None
    key = key.strip()
    if not key:
        return None
    return key, value.strip().strip("\"'")


def _parse_conf(path: Path) -> dict[str, str]:
    """Parse a Make-compatible KEY=VALUE file into a dict.

    Raises:
        OSError: If the gates config file cannot be read.
    """
    result: dict[str, str] = {}
    try:
        with open(path, encoding="utf-8") as fh:
            for raw in fh:
                parsed = _parse_line(raw)
                if parsed is not None:
                    result[parsed[0]] = parsed[1]
    except OSError as exc:
        raise OSError(f"Failed to read quality gates config at {path}: {exc}") from exc
    return result


class Gates:
    """Typed accessor for quality gate configuration values."""

    def __init__(self, raw: dict[str, str]) -> None:
        self._raw = raw

    def __getitem__(self, key: str) -> str:
        return self._raw[key]

    def get(self, key: str, default: str = "") -> str:
        return self._raw.get(key, default)

    def get_int(self, key: str, fallback: int = 0) -> int:
        try:
            return int(self._raw[key])
        except (KeyError, ValueError):
            return fallback

    def get_float(self, key: str, fallback: float = 0.0) -> float:
        try:
            return float(self._raw[key])
        except (KeyError, ValueError):
            return fallback

    def get_bool(self, key: str) -> bool:
        return self._raw.get(key, "").strip().lower() == "true"

    def __repr__(self) -> str:
        return f"Gates({self._raw!r})"


def load_gates(path: Path | None = None) -> Gates:
    """Load quality gates from ``quality/gates.conf``.

    Args:
        path: Optional override for the config file path.

    Returns:
        A ``Gates`` instance with typed accessors.
    """
    target = path or _GATES_PATH
    return Gates(_parse_conf(target))

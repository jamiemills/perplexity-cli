"""Application services - imports from presentation (forbidden)."""

from .cli import render


def do_work() -> str:
    return render("hello")

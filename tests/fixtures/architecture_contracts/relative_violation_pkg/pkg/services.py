"""Application services - uses relative import to violate direction."""

from .cli import render as cli_render


def do_work() -> str:
    return cli_render("hello")

"""Services with forbidden dynamic import to CLI (presentation layer)."""

import importlib


def load_cli():
    # Domain->Presentation is forbidden - dynamic import should not bypass
    mod = importlib.import_module("cli")
    return mod

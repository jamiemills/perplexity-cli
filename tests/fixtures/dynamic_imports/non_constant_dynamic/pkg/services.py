"""Services with non-constant dynamic import."""

import importlib


def load_module(module_name: str):
    # Non-constant argument - should fail even if target is allowed
    mod = importlib.import_module(module_name)
    return mod

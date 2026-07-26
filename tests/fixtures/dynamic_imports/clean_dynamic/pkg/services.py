"""Services with explicitly allowed dynamic import to models."""

import importlib


def load_model():
    mod = importlib.import_module("models")
    return mod

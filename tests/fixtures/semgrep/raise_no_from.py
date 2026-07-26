# positive: raise without from in except block
try:
    open("/tmp/nonexistent")
except OSError as exc:
    raise RuntimeError("failed")

# positive: raise without from in except block
try:
    open("/tmp/nonexistent")
except OSError:
    raise RuntimeError("failed")

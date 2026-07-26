# negative: raise with from
try:
    open("/tmp/nonexistent")
except OSError as e:
    raise RuntimeError("failed") from e

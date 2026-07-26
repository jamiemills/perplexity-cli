# positive: except-pass (silently swallows)
try:
    open("/tmp/nonexistent")
except OSError:
    pass

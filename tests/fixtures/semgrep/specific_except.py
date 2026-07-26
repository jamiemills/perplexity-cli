# negative: catching specific exception
try:
    open("/tmp/nonexistent")
except FileNotFoundError:
    pass

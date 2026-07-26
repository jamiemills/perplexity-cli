# positive: catching broad Exception without re-raising
try:
    do_something()
except Exception:
    print("error")

# negative: time.sleep inside retry module
# (path exclude for utils/retry.py makes this exempt)
import time


def backoff():
    time.sleep(1)

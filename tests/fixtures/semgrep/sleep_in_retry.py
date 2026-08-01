# negative: canonical backoff via event wait, not raw time.sleep
import threading


def backoff():
    threading.Event().wait(1)

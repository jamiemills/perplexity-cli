# positive: open(w) then os.chmod (TOCTOU)
import os


def save_data(path, data):
    open(path, "w").write(data)
    os.chmod(path, 0o600)

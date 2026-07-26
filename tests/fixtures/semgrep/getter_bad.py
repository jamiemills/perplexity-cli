# positive: getter with side effects (get_* creates state)
import os


def get_config_dir():
    os.makedirs("/tmp/config", exist_ok=True)
    return "/tmp/config"

# negative: named constant in if-condition
MAX_RETRIES = 5


def check_threshold(value):
    if value > MAX_RETRIES:
        return "high"

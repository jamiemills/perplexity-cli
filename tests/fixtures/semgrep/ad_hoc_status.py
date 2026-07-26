# positive: ad-hoc HTTP status check
def handle_response(status):
    if status == 429:
        print("rate limited")

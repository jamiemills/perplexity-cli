#!/usr/bin/env python3
"""Save authentication token from Chrome."""

from perplexity_cli.auth.oauth_handler import authenticate_sync
from perplexity_cli.auth.token_manager import TokenManager

print("Extracting authentication token from Chrome...")
token = authenticate_sync(port=9222)

print(f"Token extracted: {len(token)} characters")
print(f"Preview: {token[:50]}...")

tm = TokenManager()
tm.save_token(token)

print(f"\n✓ Token saved to: {tm.token_path}")
print(f"✓ Token exists: {tm.token_exists()}")

# Verify it can be loaded
loaded = tm.load_token()
if loaded == token:
    print("✓ Token verified: can be loaded")
else:
    print("✗ Error: saved token differs from loaded token")

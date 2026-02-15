"""Manual and semi-automated tests for authentication flow.

The interactive test (test_2_4_1) requires Chrome with remote debugging.
Run interactive tests with: pytest -m manual -s

The remaining tests (2.4.2-2.4.4) exercise token persistence, logout, and
error scenarios against real files on disc. They run automatically but
modify the token file, so they are excluded from the default test run.

Prerequisites for test_2_4_1:
1. Chrome must be running with remote debugging enabled:
   macOS: /Applications/Google Chrome.app/Contents/MacOS/Google Chrome --remote-debugging-port=9222
2. You must have a Perplexity.ai account ready to log in with.
"""

import os
import sys
import time

import pytest

from perplexity_cli.auth.oauth_handler import authenticate_sync
from perplexity_cli.auth.token_manager import TokenManager
from perplexity_cli.utils.config import get_perplexity_base_url


def print_section(title: str) -> None:
    """Print a formatted section header."""
    print(f"\n{'=' * 60}")
    print(f"  {title}")
    print(f"{'=' * 60}\n")


@pytest.mark.manual
@pytest.mark.slow
@pytest.mark.skipif(os.environ.get("CI") is not None, reason="Skipped in CI: requires real API")
def test_2_4_1_actual_perplexity_login() -> None:
    """Test 2.4.1: Manual test with actual Perplexity login.

    This test verifies that the OAuth handler can successfully connect to Chrome,
    navigate to Perplexity.ai, and extract an authentication token.

    Run with: pytest -m manual -s
    """
    if not sys.stdin.isatty():
        pytest.skip("Interactive test requires a terminal (run with pytest -m manual -s)")

    print_section("TEST 2.4.1: Actual Perplexity Login via Chrome")

    print("Prerequisites check:")
    print("1. Chrome must be running with: --remote-debugging-port=9222")
    print("2. You must have a Perplexity.ai account ready")
    print()

    response = input("Are you ready to proceed? (yes/no): ").strip().lower()
    if response != "yes":
        pytest.skip("User chose not to proceed")

    print("\nAttempting to connect to Chrome on port 9222...")
    base_url = get_perplexity_base_url()
    token = authenticate_sync(url=base_url, port=9222)

    assert token, "No token extracted"

    print(f"\nToken extracted (length: {len(token)} characters)")
    print(f"  Token preview: {token[:50]}...")


def test_2_4_2_token_persistence() -> None:
    """Test 2.4.2: Verify token persists across CLI invocations.

    This test saves a token and verifies it can be loaded by a separate
    TokenManager instance (simulating a new CLI invocation).
    """
    print_section("TEST 2.4.2: Token Persistence Across Invocations")

    tm = TokenManager()
    existing_token, _ = tm.load_token()

    if not existing_token:
        test_token = "test_token_" + str(int(time.time()))
        tm.save_token(test_token)
    else:
        test_token = existing_token

    # Simulate a new invocation by creating a new TokenManager
    tm2 = TokenManager()
    loaded_token, _ = tm2.load_token()

    assert loaded_token is not None, "Token not loaded on second invocation"
    assert loaded_token == test_token, "Loaded token differs from stored token"


def test_2_4_3_logout_functionality() -> None:
    """Test 2.4.3: Test logout functionality.

    This test verifies that clear_token() removes the stored token
    and subsequent loads return None.
    """
    print_section("TEST 2.4.3: Logout Functionality")

    tm = TokenManager()

    # Ensure we have a token
    if not tm.token_exists():
        tm.save_token("test_token_for_logout")

    assert tm.token_exists(), "Token should exist before logout"

    # Perform logout
    tm.clear_token()

    assert not tm.token_exists(), "Token still exists after logout"

    loaded_token, _ = tm.load_token()
    assert loaded_token is None, "Token should be None after logout"


def test_2_4_4_token_scenarios() -> None:
    """Test 2.4.4: Test invalid/expired token scenarios.

    This test verifies error handling for:
    - Corrupted token file
    - Insecure file permissions
    - Invalid JSON in token file
    """
    print_section("TEST 2.4.4: Invalid/Expired Token Scenarios")

    # Test 2.4.4.1: Corrupted token file
    tm = TokenManager()
    tm.save_token("valid_token")

    # Corrupt the file by writing invalid JSON
    with open(tm.token_path, "w", encoding="utf-8") as f:
        f.write("{invalid json")
    os.chmod(tm.token_path, 0o600)

    with pytest.raises(OSError):
        tm.load_token()

    # Test 2.4.4.2: Insecure file permissions
    tm.clear_token()
    tm.save_token("secure_token")
    os.chmod(tm.token_path, 0o644)

    with pytest.raises(RuntimeError):
        tm.load_token()

    # Fix permissions and verify we can load
    os.chmod(tm.token_path, 0o600)
    loaded_token, _ = tm.load_token()
    assert loaded_token == "secure_token", "Token not loaded after fixing permissions"

    # Test 2.4.4.3: Missing token handling
    tm.clear_token()
    loaded_token, _ = tm.load_token()
    assert loaded_token is None, "Expected None for missing token"

    # Should not raise error for missing token on clear
    tm.clear_token()

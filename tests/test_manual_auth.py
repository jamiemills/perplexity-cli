#!/usr/bin/env python3
"""Manual end-to-end testing script for authentication flow.

This script tests the complete authentication workflow with actual Perplexity.ai.

Prerequisites:
1. Chrome must be running with remote debugging enabled:
   macOS: /Applications/Google Chrome.app/Contents/MacOS/Google Chrome --remote-debugging-port=9222

2. You must have a Perplexity.ai account ready to log in with.

Usage:
    source .venv/bin/activate
    python test_manual_auth.py
"""

import sys
import time

from perplexity_cli.auth.oauth_handler import authenticate_sync
from perplexity_cli.auth.token_manager import TokenManager
from perplexity_cli.utils.config import get_perplexity_base_url


def print_section(title: str) -> None:
    """Print a formatted section header."""
    print(f"\n{'=' * 60}")
    print(f"  {title}")
    print(f"{'=' * 60}\n")


def test_2_4_1_actual_perplexity_login() -> bool:
    """Test 2.4.1: Manual test with actual Perplexity login.

    This test verifies that the OAuth handler can successfully connect to Chrome,
    navigate to Perplexity.ai, and extract an authentication token.
    """
    print_section("TEST 2.4.1: Actual Perplexity Login via Chrome")

    print("Prerequisites check:")
    print("1. Chrome must be running with: --remote-debugging-port=9222")
    print("2. You must have a Perplexity.ai account ready")
    print()

    response = input("Are you ready to proceed? (yes/no): ").strip().lower()
    if response != "yes":
        print("Skipping test 2.4.1")
        return False

    try:
        print("\nAttempting to connect to Chrome on port 9222...")
        base_url = get_perplexity_base_url()
        token = authenticate_sync(url=base_url, port=9222)

        if not token:
            print("✗ FAILED: No token extracted")
            return False

        print("\n✓ SUCCESS: Token extracted")
        print(f"  Token length: {len(token)} characters")
        print(f"  Token preview: {token[:50]}...")

        return True

    except RuntimeError as e:
        print(f"\n✗ FAILED: {e}")
        print("\nTroubleshooting:")
        print("- Ensure Chrome is running with --remote-debugging-port=9222")
        print("- Visit chrome://inspect in Chrome to verify remote debugging is enabled")
        print("- Check that you've logged into Perplexity.ai in the browser")
        return False
    except Exception as e:
        print(f"\n✗ FAILED: Unexpected error: {e}")
        return False


def test_2_4_2_token_persistence() -> bool:
    """Test 2.4.2: Verify token persists across CLI invocations.

    This test saves a token and verifies it can be loaded by a separate
    TokenManager instance (simulating a new CLI invocation).
    """
    print_section("TEST 2.4.2: Token Persistence Across Invocations")

    try:
        # Get the token manager
        tm = TokenManager()

        # Load existing token if available
        existing_token = tm.load_token()

        if not existing_token:
            print("No existing token found. Creating test token...")
            test_token = "test_token_" + str(int(time.time()))
            tm.save_token(test_token)
        else:
            test_token = existing_token
            print(f"Using existing token (length: {len(test_token)})")

        print(f"\nToken path: {tm.token_path}")
        print(f"Token exists: {tm.token_path.exists()}")

        # Simulate a new invocation by creating a new TokenManager
        print("\nSimulating new CLI invocation...")
        tm2 = TokenManager()
        loaded_token = tm2.load_token()

        if not loaded_token:
            print("✗ FAILED: Token not loaded on second invocation")
            return False

        if loaded_token == test_token:
            print("✓ SUCCESS: Token persists across invocations")
            print(f"  Original: {test_token[:30]}...")
            print(f"  Loaded:   {loaded_token[:30]}...")
            return True
        else:
            print("✗ FAILED: Loaded token differs from stored token")
            return False

    except Exception as e:
        print(f"✗ FAILED: {e}")
        return False


def test_2_4_3_logout_functionality() -> bool:
    """Test 2.4.3: Test logout functionality.

    This test verifies that clear_token() removes the stored token
    and subsequent loads return None.
    """
    print_section("TEST 2.4.3: Logout Functionality")

    try:
        tm = TokenManager()

        # Ensure we have a token
        if not tm.token_exists():
            print("No token exists. Creating test token...")
            tm.save_token("test_token_for_logout")

        print(f"Token exists before logout: {tm.token_exists()}")

        # Perform logout
        print("Performing logout (clear_token)...")
        tm.clear_token()

        if tm.token_exists():
            print("✗ FAILED: Token still exists after logout")
            return False

        loaded = tm.load_token()
        if loaded is not None:
            print("✗ FAILED: Token loaded after logout")
            return False

        print("✓ SUCCESS: Logout functionality works")
        print("  Token cleared successfully")
        print("  Token returns None on load")
        return True

    except Exception as e:
        print(f"✗ FAILED: {e}")
        return False


def test_2_4_4_token_scenarios() -> bool:
    """Test 2.4.4: Test invalid/expired token scenarios.

    This test verifies error handling for:
    - Corrupted token file
    - Insecure file permissions
    - Invalid JSON in token file
    """
    print_section("TEST 2.4.4: Invalid/Expired Token Scenarios")

    all_passed = True

    # Test 2.4.4.1: Corrupted token file
    print("TEST 2.4.4.1: Corrupted token file handling")
    try:
        tm = TokenManager()

        # Save a valid token first
        tm.save_token("valid_token")
        print("  ✓ Valid token saved")

        # Corrupt the file by writing invalid JSON
        with open(tm.token_path, "w") as f:
            f.write("{invalid json")
        import os

        os.chmod(tm.token_path, 0o600)

        print("  ✓ Token file corrupted")

        # Try to load - should raise OSError
        try:
            loaded = tm.load_token()
            print("  ✗ FAILED: Should have raised error for corrupted JSON")
            all_passed = False
        except OSError as e:
            print(f"  ✓ Correctly raised error: {str(e)[:50]}...")

    except Exception as e:
        print(f"  ✗ FAILED: Unexpected error: {e}")
        all_passed = False

    # Test 2.4.4.2: Insecure file permissions
    print("\nTEST 2.4.4.2: Insecure file permissions detection")
    try:
        tm = TokenManager()

        # Clear any previous state
        tm.clear_token()

        # Save a valid token
        tm.save_token("secure_token")
        print("  ✓ Valid token saved with 0600 permissions")

        # Change to insecure permissions
        import os

        os.chmod(tm.token_path, 0o644)
        print("  ✓ Changed permissions to 0644 (insecure)")

        # Try to load - should raise RuntimeError
        try:
            loaded = tm.load_token()
            print("  ✗ FAILED: Should have detected insecure permissions")
            all_passed = False
        except RuntimeError as e:
            print("  ✓ Correctly detected insecure permissions")
            print(f"    Error: {str(e)[:60]}...")

        # Fix permissions and verify we can load
        os.chmod(tm.token_path, 0o600)
        loaded = tm.load_token()
        if loaded == "secure_token":
            print("  ✓ Token loaded successfully after fixing permissions")
        else:
            print("  ✗ FAILED: Token not loaded after fixing permissions")
            all_passed = False

    except Exception as e:
        print(f"  ✗ FAILED: Unexpected error: {e}")
        all_passed = False

    # Test 2.4.4.3: Missing token handling
    print("\nTEST 2.4.4.3: Missing token handling")
    try:
        tm = TokenManager()
        tm.clear_token()

        # Should return None for missing token
        loaded = tm.load_token()
        if loaded is None:
            print("  ✓ Correctly returns None for missing token")
        else:
            print(f"  ✗ FAILED: Expected None, got {loaded}")
            all_passed = False

        # Should not raise error for missing token on clear
        tm.clear_token()
        print("  ✓ clear_token() handles missing token gracefully")

    except Exception as e:
        print(f"  ✗ FAILED: Unexpected error: {e}")
        all_passed = False

    if all_passed:
        print("\n✓ SUCCESS: All token scenario tests passed")
    else:
        print("\n✗ FAILED: Some token scenario tests failed")

    return all_passed


def main() -> None:
    """Run all manual tests."""
    print("\n" + "=" * 60)
    print("  PERPLEXITY CLI - PHASE 2.4 MANUAL TESTING")
    print("=" * 60)

    results = {}

    # Test 2.4.1: Actual Perplexity login
    results["2.4.1"] = test_2_4_1_actual_perplexity_login()

    # Test 2.4.2: Token persistence
    results["2.4.2"] = test_2_4_2_token_persistence()

    # Test 2.4.3: Logout functionality
    results["2.4.3"] = test_2_4_3_logout_functionality()

    # Test 2.4.4: Token scenarios
    results["2.4.4"] = test_2_4_4_token_scenarios()

    # Print summary
    print_section("TEST SUMMARY")
    for test_id, passed in results.items():
        status = "✓ PASSED" if passed else "✗ FAILED"
        print(f"  {test_id}: {status}")

    passed_count = sum(1 for p in results.values() if p)
    total_count = len(results)

    print(f"\nTotal: {passed_count}/{total_count} tests passed")

    if passed_count == total_count:
        print("\n✓ All manual tests passed!")
        sys.exit(0)
    else:
        print(f"\n✗ {total_count - passed_count} test(s) failed")
        sys.exit(1)


if __name__ == "__main__":
    main()

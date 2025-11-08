# Testing Guide - Perplexity CLI

Quick reference for testing the authentication system at different levels.

## Quick Test (30 seconds)

```bash
source .venv/bin/activate
python test_token_with_api.py
```

Expected output: `✓ SUCCESS: Token is valid!`

## Full Test Suite (1 minute)

```bash
source .venv/bin/activate
python -m pytest tests/ -v
```

Expected output: `31 passed`

## Step-by-Step Testing

### 1. Start Chrome with Remote Debugging

```bash
# macOS
/Applications/Google\ Chrome.app/Contents/MacOS/Google\ Chrome --remote-debugging-port=9222 &

# Linux
google-chrome --remote-debugging-port=9222 &

# Windows
"C:\Program Files\Google\Chrome\Application\chrome.exe" --remote-debugging-port=9222
```

### 2. Verify Chrome Connection

```bash
source .venv/bin/activate
python test_chrome_connection.py
```

Expected output:
```
✓ Connected to Chrome HTTP endpoint
✓ Found page target
✓ WebSocket connected!
✓ Chrome Version: Chrome/142.0.7444.61
```

### 3. Extract & Save Token

```bash
source .venv/bin/activate
python save_auth_token.py
```

Expected output:
```
✓ Token saved to: /Users/jamie.mills/.config/perplexity-cli/token.json
✓ Token exists: True
✓ Token verified: can be loaded
```

### 4. Verify Token Works with API

```bash
source .venv/bin/activate
python test_token_with_api.py
```

Expected output:
```
✓ SUCCESS: Token is valid!
Response: {
  "id": "...",
  "username": "jamiemills",
  "email": "jamie.mills@gmail.com",
  ...
}
```

### 5. Check File Permissions

```bash
ls -l ~/.config/perplexity-cli/token.json
# Should show: -rw------- (0600)

cat ~/.config/perplexity-cli/token.json
# Should show: {"token": "eyJhbGci..."}
```

## Test Coverage

```bash
source .venv/bin/activate
python -m pytest tests/ --cov=src/perplexity_cli --cov-report=term-missing
```

Current coverage:
- `token_manager.py`: 89% ✅
- Overall: 52% (includes untested async code and placeholder CLI)

## Manual API Testing

### Get User Profile

```bash
TOKEN=$(cat ~/.config/perplexity-cli/token.json | jq -r '.token')

curl -X GET 'https://www.perplexity.ai/api/user' \
  -H "Authorization: Bearer $TOKEN" \
  -H 'User-Agent: perplexity-cli/0.1.0' \
  -H 'Content-Type: application/json'
```

### Get Session Info

```bash
TOKEN=$(cat ~/.config/perplexity-cli/token.json | jq -r '.token')

curl -X GET 'https://www.perplexity.ai/api/auth/session' \
  -H "Authorization: Bearer $TOKEN" \
  -H 'User-Agent: perplexity-cli/0.1.0' \
  -H 'Content-Type: application/json'
```

### List Conversations

```bash
TOKEN=$(cat ~/.config/perplexity-cli/token.json | jq -r '.token')

curl -X GET 'https://www.perplexity.ai/api/conversations' \
  -H "Authorization: Bearer $TOKEN" \
  -H 'User-Agent: perplexity-cli/0.1.0' \
  -H 'Content-Type: application/json'
```

## Status Codes

- **200 OK**: Token is valid ✅
- **401 Unauthorized**: Token is invalid or expired ❌
- **403 Forbidden**: Token valid but access denied ❌
- **404 Not Found**: Endpoint doesn't exist (try another) ⚠️

## Troubleshooting

### Chrome Not Found

```bash
# Verify Chrome is running
curl http://localhost:9222/json

# Should return list of targets
```

### Token Not Extracted

Make sure you:
1. Have Chrome running with `--remote-debugging-port=9222`
2. Have logged into Perplexity.ai in the browser
3. Have a valid internet connection

### Permission Denied on Token File

```bash
# Fix permissions
chmod 0600 ~/.config/perplexity-cli/token.json
```

### Token Invalid/Expired

```bash
# Extract new token
python save_auth_token.py
```

## Test Files Reference

| File | Purpose | Run Time |
|------|---------|----------|
| `tests/test_auth.py` | Unit tests (22 tests) | ~0.05s |
| `tests/test_auth_integration.py` | Integration tests (9 tests) | ~0.05s |
| `test_chrome_connection.py` | Chrome DevTools verification | ~1s |
| `test_manual_auth.py` | Interactive manual tests | ~30s (interactive) |
| `save_auth_token.py` | Extract and save token | ~5s (interactive) |
| `test_token_with_api.py` | API validation | ~3s |

## Test Results Summary

### All Tests Passing ✅

- Unit tests: 22/22 ✅
- Integration tests: 9/9 ✅
- Manual tests: 4/4 ✅
- API validation: ✅ (token works)

### Security Verified ✅

- File permissions: 0600 enforced ✅
- No credential leakage: Verified ✅
- Token format: AES-256-GCM JWE ✅
- API authentication: Working ✅

### Code Quality ✅

- Ruff linting: All checks passing ✅
- Type hints: 100% coverage ✅
- Docstrings: 100% coverage ✅

## What's Tested

### Authentication (2.4.1)
- ✅ Chrome DevTools Protocol connection
- ✅ Navigation to Perplexity.ai
- ✅ Token extraction from browser session
- ✅ Token validation and format

### Token Storage (2.4.2)
- ✅ File creation and saving
- ✅ File permission enforcement (0600)
- ✅ Token retrieval and loading
- ✅ Persistence across invocations

### Token Management (2.4.3)
- ✅ Token deletion (logout)
- ✅ Idempotent operations
- ✅ Error handling

### Error Scenarios (2.4.4)
- ✅ Corrupted token file handling
- ✅ Insecure permission detection
- ✅ Missing token handling
- ✅ Error recovery

### API Compatibility
- ✅ Token valid with Perplexity API
- ✅ User profile retrieval (200 OK)
- ✅ Bearer authentication working
- ✅ Session persistence

## Next Steps

Phase 3 will build on this foundation to:
1. Create HTTP client with authentication
2. Implement Perplexity API endpoints
3. Handle query submission
4. Parse responses and extract answers
5. Implement CLI commands

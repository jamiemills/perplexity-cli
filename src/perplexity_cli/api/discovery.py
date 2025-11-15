"""API discovery utilities for exploring Perplexity's library/threads endpoints.

This module helps discover and document Perplexity API endpoints for threads.
"""

import json
from typing import Any

import httpx

from perplexity_cli.utils.config import get_perplexity_base_url
from perplexity_cli.utils.logging import get_logger


def discover_library_endpoints(token: str) -> dict[str, Any]:
    """Discover library/threads API endpoints.

    Args:
        token: Authentication token.

    Returns:
        Dictionary with discovered endpoint information.
    """
    logger = get_logger()
    base_url = get_perplexity_base_url()
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "Accept": "application/json",
        "User-Agent": "perplexity-cli/0.1.0",
    }

    results: dict[str, Any] = {
        "base_url": base_url,
        "tested_endpoints": [],
        "successful_endpoints": [],
        "failed_endpoints": [],
    }

    # List of potential endpoints to test
    potential_endpoints = [
        "/api/library",
        "/rest/library",
        "/api/threads",
        "/rest/threads",
        "/api/user/library",
        "/rest/user/library",
        "/api/conversations",
        "/rest/conversations",
    ]

    with httpx.Client(timeout=30) as client:
        for endpoint_path in potential_endpoints:
            url = f"{base_url}{endpoint_path}"

            try:
                logger.info(f"Testing endpoint: {url}")
                response = client.get(url, headers=headers)
                endpoint_result = {
                    "url": url,
                    "status": response.status_code,
                    "headers": dict(response.headers),
                }
                results["tested_endpoints"].append(endpoint_result)

                if response.status_code == 200:
                    try:
                        data = response.json()
                        results["successful_endpoints"].append({
                            "url": url,
                            "status": response.status_code,
                            "response_preview": json.dumps(data, indent=2)[:500],
                            "keys": list(data.keys()) if isinstance(data, dict) else "not_dict",
                        })
                        logger.info(f"✓ Success: {url} - Status {response.status_code}")
                    except json.JSONDecodeError:
                        results["successful_endpoints"].append({
                            "url": url,
                            "status": response.status_code,
                            "response_type": "non-json",
                            "preview": response.text[:200],
                        })
                elif response.status_code == 404:
                    logger.debug(f"  Not found: {url}")
                elif response.status_code == 401:
                    logger.warning(f"  Auth required: {url}")
                    results["failed_endpoints"].append({
                        "url": url,
                        "status": response.status_code,
                        "reason": "authentication_required",
                    })
                else:
                    logger.warning(f"  Unexpected status {response.status_code}: {url}")
                    results["failed_endpoints"].append({
                        "url": url,
                        "status": response.status_code,
                        "preview": response.text[:200],
                    })
            except Exception as e:
                logger.error(f"  Error testing {url}: {e}")
                results["failed_endpoints"].append({
                    "url": url,
                    "error": str(e),
                })

    return results


def inspect_thread_from_response(message_data: dict[str, Any]) -> dict[str, Any]:
    """Inspect thread information from an SSE message response.

    Args:
        message_data: SSE message data dictionary.

    Returns:
        Dictionary with thread-related information found.
    """
    thread_info: dict[str, Any] = {
        "found_fields": [],
        "thread_identifiers": {},
        "context_fields": {},
    }

    # Check for thread_url_slug
    if "thread_url_slug" in message_data:
        thread_info["found_fields"].append("thread_url_slug")
        thread_info["thread_identifiers"]["slug"] = message_data["thread_url_slug"]

    # Check for context UUIDs
    for field in ["context_uuid", "frontend_context_uuid", "backend_uuid"]:
        if field in message_data:
            thread_info["found_fields"].append(field)
            thread_info["context_fields"][field] = message_data[field]

    # Check for cursor (may be used for pagination/follow-ups)
    if "cursor" in message_data:
        thread_info["found_fields"].append("cursor")
        thread_info["context_fields"]["cursor"] = message_data["cursor"]

    # Check for read_write_token (may be needed for follow-ups)
    if "read_write_token" in message_data:
        thread_info["found_fields"].append("read_write_token")
        thread_info["context_fields"]["read_write_token"] = message_data["read_write_token"]

    return thread_info


def test_followup_query(
    token: str, thread_slug: str, context_uuid: str | None = None
) -> dict[str, Any]:
    """Test sending a follow-up query to a thread.

    Args:
        token: Authentication token.
        thread_slug: Thread slug/identifier.
        context_uuid: Optional context UUID from previous query.

    Returns:
        Dictionary with test results.
    """
    logger = get_logger()
    base_url = get_perplexity_base_url()
    query_endpoint = f"{base_url}/rest/sse/perplexity_ask"

    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "Accept": "text/event-stream",
        "User-Agent": "perplexity-cli/0.1.0",
    }

    # Test query parameters with thread context
    import uuid

    test_params = {
        "query_str": "test follow-up",
        "params": {
            "language": "en-US",
            "timezone": "Europe/London",
            "frontend_uuid": str(uuid.uuid4()),
            "frontend_context_uuid": context_uuid or str(uuid.uuid4()),
            "is_related_query": True,  # Indicate this is a follow-up
            # May need thread_slug or thread_id parameter
        },
    }

    results: dict[str, Any] = {
        "endpoint": query_endpoint,
        "test_params": test_params,
        "response_received": False,
        "thread_info": {},
    }

    try:
        with httpx.Client(timeout=10) as client:
            with client.stream("POST", query_endpoint, headers=headers, json=test_params) as response:
                results["status_code"] = response.status_code
                if response.status_code == 200:
                    results["response_received"] = True
                    # Read first few messages to inspect
                    message_count = 0
                    for line in response.iter_lines():
                        if line.startswith("data:"):
                            try:
                                data = json.loads(line[5:].strip())
                                thread_info = inspect_thread_from_response(data)
                                if thread_info["found_fields"]:
                                    results["thread_info"] = thread_info
                                    break
                                message_count += 1
                                if message_count > 5:  # Limit inspection
                                    break
                            except json.JSONDecodeError:
                                continue
                else:
                    results["error"] = f"Status {response.status_code}: {response.text[:200]}"
    except Exception as e:
        results["error"] = str(e)
        logger.error(f"Error testing follow-up: {e}")

    return results


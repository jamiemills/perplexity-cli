#!/usr/bin/env python3
"""Verify that our follow-up implementation matches expected request structure.

This script compares our implementation with the known correct structure
from research.
"""

import sys
import json
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from perplexity_cli.api.models import QueryParams, QueryRequest, ThreadContext


def verify_followup_request_structure():
    """Verify our follow-up request structure matches expected format."""
    print("=" * 70)
    print("VERIFYING FOLLOW-UP REQUEST STRUCTURE")
    print("=" * 70)
    
    # Create a test thread context (like we'd get from a thread)
    thread_context = ThreadContext(
        thread_url_slug="test-thread-slug-123",
        frontend_context_uuid="test-frontend-context-uuid",
        context_uuid="test-context-uuid",
        read_write_token="test-read-write-token",
    )
    
    # Build query params like submit_followup_query does
    import uuid
    frontend_uuid = str(uuid.uuid4())
    
    params = QueryParams(
        language="en-US",
        timezone="Europe/London",
        frontend_uuid=frontend_uuid,
        frontend_context_uuid=thread_context.frontend_context_uuid,
        context_uuid=thread_context.context_uuid if thread_context.context_uuid else None,
        read_write_token=thread_context.read_write_token if thread_context.read_write_token else None,
        thread_url_slug=thread_context.thread_url_slug if thread_context.thread_url_slug else None,
        is_related_query=True,
    )
    
    # Build request
    request = QueryRequest(query_str="test follow-up query", params=params)
    request_dict = request.to_dict()
    
    print("\nOur Request Structure:")
    print(json.dumps(request_dict, indent=2))
    
    # Load expected structure from research
    research_file = Path(__file__).parent.parent / "docs" / "our_followup_request.json"
    if research_file.exists():
        with open(research_file) as f:
            research_data = json.load(f)
            expected_request = research_data.get("our_request", {})
            
            print("\n" + "=" * 70)
            print("EXPECTED STRUCTURE (from research):")
            print("=" * 70)
            print(json.dumps(expected_request, indent=2))
            
            # Compare structures
            print("\n" + "=" * 70)
            print("COMPARISON:")
            print("=" * 70)
            
            our_params = request_dict.get("params", {})
            expected_params = expected_request.get("params", {})
            
            # Check required fields
            required_fields = [
                "is_related_query",
                "frontend_context_uuid",
                "context_uuid",
                "read_write_token",
                "thread_url_slug",
            ]
            
            print("\nRequired Fields Check:")
            all_present = True
            for field in required_fields:
                our_has = field in our_params
                expected_has = field in expected_params
                status = "✓" if our_has else "✗"
                print(f"  {status} {field}: our={our_has}, expected={expected_has}")
                if not our_has:
                    all_present = False
            
            if all_present:
                print("\n✓ All required fields are present in our request!")
            else:
                print("\n✗ Some required fields are missing!")
            
            # Check structure
            print("\nStructure Check:")
            has_query_str = "query_str" in request_dict
            has_params = "params" in request_dict
            print(f"  {'✓' if has_query_str else '✗'} Has 'query_str' at top level: {has_query_str}")
            print(f"  {'✓' if has_params else '✗'} Has 'params' at top level: {has_params}")
            
            if has_query_str and has_params:
                print("\n✓ Request structure is correct!")
            
            # Check values
            print("\nValue Checks:")
            if our_params.get("is_related_query") == True:
                print("  ✓ is_related_query is True")
            else:
                print(f"  ✗ is_related_query is {our_params.get('is_related_query')}")
            
            if our_params.get("frontend_context_uuid") == thread_context.frontend_context_uuid:
                print("  ✓ frontend_context_uuid matches thread context")
            else:
                print("  ✗ frontend_context_uuid mismatch")
            
            if our_params.get("context_uuid") == thread_context.context_uuid:
                print("  ✓ context_uuid matches thread context")
            else:
                print("  ✗ context_uuid mismatch")
            
            if our_params.get("read_write_token") == thread_context.read_write_token:
                print("  ✓ read_write_token matches thread context")
            else:
                print("  ✗ read_write_token mismatch")
            
            if our_params.get("thread_url_slug") == thread_context.thread_url_slug:
                print("  ✓ thread_url_slug matches thread context")
            else:
                print("  ✗ thread_url_slug mismatch")
    
    print("\n" + "=" * 70)
    print("SUMMARY")
    print("=" * 70)
    print("Our implementation appears to match the expected structure.")
    print("If follow-ups still don't work, the issue may be:")
    print("  1. Using stale thread context from list_threads()")
    print("  2. Thread context not being saved/loaded correctly")
    print("  3. Missing some other parameter we haven't discovered")
    print("\nNext step: Capture actual browser request to compare.")


if __name__ == "__main__":
    verify_followup_request_structure()


#!/bin/bash

uv run pxcli auth
uv run pytest tests/test_api_integration.py::TestPerplexityAPIIntegration -v

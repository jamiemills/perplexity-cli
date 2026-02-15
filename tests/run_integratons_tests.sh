#!/bin/bash

source .venv/bin/activate
pxcli auth
uv run pytest tests/test_api_integration.py::TestPerplexityAPIIntegration -v

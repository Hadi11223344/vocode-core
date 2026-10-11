.PHONY: chat speak listen lint lint_diff test test-fast setup-check help

chat:
	poetry run python playground/streaming/agent/chat.py

transcribe:
	poetry run python playground/streaming/transcriber/transcribe.py

synthesize:
	poetry run python playground/streaming/synthesizer/synthesize.py

turn_based_conversation:
	poetry run python quickstarts/turn_based_conversation.py

streaming_conversation:
	poetry run python quickstarts/streaming_conversation.py

PYTHON_FILES=.
lint: PYTHON_FILES=vocode/ quickstarts/ playground/
lint_diff typecheck_diff: PYTHON_FILES=$(shell git diff --name-only --diff-filter=d main | grep -E '\.py$$')

lint lint_diff:
	poetry run black $(PYTHON_FILES)

typecheck:
	poetry run mypy -p vocode
	poetry run mypy -p quickstarts
	poetry run mypy -p playground

typecheck_diff:
	poetry run mypy $(PYTHON_FILES)

test:
	poetry run pytest

# Prefer Poetry, then a working .venv, then python3 -m pytest.
# Note: a stale .venv may point at a deleted path — only use it if python runs.
PYTEST ?= $(shell \
	if command -v poetry >/dev/null 2>&1; then echo "poetry run pytest"; \
	elif [ -x .venv/bin/python ] && .venv/bin/python -c "import pytest" >/dev/null 2>&1; then echo ".venv/bin/python -m pytest"; \
	else echo "python3 -m pytest"; fi)

# Fast contributor suite: graph contracts, slots, compiler/executor core.
# Keep this under ~2 minutes; do not add heavyweight integration suites here.
test-fast:
	$(PYTEST) -q \
		tests/voice_platform/test_graph_contracts.py \
		tests/voice_platform/test_slots.py \
		tests/voice_platform/test_langgraph_flow_executor.py \
		tests/voice_platform/test_action_optional_inputs.py \
		tests/voice_platform/test_quickwin_routing_truth.py \
		tests/voice_platform/test_playground_mock_context.py \
		tests/voice_platform/test_call109_anti_repeat.py \
		tests/voice_platform/test_security_bootstrap.py

setup-check:
	python3 scripts/check_setup.py

help:
	@echo "Usage: make <target>"
	@echo ""
	@echo "Targets:"
	@echo "  chat         Run chat agent"
	@echo "  transcribe   Transcribe audio to text"
	@echo "  synthesize   Synthesize text into audio"
	@echo "  lint         Lint all Python files"
	@echo "  lint_diff    Lint changed Python files"
	@echo "  test         Run full pytest suite"
	@echo "  test-fast    Graph/slots/routing unit tests (contributor default)"
	@echo "  setup-check  Validate Tier 0/1 local env"
	@echo "  help         Show this help message"


COUNTRY ?= Korea

.PHONY: download build serve test

download:
	uv run python -m persona_mcp_store.cli download $(COUNTRY)

build:
	uv run python -m persona_mcp_store.cli build $(COUNTRY)

serve:
	uv run python -m persona_mcp_store.cli serve

test:
	uv run pytest tests/ -v

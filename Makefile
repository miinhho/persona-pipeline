COUNTRY ?= Korea

.PHONY: download classify build serve test

download:
	uv run python -m persona_mcp_store.cli download $(COUNTRY)

classify:
	uv run python -m persona_mcp_store.cli classify-occupation $(COUNTRY)

build:
	uv run python -m persona_mcp_store.cli build $(COUNTRY)

serve:
	uv run python -m persona_mcp_store.cli serve

test:
	uv run pytest tests/ -v

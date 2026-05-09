COUNTRY ?= Korea

.PHONY: download classify build serve test

download:
	uv run python -m persona_pipeline.cli download $(COUNTRY)

classify:
	uv run python -m persona_pipeline.cli classify-occupation $(COUNTRY)

build:
	uv run python -m persona_pipeline.cli build $(COUNTRY)

serve:
	uv run python -m persona_pipeline.cli serve

test:
	uv run pytest tests/ -v

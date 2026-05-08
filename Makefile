SHELL := /bin/bash
PY := python -m persona_pipeline.cli

COUNTRIES := USA Japan India Singapore Brazil France Korea
COUNTRY ?= Korea

DATA := data
RAW := $(DATA)/raw/$(COUNTRY)/personas.parquet
CACHE := $(DATA)/cache/$(COUNTRY)
ARCHETYPES := $(DATA)/archetypes/cards_$(COUNTRY).parquet

.PHONY: help download build archetype match test clean clean-country build-all archetype-all

help:
	@echo "Targets (use COUNTRY=<name>, default Korea):"
	@echo "  download         — download HF Nemotron-Personas-{COUNTRY}"
	@echo "  build            — enrich → partition (tiny cache)"
	@echo "  archetype        — archetype cards from partition cache + raw"
	@echo "  match Q='...'    — natural-language match"
	@echo "  build-all        — sequential build for all countries"
	@echo "  archetype-all    — sequential archetype for all countries"
	@echo "  test             — pytest"
	@echo "  clean            — remove data/cache, data/archetypes"
	@echo "  clean-country    — remove COUNTRY's cache + archetype"
	@echo "Available countries: $(COUNTRIES)"

download: $(RAW)
$(RAW):
	$(PY) download $(COUNTRY)

$(CACHE)/01_enriched.parquet: $(RAW)
	$(PY) stage-enrich $(COUNTRY)

$(CACHE)/02_partitioned.parquet: $(CACHE)/01_enriched.parquet
	$(PY) stage-partition $(COUNTRY)

build: $(CACHE)/02_partitioned.parquet
	@echo "build[$(COUNTRY)] done"

archetype: $(ARCHETYPES)
$(ARCHETYPES): $(CACHE)/02_partitioned.parquet
	$(PY) stage-archetype $(COUNTRY)

match:
	@test -n "$(Q)" || (echo "Usage: make match COUNTRY=Korea Q='your query'" && exit 1)
	$(PY) match $(COUNTRY) "$(Q)"

build-all:
	@for c in $(COUNTRIES); do $(MAKE) --no-print-directory build COUNTRY=$$c || exit 1; done

archetype-all:
	@for c in $(COUNTRIES); do $(MAKE) --no-print-directory archetype COUNTRY=$$c || exit 1; done

test:
	pytest -v

clean:
	rm -rf $(DATA)/cache $(DATA)/archetypes

clean-country:
	rm -rf $(CACHE) $(ARCHETYPES)

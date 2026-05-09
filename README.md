# persona-pipeline

Multi-country raw-persona MCP server over Nemotron-Personas (USA / Japan / India / Singapore / Brazil / France / Korea, ~1M personas each). LLM clients query the server to fetch raw personas filtered by demographic axes.

## Quick start

```bash
make download COUNTRY=Korea           # HF Nemotron-Personas-Korea
make classify COUNTRY=Korea           # Anthropic Batches: occupation → group lookup
make build COUNTRY=Korea              # write data/store/Korea.parquet
make serve                            # run MCP server (stdio)
```

`make build COUNTRY=Korea` requires `data/occupation_lookup/Korea.parquet`, which `classify` produces (committed to git as a versioned asset). Native-category countries (Singapore/Brazil/France) skip `classify`.

## Pipeline

```
raw (HF dataset, gitignore)
  ↓ classify-occupation   Anthropic Batches → (occupation, occupation_group) lookup parquet (git-tracked)
  ↓ build                 enrich raw with axes (region, age_gen, occupation_group) + sort
data/store/{country}.parquet  + {country}.catalog.json (sidecar)
                                (gitignore, deterministic from raw + lookup + code)
  ↓ serve
MCP server (stdio) exposes:
  Tools (actions):
  • sample_personas(country, n, region?, age_gen?, sex?, occupation_group?, seed?)
  • search_personas(country, query, top_k, axes filters?)
  • persona_distribution(country, group_by, axes filters?)
  • get_persona(country, uuid)
  Resources (catalog discovery):
  • personas://catalog                  → list of built countries
  • personas://catalog/{country}        → axes with value counts + schema
```

LLM clients (Claude Desktop / Claude Code / external) connect to the MCP server, sample raw personas, and use them as system-prompt material in their own simulation/analysis flows. We do not host simulation.

## Country mappings

`persona_pipeline/mappings/{korea,japan,...}.py` — per-country rules in a `CountryMappings` dataclass:
- `axes`: which demographic axes the store carries (Singapore has no region → 3 axes)
- `region_source_col` + `region_map`: native administrative division → regional grouping
- `occupation_group_definitions`: label → description fed to the classifier (Korea/Japan/USA/India). Singapore/Brazil/France use the dataset's native category column.

## Layout

```
persona_pipeline/
├── _config.py              constants (ROW_GROUP_SIZE)
├── mappings/               per-country rules + axis name constants
├── stages/
│   ├── enrich.py           raw → store-shaped LazyFrame
│   └── classify_occupation.py  Anthropic Batches occupation classifier
├── store.py                load / sample / distribution / get / search helpers
├── mcp_server.py           FastMCP server: 4 tools + 2 catalog resources
├── io.py                   atomic parquet write + HF download
└── cli/                    Typer commands

tests/                      pytest
docs/superpowers/           specs / plans
```

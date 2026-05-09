# persona-mcp-store

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

## Remote deployment

For team-internal or remote LLM clients, run the server over streamable-http:

```bash
export PERSONA_STORE_API_KEYS="$(openssl rand -hex 32)"
uv run persona-mcp-store serve-http --host 0.0.0.0 --port 8080
```

Connect from an MCP-aware client by registering:

```json
{
  "mcpServers": {
    "persona-store": {
      "type": "streamable-http",
      "url": "https://persona-store.example.com",
      "headers": {"Authorization": "Bearer <your-key>"}
    }
  }
}
```

### Configuration (env vars)

| Variable | Default | Required | Purpose |
|---|---|---|---|
| `PERSONA_STORE_API_KEYS` | — | yes | Comma-separated bearer tokens. Server refuses to start if unset/empty. |
| `PERSONA_STORE_DATA_DIR` | `data/store` | no | Parquet store + catalog sidecar directory. Container default `/data`. |
| `PERSONA_STORE_RATE_LIMIT` | `60` | no | Requests per minute per token (rolling 60-second window). |

### Container

```bash
docker compose up -d
```

The provided `docker-compose.yml` mounts `./data/store` read-only into the container at `/data` and binds port 8080 to `127.0.0.1` (i.e. localhost only — front with a reverse proxy for external access).

### TLS / production access

The container speaks plain HTTP. Production deployments terminate TLS at a reverse proxy (nginx, Caddy, cloud LB):

```nginx
server {
  listen 443 ssl;
  server_name persona-store.team.example.com;
  ssl_certificate /etc/letsencrypt/live/.../fullchain.pem;
  ssl_certificate_key /etc/letsencrypt/live/.../privkey.pem;

  location / {
    proxy_pass http://127.0.0.1:8080;
    proxy_set_header Host $host;
    proxy_set_header X-Forwarded-Proto https;
    proxy_read_timeout 60s;
  }

  location /health { access_log off; proxy_pass http://127.0.0.1:8080; }
}
```

### Operations

- **Logs**: each request emits one JSON line to stderr with `request_id`, `token_id` (key prefix), `path`, `status`, `elapsed_ms`. Wire stderr into your log shipper (Loki, ELK, Cloud Logging).
- **Health**: `GET /health` returns `{"status":"ok","stores":[...]}` without auth. Use as liveness probe.
- **Key rotation**: edit env var (e.g. `PERSONA_STORE_API_KEYS=new1,new2`) and restart the container. Old tokens become invalid immediately; new ones accepted.
- **Rate limit**: per-token rolling 60s window. 429 response includes `Retry-After` header.
- **Scaling**: rate limit and request-id buckets are in-memory (single-instance). Multi-instance horizontal scaling requires distributed state (Redis) — out of v1 scope.

## Country mappings

`persona_mcp_store/mappings/{korea,japan,...}.py` — per-country rules in a `CountryMappings` dataclass:
- `axes`: which demographic axes the store carries (Singapore has no region → 3 axes)
- `region_source_col` + `region_map`: native administrative division → regional grouping
- `occupation_group_definitions`: label → description fed to the classifier (Korea/Japan/USA/India). Singapore/Brazil/France use the dataset's native category column.

## Layout

```
persona_mcp_store/
├── _config.py              constants (ROW_GROUP_SIZE)
├── mappings/               per-country rules + axis name constants
├── stages/
│   ├── enrich.py           raw → store-shaped LazyFrame
│   └── classify_occupation.py  Anthropic Batches occupation classifier
├── store.py                load / sample / distribution / get / search helpers
├── mcp_server.py           FastMCP server: 4 tools + 2 catalog resources
├── remote.py               streamable-http app: auth + rate limit + JSON logs + /health
├── io.py                   atomic parquet write + HF download
└── cli/                    Typer commands (download, build, serve, serve-http, …)

tests/                      pytest
docs/superpowers/           specs / plans
```

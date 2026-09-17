# Langfuse observability

DSA can export nested analysis traces to a self-hosted Langfuse 3.x instance. The integration is disabled by default and is best effort: configuration, SDK, network, or exporter failures never fail an analysis task.

## Start Langfuse locally

Use the upstream self-hosted Docker Compose bundle so its Postgres, ClickHouse, Redis, and object-storage versions stay aligned with the selected Langfuse release:

```bash
git clone https://github.com/langfuse/langfuse.git
cd langfuse
git checkout v3
docker compose up -d
docker compose ps
```

Open `http://localhost:3000`, create a project, and copy its public and secret keys into the DSA `.env`. Never commit real keys.

```dotenv
LANGFUSE_ENABLED=true
LANGFUSE_BASE_URL=http://localhost:3000
LANGFUSE_PUBLIC_KEY=pk-lf-...
LANGFUSE_SECRET_KEY=sk-lf-...
LANGFUSE_RELEASE=local-dev
```

Restart DSA, run one single-stock analysis, then verify one trace contains nested `pipeline.stock_analysis`, `agent.run`, `agent.llm.generation`, `tool.*`, `search.stock_news`, `rag.comprehensive_intel`, and fallback observations for the paths that executed. Generation observations expose model/provider, token usage, cost when LiteLLM supplies it, latency, status, and error type. Retry/cache fields are exported only when their structured values are available.

## Privacy and operations

Telemetry metadata is deny-by-default with a small scalar allowlist. Prompt/response bodies, tool arguments/results, stock codes, portfolio data, API keys, raw user/session IDs, and environment contents are not exported. Error details contain only the exception class.

To roll back immediately, set `LANGFUSE_ENABLED=false` and restart DSA; no code or data migration is required. For exporter trouble, inspect DSA warning counts and Langfuse ingestion health while analysis success/error rates remain the primary service signal.

This integration does not change API, Web, or desktop contracts. Production URLs, credentials, retention, access controls, and deployment are an operator-owned follow-up.

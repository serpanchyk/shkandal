# LLM Provider Boundary

Shkandal uses LangChain inside each LLM task for prompt composition and simple chains, but keeps job orchestration, retries, validation, persistence, and database mutation in `worker-ml`. All runtime model traffic goes through a LiteLLM proxy under `infra/litellm`, using logical per-stage model aliases so provider routing, throttling, and fallback policy can change without leaking provider details into domain code.

# Design: Phase 3 — Model Routing (P3-3) + Typed Tool Calling (P3-2)

Status: approved (2026-07-03). Decisions recorded below. Build order: **P3-3 first,
then P3-2**, as two separate PRs.

## Resolved decisions

- **Q1 — Research agent: augment, not replace.** Keep the deterministic
  `MarketContextBuilder` as the reliable base context; add a tool-calling research
  node that does *targeted follow-up* and merges a brief into the context. Preserves
  determinism/cost/auditability while still demonstrating the tool-calling stack.
- **Q2 — Fallback provider: OpenAI-only for now.** Primary + fallback are both
  OpenAI models (e.g. `gpt-4o-mini` primary, a second model as fallback). The
  provider interface is provider-agnostic, so Anthropic/Ollama slot in later as a
  ~1-file add once a key/runtime is available.
- **Q3 — Two PRs.** P3-3 (routing/provider/fallback) first; P3-2 (tools) on top.

---

## Part A — P3-3: Provider abstraction, routing, fallback

**Seam.** Today every call goes `LLMGateway._call → _request_with_backoff →
self._client.chat.completions.create`, with a single module-level `OpenAI()` and
`_model_for_tier` mapping `strong`/`cheap` → model name. P3-3 puts a provider
interface + routing table behind that seam.

**Provider interface** (`src/llm/providers/`):
```python
class LLMProvider(Protocol):
    name: str
    def chat(self, *, model, messages, temperature, response_format=None,
             tools=None, max_tokens=None) -> ProviderResponse: ...

@dataclass
class ProviderResponse:
    content: str | None
    tool_calls: list           # normalized; empty when none (used by P3-2)
    prompt_tokens: int
    completion_tokens: int
    raw: Any
```
`OpenAIProvider` wraps `chat.completions.create` and normalizes the response;
catches `openai.APIError` and re-raises `ProviderError` so the gateway's retry loop
is provider-agnostic. Ship only `OpenAIProvider` now.

**Routing** — a route is (provider, model) per tier:
```
LLM_STRONG_PROVIDER / LLM_CHEAP_PROVIDER = "openai"
LLM_STRONG_MODEL / LLM_CHEAP_MODEL       (existing)
LLM_FALLBACK_PROVIDER / LLM_FALLBACK_MODEL   (optional; empty = no fallback)
```
`resolve_route(tier) -> Route(provider, model)`; `resolve_fallback() -> Route|None`.
`validate_config()` checks providers are supported and models non-empty.

**Fallback** — after exhausting retries on the primary route, if a fallback route is
configured, try it once (own small retry budget); only raise `LLMError` if the
fallback also fails. Each call records `provider` and `served_by` / `fell_back` in
the cost log and Langfuse metadata. Default (no fallback configured) preserves exact
current behavior, so existing gateway tests are unchanged.

**Cost** — keep `_MODEL_PRICING` keyed by model; add the fallback model's price.
Cost-drop-vs-all-strong is measurable via the run-cost summary once `strong` is set
to a pricier model than `cheap`; documented, not forced (defaults stay `gpt-4o-mini`
both tiers so scheduled-run cost doesn't change silently).

**Tests (no API):** provider normalizes a fake SDK response; routing tier→(provider,
model); config rejects unknown provider; fallback path (primary fails → fallback
serves; both fail → `LLMError`) via injected fake providers.

**Effort:** small–medium (a refactor behind the provider seam + config).

---

## Part B — P3-2: Typed tool calling for research

**Tool abstraction** (`src/llm/tools.py`): a `Tool` with name, description, Pydantic
`input_schema`, and a `handler(BaseModel) -> result`; a `ToolRegistry` that renders
the `tools=[...]` param, validates args (invalid → structured error the model can
retry, not an exception), dispatches, and serializes results.

**Five tools** (thin wrappers over existing clients, injected — no globals):
`get_price`, `get_history` (summarized returns), `search_news`, `retrieve_memory`,
`get_portfolio`.

**Gateway loop**: `complete_with_tools(messages, registry, *, tier, schema=None,
max_rounds=4, prompt_version)` — call provider with `tools`; while the response has
tool calls, execute them, append `role:"tool"` results, repeat; stop on a final
answer or `max_rounds`. Returns the final output plus the ordered tool-call list
(name, args, result-summary, ms). Guards: hard round cap, per-tool try/except,
temperature 0.

**Placement (augment)**: keep `MarketContextBuilder`; add a `research` graph node
before `decide_trades` running a tool-calling `ResearchAnalyst` that does targeted
follow-up and emits a `research_brief` merged into the context.

**Tracing**: the brief + its tool calls are stored on the decision (journal) and
rendered on `decisions.html` as a "Research trace"; each tool call is a Langfuse
child span under the research node.

**Tests (no API):** registry (valid → runs; invalid args → structured error/retry);
each tool wrapper with a fake client; the loop with a scripted fake provider
(request tool → result → final answer; `max_rounds` enforced; tool-call list
returned). Optional eval scorer: research node emits ≥1 recorded tool call.

**Effort:** medium–high; depends on P3-3's provider seam.

## Out of scope (deferred)
Fine-tuning/DPO, a hand-rolled agent framework, tools inside the analysts (keep them
prompt-only), parallel tool execution, and non-OpenAI providers (fast follow).

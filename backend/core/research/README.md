# DDG Hybrid Deep Research Orchestrator

Second research mode for the `/api/research` endpoint. Sits alongside the
existing OpenAI o3/o4 deep research path without replacing it.

## Why this exists

`o3-deep-research` and `o4-mini-deep-research` delegate the entire research
loop (decomposition, searching, synthesis) to the OpenAI model. That's
high-quality but slow — a single query can take 3–10 minutes because the
model internally chains dozens of web_search calls.

This orchestrator makes the loop explicit and runs pieces in parallel:

```
planner (GPT-4o-mini, 1 call)
    ↓ structured plan with 5–8 subquestions × 3–5 search queries each
dual search (DuckDuckGo + OpenAI Responses web_search, all queries in parallel)
    ↓
normalize → dedupe (canonical URL + title signature)
    ↓
evaluator (GPT-4o-mini, 1 call per subquestion, in parallel)
    ↓ scores each result on relevance/authority/freshness/density
follow-up queries (if evaluator flagged gaps, 1 extra round)
    ↓
synthesizer (GPT-4o-mini, 1 call)
    ↓
final markdown report with footnoted sources
```

Typical end-to-end time is 30–90 seconds vs. 3–10 minutes for o3.

## Module layout

```
core/research/
├── orchestrator.py           # Top-level run_orchestrated_research()
├── planner.py                # plan_research() → ResearchPlan
├── normalize.py              # canonical_url, classify_source_type, normalize_results
├── dedupe.py                 # dedupe_results() — URL + title signature
├── evaluator.py              # evaluate_subquestion() → EvaluationReport
├── followup_query_generator.py  # generate_followup_queries()
├── synthesizer.py            # synthesize_report() → markdown
├── prompts/
│   ├── planner_prompt.py
│   ├── evaluator_prompt.py
│   └── synthesizer_prompt.py
└── search/
    ├── base.py               # NormalizedResult + SearchProvider Protocol + search_with_fallback
    └── providers/
        ├── ddg.py            # DuckDuckGo (duckduckgo_search library)
        └── openai_web.py     # OpenAI Responses API + web_search_preview tool
```

## Common normalized result schema

```python
@dataclass
class NormalizedResult:
    subquestion_id: str          # "SQ1", "SQ2", ...
    provider: str                # "ddg" | "openai_web"
    query: str                   # the exact query that produced this hit
    title: str
    url: str                     # canonicalized by normalize.canonical_url
    snippet: str
    published_at: str | None     # YYYY-MM-DD or None (unreliable across providers)
    source_type: str             # gov | company | media | retailer | research | blog | unknown
    raw: dict                    # provider's original payload
```

## How to trigger it

### From the API

```http
POST /api/research/start
{
  "query": "인도 라면 시장 2025 진출 전략",
  "model": "ddg-hybrid-research",
  "api_key": "sk-..."
}
```

Returns:
```json
{
  "session_id": "abc123",
  "response_id": "orchestrator:abc123",
  "status": "queued"
}
```

Then subscribe to the SSE stream:
```
GET /api/research/stream/orchestrator/{session_id}
```

SSE event types (same shape as the o3/o4 endpoint for frontend reuse):
- `status` — orchestrator phase (`planning` / `searching` / `normalizing` / `evaluating` / `synthesizing` / `completed`)
- `planning_done` — full ResearchPlan JSON
- `search_step` — one query completed
- `followup` — follow-up round started
- `completed` — final report + sources + search_steps
- `failed` — orchestrator crashed

### From code

```python
from openai import AsyncOpenAI
from core.research.orchestrator import run_orchestrated_research

client = AsyncOpenAI(api_key="sk-...")

async def _log(event_type, payload):
    print(event_type, payload)

result = await run_orchestrated_research(
    client,
    "인도 라면 시장 2025 진출 전략",
    progress_callback=_log,
)
print(result.report)          # final markdown
print(len(result.sources))    # validated sources
print(result.plan.to_dict())  # the plan that was generated
```

## Configuration (environment variables)

| Variable | Default | Effect |
|---|---|---|
| `RESEARCH_OPENAI_WEB_SEARCH` | `1` | Set to `0` to disable the OpenAI web_search provider → DDG-only mode |
| `RESEARCH_PLANNER_MODEL` | `gpt-4o-mini` | GPT model used by the planner |
| `RESEARCH_EVALUATOR_MODEL` | `gpt-4o-mini` | GPT model used by the evaluator |
| `RESEARCH_FOLLOWUP_MODEL` | `gpt-4o-mini` | GPT model used by the follow-up query generator |
| `RESEARCH_SYNTHESIZER_MODEL` | `gpt-4o-mini` | GPT model used by the synthesizer |
| `RESEARCH_OPENAI_WEB_MODEL` | `gpt-4o-mini` | GPT model used by the openai_web provider wrapper |

## Tests

```bash
cd backend
.miro/Scripts/python.exe tests/research/test_normalize.py         # 16/16
.miro/Scripts/python.exe tests/research/test_dedupe.py            # 9/9
.miro/Scripts/python.exe tests/research/test_provider_fallback.py # 7/7
.miro/Scripts/python.exe tests/research/test_evaluator_contract.py # 13/13
```

All tests are standalone (no pytest required); each file has a `__main__`
harness that runs via `inspect`.

## Operator notes

- **Cost**: Typical run = 1 planner call + N evaluator calls (N = subquestions,
  usually 5-8) + 1 synthesizer call + 1 openai_web provider call per query
  (15-40 queries total). On `gpt-4o-mini` this is usually under $0.10 per
  research request.
- **Rate limits**: DDG has informal rate limits. If you run many concurrent
  research sessions, DDG may start returning empty results — the orchestrator
  will still proceed with whatever the openai_web provider returned.
- **Fallback**: If `openai_web` fails (timeout, bad JSON, API error) the
  orchestrator silently continues with DDG-only results. If DDG also fails
  the evaluator will flag the subquestion and the follow-up round will try
  different queries.
- **Graceful degradation**: If a single subquestion yields zero results the
  synthesizer is told "no validated sources for SQx" and writes a caveat in
  that section of the report — never fabricates content.
- **Session persistence**: Each run writes to `data/research/{session_id}.json`
  incrementally (status updates on every phase). Frontend can poll
  `GET /api/research/sessions/{id}` or subscribe to the SSE stream.

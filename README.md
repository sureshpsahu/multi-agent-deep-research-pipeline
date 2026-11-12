# Multi-Agent Deep Research & Telemetry Pipeline

An orchestrated multi-agent research pipeline built with **Claude** and **Python** that decomposes complex business questions into parallel web-search and URL-browsing tasks, extracts high-signal text passages, and synthesizes executive reports with full cost and quota telemetry.

## System Architecture

```text
                        +--------------------+

                        |   User Research    |
                        |      Prompt        |
                        +---------+----------+
                                  |
                                  v
                        +--------------------+

                        |   Planner Agent    | (Decomposes into 3-5 sub-queries)
                        +---------+----------+
                                  |
             +--------------------+--------------------+
             v                    v                    v
   +------------------+ +------------------+ +------------------+

   | Search/Browse #1 | | Search/Browse #2 | | Search/Browse #3 | (Parallel Workers +
   +--------+---------+ +--------+---------+ +--------+---------+  429 Rate Limiter)

             |                    |                    |
             +--------------------+--------------------+
                                  |
                                  v
                        +--------------------+

                        | Passage Extractor  | (Strips HTML boilerplate;
                        |  & Deduplicator    |  cuts input tokens by 42%)
                        +---------+----------+
                                  |
                                  v
                        +--------------------+

                        | Synthesizer Agent  | (Generates cited brief +
                        +--------------------+  telemetry_scorecard.json)
```

### Architectural Tradeoffs Evaluated
1. **Passage Extraction vs. Raw HTML Ingestion:** Feeding full scraped web pages into Claude inflated context windows to ~18,000 tokens per query and degraded synthesis focus. Implementing a lightweight passage-ranking filter before synthesis **reduced input token consumption by 42%** while preserving citation accuracy.
2. **Parallel Fan-Out vs. API Quota Throttling:** Spawning 5 concurrent search/browse workers frequently triggered `HTTP 429 Too Many Requests` errors on standard API tiers. Added a token-bucket rate limiter and exponential backoff in `telemetry.py` to guarantee graceful degradation under burst loads.

## Quickstart

1. **Clone and install dependencies:**
   ```bash
   git clone https://github.com
   cd multi-agent-deep-research-pipeline
   pip install -r requirements.txt
   ```

2. **Configure environment variables (`.env`):**
   ```env
   ANTHROPIC_API_KEY=your_claude_key
   GROUNDING_PROVIDER=tavily
   SEARCH_API_KEY=your_search_key
   MAX_PARALLEL_WORKERS=3
   PASSAGE_EXTRACTION_MODE=true
   ```

3. **Run a multi-agent research query:**
   ```bash
   python main.py --topic "Enterprise AI grounding adoption and API monetization models"
   ```

## Benchmark Results (Raw HTML vs. Passage Extraction Mode)

| Metric | Raw Page Ingestion | Passage-Filtered Pipeline | Impact |
| :--- | :--- | :--- | :--- |
| **Avg Input Tokens / Report** | 18,450 | 10,620 | **-42.4% token reduction** |
| **Estimated Cost / Report** | $0.064 | $0.039 | **-39.1% cost savings** |
| **P95 End-to-End Latency** | 9.8 s | 6.1 s | **37.7% faster synthesis** |
| **HTTP 429 Recovery Rate** | 60% (crashed) | 100% (auto-retry) | Zero dropped research runs |

## Recommended Platform & SDK Improvements
Based on telemetry collected during parallel agent execution, enterprise grounding APIs should expose:
1. **Native `passage_mode` flags** on browse endpoints so agents receive ranked text chunks rather than raw DOM payloads.
2. **Batch sub-query endpoints** to let Planner agents submit 3–5 related queries in a single authenticated call, reducing network overhead and rate-limit contention.
3. **Standardized `Retry-After` and quota-remaining headers** so client SDKs can dynamically throttle parallel worker pools before hitting `429` errors.

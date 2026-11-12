"""
Developer Experience (DevEx) & API Metering Telemetry Wrapper.

This module instruments AI agent tool calls and LLM inference requests to benchmark:
1. Time-to-First-Successful-Call (TTFSC) for developer onboarding visibility.
2. P50 and P95 retrieval/inference latencies to track tail-latency bottlenecks.
3. HTTP 429 rate-limit quota throttling and exponential backoff recovery.
4. Per-query token consumption, USD cost estimation, and passage-extraction savings.
"""

import time
import json
import math
from dataclasses import dataclass, field, asdict
from typing import Callable, Any, Dict, List

# Reference token pricing constants (USD per 1M tokens) for cost estimation
INPUT_COST_PER_1M = 3.00
OUTPUT_COST_PER_1M = 15.00


@dataclass
class CallMetric:
    """Stores telemetry data for a single API or MCP tool execution."""
    step_name: str
    latency_ms: float
    status_code: int
    retries: int
    input_tokens: int = 0
    output_tokens: int = 0
    raw_chars: int = 0
    extracted_chars: int = 0


@dataclass
class DevExTelemetryTracker:
    """
    Middleware tracker that wraps external API/MCP calls and aggregates
    end-to-end performance, reliability, and token economics into a scorecard.
    """
    session_start: float = field(default_factory=time.perf_counter)
    first_success_ms: float = None
    calls: List[CallMetric] = field(default_factory=list)

    def execute_with_telemetry(
        self,
        step_name: str,
        fn: Callable[..., Any],
        max_retries: int = 3,
        *args,
        **kwargs
    ) -> Any:
        """
        Executes a target function while recording latency, token usage,
        and handling HTTP 429 quota throttling with exponential backoff.

        Args:
            step_name: Label identifying the agent step (e.g., 'web_search', 'planner').
            fn: The callable function executing the API or MCP tool request.
            max_retries: Maximum retry attempts when encountering HTTP 429 rate limits.
            *args: Positional arguments forwarded to `fn`.
            **kwargs: Keyword arguments forwarded to `fn`.

        Returns:
            The raw response returned by `fn`.
        """
        retries = 0
        backoff = 1.0  # Initial backoff delay in seconds

        while True:
            t0 = time.perf_counter()
            try:
                response = fn(*args, **kwargs)
                latency_ms = (time.perf_counter() - t0) * 1000

                # Record Time-to-First-Successful-Call (TTFSC) on the initial 200 OK response
                if self.first_success_ms is None:
                    self.first_success_ms = (time.perf_counter() - self.session_start) * 1000

                # Extract token usage from Anthropic/LLM response objects if available
                in_tok = getattr(getattr(response, "usage", None), "input_tokens", 0)
                out_tok = getattr(getattr(response, "usage", None), "output_tokens", 0)

                # Extract character counts from search/browse dicts to measure passage filtering
                raw_len = response.get("raw_chars", 0) if isinstance(response, dict) else 0
                ext_len = response.get("extracted_chars", 0) if isinstance(response, dict) else 0

                self.calls.append(
                    CallMetric(
                        step_name=step_name,
                        latency_ms=round(latency_ms, 2),
                        status_code=200,
                        retries=retries,
                        input_tokens=in_tok,
                        output_tokens=out_tok,
                        raw_chars=raw_len,
                        extracted_chars=ext_len,
                    )
                )
                return response

            except Exception as e:
                latency_ms = (time.perf_counter() - t0) * 1000
                status = getattr(e, "status_code", 500)

                # Retry with exponential backoff when hitting API rate limits (HTTP 429)
                if status == 429 and retries < max_retries:
                    retries += 1
                    time.sleep(backoff)
                    backoff *= 2
                    continue

                # Log terminal failure before re-raising the exception
                self.calls.append(
                    CallMetric(
                        step_name=step_name,
                        latency_ms=round(latency_ms, 2),
                        status_code=status,
                        retries=retries,
                    )
                )
                raise

    def generate_scorecard(self) -> Dict[str, Any]:
        """
        Computes summary DevEx and operational health metrics across all recorded calls.

        Returns:
            Dictionary containing TTFSC, P50/P95 latencies, retry counts, token spend,
            and passage-extraction token savings percentage.
        """
        # Filter successful calls to compute P50 (median) and P95 (tail) latency
        latencies = sorted(c.latency_ms for c in self.calls if c.status_code == 200)
        p50 = latencies[len(latencies) // 2] if latencies else 0.0
        p95_idx = max(0, math.ceil(0.95 * len(latencies)) - 1)
        p95 = latencies[p95_idx] if latencies else 0.0

        # Aggregate token counts and calculate estimated USD cost
        total_in = sum(c.input_tokens for c in self.calls)
        total_out = sum(c.output_tokens for c in self.calls)
        total_cost = (
            (total_in / 1_000_000 * INPUT_COST_PER_1M)
            + (total_out / 1_000_000 * OUTPUT_COST_PER_1M)
        )

        # Count total HTTP 429 rate-limit retries triggered across parallel/sequential steps
        throttled_count = sum(c.retries for c in self.calls)

        # Calculate inbound payload reduction achieved via passage extraction
        raw_total = sum(c.raw_chars for c in self.calls)
        ext_total = sum(c.extracted_chars for c in self.calls)
        reduction_pct = (
            round((1 - (ext_total / raw_total)) * 100, 1) if raw_total > 0 else 0.0
        )

        return {
            "time_to_first_successful_call_ms": round(self.first_success_ms or 0.0, 2),
            "total_calls": len(self.calls),
            "p50_latency_ms": p50,
            "p95_latency_ms": p95,
            "http_429_retries": throttled_count,
            "total_input_tokens": total_in,
            "total_output_tokens": total_out,
            "estimated_query_cost_usd": round(total_cost, 5),
            "passage_token_reduction_pct": reduction_pct,
        }

    def export_report(self, filepath: str = "telemetry_scorecard.json") -> None:
        """
        Writes the aggregated DevEx scorecard and step-by-step call trace to a JSON file.

        Args:
            filepath: Output path for the JSON telemetry report.
        """
        report = {
            "summary": self.generate_scorecard(),
            "call_trace": [asdict(c) for c in self.calls],
        }
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(report, f, indent=2)

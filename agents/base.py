"""
Base agent infrastructure for the portfolio analyzer pipeline.

Provides:
  NodeContract  — input/output schema per agent
  BaseAgent     — abstract base with budget check, input validation,
                  retry-with-backoff, per-node output evaluation
  Shared helpers — _j, _slim_*, _cost, _remaining, _budget_ok, init_llms
"""

import json
import random
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field

import anthropic
from langchain_anthropic import ChatAnthropic
from langchain_core.prompts import ChatPromptTemplate

from run_config import RunConfig

# ------------------------------------------------------------------ #
# LLM instances (module-level singletons, initialised once per run)   #
# ------------------------------------------------------------------ #

_llm_analysis: ChatAnthropic | None = None   # max_tokens=1024 — deep analysis
_llm_summary:  ChatAnthropic | None = None   # max_tokens=512  — summaries/meta


def init_llms(api_key: str) -> None:
    global _llm_analysis, _llm_summary
    _llm_analysis = ChatAnthropic(model="claude-sonnet-4-6", api_key=api_key, max_tokens=1024)
    _llm_summary  = ChatAnthropic(model="claude-sonnet-4-6", api_key=api_key, max_tokens=512)


def get_llm(tier: str = "analysis") -> ChatAnthropic:
    llm = _llm_analysis if tier == "analysis" else _llm_summary
    if llm is None:
        raise RuntimeError("LLMs not initialised — call init_llms(api_key) first")
    return llm

# ------------------------------------------------------------------ #
# Token / cost helpers                                                 #
# ------------------------------------------------------------------ #

_INPUT_CPT  = 3.00  / 1_000_000   # $ per input token  (claude-sonnet-4-6)
_OUTPUT_CPT = 15.00 / 1_000_000   # $ per output token

# Minimum cost estimate per node (used for budget floor checks)
NODE_MIN_COST: dict[str, float] = {
    "fundamental":    0.012,
    "technical":      0.010,
    "dcf":            0.008,
    "sentiment":      0.008,
    "hot_stocks":     0.010,
    "portfolio":      0.008,
    "macro_risk":     0.008,
    "alerts":         0.006,
    "comparative":    0.008,
    "trend":          0.007,
    "cost_agent":     0.000,   # no LLM call
    "market_opinion": 0.006,
    "final_summary":  0.005,
    "evaluator":      0.000,   # no LLM call
}

# Priority order for parallel nodes (lower = higher priority = less likely to be trimmed)
NODE_PRIORITY: dict[str, int] = {
    "fundamental": 1,
    "technical":   2,
    "dcf":         3,
    "sentiment":   4,
    "portfolio":   5,
    "macro_risk":  6,
    "alerts":      7,
    "comparative": 8,
    "hot_stocks":  9,
    "trend":       10,
}


def token_cost(in_tok: int, out_tok: int) -> float:
    return in_tok * _INPUT_CPT + out_tok * _OUTPUT_CPT


def spent(state) -> float:
    return token_cost(state["input_tokens"], state["output_tokens"])


def remaining(state) -> float:
    cfg: RunConfig = state["run_config"]
    return cfg.total_usd - spent(state)


def budget_ok(state, node_name: str = "") -> bool:
    cfg: RunConfig = state["run_config"]
    needed = NODE_MIN_COST.get(node_name, 0.008) + cfg.reserve_usd
    return remaining(state) >= needed

# ------------------------------------------------------------------ #
# Data helpers                                                         #
# ------------------------------------------------------------------ #

def compact_json(data, limit: int = 2500) -> str:
    """Compact JSON string, truncated to limit chars."""
    s = json.dumps(data, separators=(",", ":"), default=str)
    return s[:limit] + "…[truncated]" if len(s) > limit else s


def slim_holdings(holdings: dict) -> dict:
    keep = ("shares", "avg_buy_price", "equity")
    return {t: {k: v for k, v in h.items() if k in keep} for t, h in holdings.items()}


def slim_insider(insider: dict) -> dict:
    return {t: recs[:3] for t, recs in insider.items()}


def slim_news(news: dict) -> dict:
    return {t: [n.get("title", "") for n in items[:3]] for t, items in news.items()}

# ------------------------------------------------------------------ #
# Retry-with-backoff for transient failures                            #
# ------------------------------------------------------------------ #

class NodeExecutionError(Exception):
    """Raised when a node fails after all retries."""
    pass


def invoke_with_retry(
    system: str,
    human: str,
    inputs: dict,
    llm: ChatAnthropic,
    max_retries: int = 3,
    base_delay: float = 1.0,
) -> tuple[str, int, int]:
    """
    Call LLM with exponential backoff for transient failures.

    Handles:
      - APIConnectionError / APITimeoutError — network issues (retry w/ backoff)
      - RateLimitError                       — too many requests (wait 60s)
      - APIStatusError 5xx                   — server errors (retry w/ backoff)
      - Other exceptions                     — re-raise immediately

    Returns (text, input_tokens, output_tokens).
    """
    prompt = ChatPromptTemplate.from_messages([("system", system), ("human", human)])
    chain  = prompt | llm

    last_exc: Exception | None = None
    for attempt in range(max_retries):
        try:
            msg   = chain.invoke(inputs)
            usage = getattr(msg, "usage_metadata", None) or {}
            return (
                msg.content,
                usage.get("input_tokens", 0),
                usage.get("output_tokens", 0),
            )

        except (anthropic.APIConnectionError, anthropic.APITimeoutError) as e:
            last_exc = e
            delay = base_delay * (2 ** attempt) + random.uniform(0, 0.5)
            print(f"    [retry] Network error ({e.__class__.__name__}) — retrying in {delay:.1f}s "
                  f"(attempt {attempt + 1}/{max_retries})")
            time.sleep(delay)

        except anthropic.RateLimitError as e:
            last_exc = e
            delay = 60.0
            print(f"    [retry] Rate limit hit — waiting {delay:.0f}s "
                  f"(attempt {attempt + 1}/{max_retries})")
            time.sleep(delay)

        except anthropic.APIStatusError as e:
            last_exc = e
            if e.status_code in (500, 502, 503, 529) and attempt < max_retries - 1:
                delay = base_delay * (2 ** attempt)
                print(f"    [retry] API error {e.status_code} — retrying in {delay:.1f}s "
                      f"(attempt {attempt + 1}/{max_retries})")
                time.sleep(delay)
            else:
                raise NodeExecutionError(
                    f"API error {e.status_code} after {attempt + 1} attempt(s): {e}"
                ) from e

    raise NodeExecutionError(
        f"Failed after {max_retries} retries: {last_exc}"
    ) from last_exc

# ------------------------------------------------------------------ #
# Node contract — input/output schema                                  #
# ------------------------------------------------------------------ #

@dataclass
class NodeContract:
    """
    Declarative schema for a node's expected inputs and outputs.

    required_snapshot_keys:    snapshot dict keys that must be non-empty dicts/lists.
    required_output_phrases:   at least one of these (case-insensitive) must appear in output.
    min_output_length:         output must be at least this many non-whitespace characters.
    """
    required_snapshot_keys:   list[str] = field(default_factory=list)
    required_output_phrases:  list[str] = field(default_factory=list)
    min_output_length:        int       = 80

    def validate_inputs(self, state) -> tuple[bool, str]:
        """Returns (ok, error_message)."""
        snap = state.get("snapshot") or {}
        for key in self.required_snapshot_keys:
            val = snap.get(key)
            if not val:
                return False, f"required snapshot key '{key}' is missing or empty"
        return True, ""

    def validate_output(self, text: str) -> tuple[bool, str]:
        """Returns (ok, reason_if_failed)."""
        if not text or len(text.strip()) < self.min_output_length:
            return False, f"output too short ({len(text.strip())} < {self.min_output_length} chars)"
        lowered = text.lower()
        bad = ("i cannot", "i don't have access", "no data available",
               "as an ai", "i'm unable to", "[skipped")
        for phrase in bad:
            if phrase in lowered:
                return False, f"output appears to be an error/refusal: '{phrase}'"
        if self.required_output_phrases:
            if not any(p.lower() in lowered for p in self.required_output_phrases):
                return False, f"missing required phrase(s): {self.required_output_phrases}"
        return True, ""

# ------------------------------------------------------------------ #
# Base agent                                                           #
# ------------------------------------------------------------------ #

class BaseAgent(ABC):
    """
    Abstract base for all analysis agents.

    Subclasses must define:
      name              str            — node name in the LangGraph graph
      contract          NodeContract   — input/output schema
      system_prompt     str (property) — LLM system message
      human_prompt      str (property) — LLM human message template
      build_prompt_inputs(state) -> dict

    Optional overrides:
      llm_tier          str            — "analysis" (default) or "summary"
    """

    name:     str
    contract: NodeContract
    llm_tier: str = "analysis"

    @property
    @abstractmethod
    def system_prompt(self) -> str: ...

    @property
    @abstractmethod
    def human_prompt(self) -> str: ...

    @abstractmethod
    def build_prompt_inputs(self, state) -> dict: ...

    # -- public call (LangGraph node function) -----------------------

    def __call__(self, state) -> dict:
        label = f"[{self.name}]"

        # 1. Budget check
        if not budget_ok(state, self.name):
            r = remaining(state)
            print(f"  {label} SKIPPED — only ${r:.4f} remaining")
            return {"stopped_early": True}

        # 2. Input validation
        ok, err = self.contract.validate_inputs(state)
        if not ok:
            print(f"  {label} SKIPPED — {err}")
            return {self.name: f"[skipped — {err}]", "input_tokens": 0, "output_tokens": 0}

        # 3. Execute with per-node evaluation + one quality retry
        result = self._execute_with_eval(state, label)
        r_after = remaining(state) - token_cost(result.get("input_tokens", 0), result.get("output_tokens", 0))
        print(f"  {label} done  "
              f"${token_cost(result.get('input_tokens',0), result.get('output_tokens',0)):.4f}  "
              f"~${r_after:.4f} remaining")
        return result

    def _execute_with_eval(self, state, label: str) -> dict:
        """Run LLM call, evaluate output quality, retry once if needed."""
        cfg: RunConfig = state["run_config"]

        def _call() -> tuple[str, int, int]:
            return invoke_with_retry(
                self.system_prompt,
                self.human_prompt,
                self.build_prompt_inputs(state),
                llm=get_llm(self.llm_tier),
            )

        try:
            text, it, ot = _call()
        except NodeExecutionError as e:
            print(f"  {label} FAILED — {e}")
            return {self.name: f"[failed — {e}]", "input_tokens": 0, "output_tokens": 0, "stopped_early": True}

        # Per-node quality evaluation
        if cfg.evaluate_nodes:
            ok, reason = self.contract.validate_output(text)
            if not ok:
                print(f"  {label} quality LOW — {reason}")
                if budget_ok(state, self.name):
                    print(f"  {label} retrying...")
                    try:
                        text2, it2, ot2 = _call()
                        # Log retry result quality but don't retry again
                        ok2, reason2 = self.contract.validate_output(text2)
                        status = "OK" if ok2 else f"still LOW ({reason2})"
                        print(f"  {label}/retry quality {status}")
                        text, it, ot = text2, it + it2, ot + ot2
                    except NodeExecutionError as e:
                        print(f"  {label}/retry FAILED — {e}")
                else:
                    print(f"  {label} no budget for retry, keeping output as-is")
            else:
                print(f"  {label} quality OK")

        return {self.name: text, "input_tokens": it, "output_tokens": ot}

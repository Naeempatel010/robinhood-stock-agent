"""
LangGraph-orchestrated Claude analysis pipeline.

Graph topology (parallel fan-out → sequential):

  START
  ├── fundamental  ┐
  ├── technical    │
  ├── dcf          ├─ (parallel threads) ──► market_opinion ──► final_summary ──► evaluator
  ├── sentiment    │                                                                  │    │
  └── hot_stocks   ┘                                                               retry  END

Budget: $5.00 total, stop if < $0.50 remaining.
Token reducers (Annotated[int, add]) correctly sum parallel node updates.
"""

import json
from operator import add
from typing import Annotated, TypedDict

import yfinance as yf
from langchain_anthropic import ChatAnthropic
from langchain_core.prompts import ChatPromptTemplate
from langgraph.graph import END, START, StateGraph

from config import HOT_TICKERS, load_credentials

# ------------------------------------------------------------------ #
# LLM (two tiers for token efficiency)                                #
# ------------------------------------------------------------------ #

_llm_analysis = None
_llm_summary  = None


def _init_llms(api_key: str) -> None:
    global _llm_analysis, _llm_summary
    _llm_analysis = ChatAnthropic(model="claude-sonnet-4-6", api_key=api_key, max_tokens=1024)
    _llm_summary  = ChatAnthropic(model="claude-sonnet-4-6", api_key=api_key, max_tokens=512)

# ------------------------------------------------------------------ #
# Token budget                                                        #
# ------------------------------------------------------------------ #

TOTAL_BUDGET = 5.00   # dollars per run
RESERVE      = 0.50   # stop before this runs out

_INPUT_CPT  = 3.00  / 1_000_000   # $ per input token  (claude-sonnet-4-6)
_OUTPUT_CPT = 15.00 / 1_000_000   # $ per output token

def _cost(in_tok: int, out_tok: int) -> float:
    return in_tok * _INPUT_CPT + out_tok * _OUTPUT_CPT

def _remaining(state) -> float:
    return TOTAL_BUDGET - _cost(state["input_tokens"], state["output_tokens"])

def _budget_ok(state) -> bool:
    return _remaining(state) > RESERVE

# ------------------------------------------------------------------ #
# Token-tracked invoke                                                #
# ------------------------------------------------------------------ #

def _invoke(system: str, human: str, inputs: dict, llm=None) -> tuple:
    """Call LLM, return (text, input_tokens, output_tokens)."""
    if llm is None:
        llm = _llm_analysis
    prompt = ChatPromptTemplate.from_messages([("system", system), ("human", human)])
    msg = (prompt | llm).invoke(inputs)
    usage = getattr(msg, "usage_metadata", None) or {}
    return msg.content, usage.get("input_tokens", 0), usage.get("output_tokens", 0)

# ------------------------------------------------------------------ #
# Token-efficient data helpers                                        #
# ------------------------------------------------------------------ #

def _j(data, limit: int = 2500) -> str:
    """Compact JSON, capped at limit chars to control input tokens."""
    s = json.dumps(data, separators=(",", ":"), default=str)
    return s[:limit] + "…[truncated]" if len(s) > limit else s

def _slim_holdings(holdings: dict) -> dict:
    keep = ("shares", "avg_buy_price", "equity")
    return {t: {k: v for k, v in h.items() if k in keep} for t, h in holdings.items()}

def _slim_insider(insider: dict) -> dict:
    return {t: recs[:3] for t, recs in insider.items()}

def _slim_news(news: dict) -> dict:
    return {t: [n.get("title", "") for n in items[:3]] for t, items in news.items()}

# ------------------------------------------------------------------ #
# Graph state                                                         #
# ------------------------------------------------------------------ #

class AnalysisState(TypedDict):
    snapshot:            dict
    historical_comparison: dict
    # Results — empty string = not computed / skipped
    fundamental:   str
    technical:     str
    dcf:           str
    sentiment:     str
    market_opinion: str
    hot_stocks:    str
    final_summary: str
    # Token counts — `add` reducer correctly sums parallel node updates
    input_tokens:  Annotated[int, add]
    output_tokens: Annotated[int, add]
    # Control
    retry_count:   int   # 0=not retried, 1=retry pending, 2=done
    stopped_early: bool

# ------------------------------------------------------------------ #
# Node helpers                                                        #
# ------------------------------------------------------------------ #

def _skip(label: str, state) -> dict:
    print(f"  {label} SKIPPED — budget ${_remaining(state):.3f} remaining")
    return {"stopped_early": True}

def _log(label: str, it: int, ot: int, state) -> None:
    spent = _cost(it, ot)
    remaining = _remaining(state) - spent   # approximate (parallel nodes don't see each other's costs yet)
    print(f"  {label} done  ${spent:.3f} this call  ~${remaining:.3f} remaining")

# ------------------------------------------------------------------ #
# Parallel nodes (fan-out from START)                                 #
# ------------------------------------------------------------------ #

def fundamental_node(state: AnalysisState) -> dict:
    if not _budget_ok(state):
        return _skip("[a] fundamental", state)

    s = state["snapshot"]
    text, it, ot = _invoke(
        "You are a professional financial analyst. Be concise.",
        "Holdings:{holdings}\nFundamentals:{fundamental}\nShort interest:{short_interest}\nInsider:{insider}\n\n"
        "For each stock: valuation + financial health, short interest signal, insider signal. "
        "Verdict: Strong/Neutral/Weak. One paragraph per stock.",
        {
            "holdings":       _j(_slim_holdings(s["portfolio_summary"]["holdings"])),
            "fundamental":    _j(s["fundamental_data"]),
            "short_interest": _j(s["short_interest_data"]),
            "insider":        _j(_slim_insider(s["insider_data"])),
        },
    )
    _log("[a] fundamental", it, ot, state)
    return {"fundamental": text, "input_tokens": it, "output_tokens": ot}


def technical_node(state: AnalysisState) -> dict:
    if not _budget_ok(state):
        return _skip("[b] technical", state)

    s = state["snapshot"]
    cd = s.get("correlation_data", {})
    text, it, ot = _invoke(
        "You are an expert technical analyst. Be concise.",
        "Technical:{technical}\nCorrelation:{correlation}\n\n"
        "For each stock: trend, RSI, MACD, BB, SMA crossovers (1-2 lines each). "
        "Then: top correlated pairs, diversification score {div}/10, one rebalancing suggestion.",
        {
            "technical":   _j(s["technical_data"]),
            "correlation": _j(cd),
            "div":         cd.get("diversification_score", "N/A"),
        },
    )
    _log("[b] technical", it, ot, state)
    return {"technical": text, "input_tokens": it, "output_tokens": ot}


def dcf_node(state: AnalysisState) -> dict:
    if not _budget_ok(state):
        return _skip("[c] DCF", state)

    s = state["snapshot"]
    text, it, ot = _invoke(
        "You are a value investor. Be concise.",
        "DCF results (10% discount, 3% terminal, 5yr):{dcf}\nHoldings:{holdings}\n\n"
        "For each stock: over/undervalued, margin of safety, caveats, position sizing impact. "
        "One line per stock.",
        {
            "dcf":      _j(s["dcf_results"]),
            "holdings": _j(_slim_holdings(s["portfolio_summary"]["holdings"])),
        },
    )
    _log("[c] DCF", it, ot, state)
    return {"dcf": text, "input_tokens": it, "output_tokens": ot}


def sentiment_node(state: AnalysisState) -> dict:
    if not _budget_ok(state):
        return _skip("[d] sentiment", state)

    s = state["snapshot"]
    text, it, ot = _invoke(
        "You are a market sentiment analyst. Be concise.",
        "Stock news:{stock_news}\nMarket news:{market_news}\n\n"
        "Rate each stock Bullish/Neutral/Bearish (one sentence). Overall market sentiment.",
        {
            "stock_news":  _j(_slim_news(s["news_data"])),
            "market_news": _j([n.get("title", "") for n in s.get("market_news", [])[:5]]),
        },
    )
    _log("[d] sentiment", it, ot, state)
    return {"sentiment": text, "input_tokens": it, "output_tokens": ot}


def hot_stocks_node(state: AnalysisState) -> dict:
    if not _budget_ok(state):
        return _skip("[e] hot stocks", state)

    current = list(state["snapshot"]["portfolio_summary"]["holdings"].keys())
    hot_data = {}
    for ticker in HOT_TICKERS:
        if ticker in current:
            continue
        try:
            info = yf.Ticker(ticker).info
            hot_data[ticker] = {
                "price":      info.get("currentPrice"),
                "pe":         info.get("trailingPE"),
                "fwd_pe":     info.get("forwardPE"),
                "rev_growth": info.get("revenueGrowth"),
                "analyst":    info.get("recommendationKey"),
                "target":     info.get("targetMeanPrice"),
            }
        except Exception:
            pass

    text, it, ot = _invoke(
        "You are a growth stock analyst. Be concise.",
        "Current portfolio:{current}\nHot stocks:{hot}\n\nTop 3 buy candidates: ticker, entry price, one-line thesis.",
        {"current": ", ".join(current), "hot": _j(hot_data)},
    )
    _log("[e] hot stocks", it, ot, state)
    return {"hot_stocks": text, "input_tokens": it, "output_tokens": ot}


# ------------------------------------------------------------------ #
# Sequential nodes                                                    #
# ------------------------------------------------------------------ #

def market_opinion_node(state: AnalysisState) -> dict:
    if not _budget_ok(state):
        return _skip("[f] market opinion", state)

    if not any([state.get("fundamental"), state.get("technical"), state.get("sentiment")]):
        return {"market_opinion": "Insufficient upstream data."}

    text, it, ot = _invoke(
        "You are a senior portfolio manager. Be concise.",
        "Fundamental:{f}\nTechnical:{t}\nSentiment:{s}\n\n"
        "1-3 month outlook in 3 bullet points: macro, key risk, direction.",
        {
            "f": (state.get("fundamental") or "N/A")[:800],
            "t": (state.get("technical")   or "N/A")[:800],
            "s": (state.get("sentiment")   or "N/A")[:400],
        },
        llm=_llm_summary,
    )
    _log("[f] market opinion", it, ot, state)
    return {"market_opinion": text, "input_tokens": it, "output_tokens": ot}


def final_summary_node(state: AnalysisState) -> dict:
    if not _budget_ok(state):
        return _skip("[g] final summary", state)

    ps = state["snapshot"]["portfolio_summary"]
    hc = state["historical_comparison"]
    is_retry = state["retry_count"] == 1
    retry_note = "\n\nPrevious attempt was missing sections. You MUST include all 5 numbered sections." if is_retry else ""

    text, it, ot = _invoke(
        "You are a senior portfolio advisor. Under 200 words total.",
        "Portfolio:{portfolio}\nHistory:{history}\n"
        "Fundamental:{f}\nTechnical:{t}\nDCF:{d}\nSentiment:{s}\nOpinion:{o}\nHot:{h}\n\n"
        "Exactly 5 sections (one line each):\n"
        "1. RISK RATING: X/10 — reason\n"
        "2. PORTFOLIO RATING: X/10 — reason\n"
        "3. REBALANCING: action or None needed\n"
        "4. SELL NOW: ticker + reason, or None\n"
        "5. BUY NOW: up to 3 — ticker, price, one-line thesis"
        "{retry_note}",
        {
            "portfolio":  _j({**_slim_holdings(ps["holdings"]), "equity": ps["equity"], "cash": ps["cash"]}),
            "history":    _j(hc) if hc else "First run",
            "f":          (state.get("fundamental")    or "N/A")[:600],
            "t":          (state.get("technical")      or "N/A")[:600],
            "d":          (state.get("dcf")            or "N/A")[:400],
            "s":          (state.get("sentiment")      or "N/A")[:400],
            "o":          (state.get("market_opinion") or "N/A")[:400],
            "h":          (state.get("hot_stocks")     or "N/A")[:400],
            "retry_note": retry_note,
        },
        llm=_llm_summary,
    )
    _log("[g] final summary", it, ot, state)
    return {"final_summary": text, "input_tokens": it, "output_tokens": ot}


# ------------------------------------------------------------------ #
# Evaluator (quality gate — no LLM call, structural check only)      #
# ------------------------------------------------------------------ #

_REQUIRED_SECTIONS = ["RISK RATING", "PORTFOLIO RATING", "REBALANCING", "SELL NOW", "BUY NOW"]


def evaluator_node(state: AnalysisState) -> dict:
    """
    EvaluatorOptimizer pattern from mcp-agent:
    checks final_summary quality and triggers one retry if sections are missing.
    retry_count: 0=first eval, 1=retry pending → final_summary reruns, 2=done
    """
    summary = (state.get("final_summary") or "").upper()
    missing  = [s for s in _REQUIRED_SECTIONS if s not in summary]

    if state["retry_count"] == 0 and missing and _budget_ok(state):
        print(f"  [quality] Missing: {missing} — retrying final summary once")
        return {"retry_count": 1}

    if missing:
        print(f"  [quality] Missing: {missing} (no retry — budget or already retried)")
    else:
        print(f"  [quality] All 5 sections present")
    return {"retry_count": 2}   # signal: done evaluating


def _route_evaluator(state: AnalysisState) -> str:
    return "retry" if state["retry_count"] == 1 else "done"


# ------------------------------------------------------------------ #
# Graph construction                                                  #
# ------------------------------------------------------------------ #

def _build_graph():
    b = StateGraph(AnalysisState)

    # Nodes
    for name, fn in [
        ("fundamental",    fundamental_node),
        ("technical",      technical_node),
        ("dcf",            dcf_node),
        ("sentiment",      sentiment_node),
        ("hot_stocks",     hot_stocks_node),
        ("market_opinion", market_opinion_node),
        ("final_summary",  final_summary_node),
        ("evaluator",      evaluator_node),
    ]:
        b.add_node(name, fn)

    # Parallel fan-out from START
    for n in ["fundamental", "technical", "dcf", "sentiment", "hot_stocks"]:
        b.add_edge(START, n)

    # Fan-in barrier: all parallel nodes → market_opinion
    for n in ["fundamental", "technical", "dcf", "sentiment", "hot_stocks"]:
        b.add_edge(n, "market_opinion")

    # Sequential chain
    b.add_edge("market_opinion", "final_summary")
    b.add_edge("final_summary",  "evaluator")

    # Conditional: retry final_summary once or end
    b.add_conditional_edges("evaluator", _route_evaluator, {"retry": "final_summary", "done": END})

    return b.compile()


_graph = _build_graph()


# ------------------------------------------------------------------ #
# Public interface (backward-compatible with analyze.py)             #
# ------------------------------------------------------------------ #

def run_all(snapshot: dict, historical_comparison: dict, api_key: str = None) -> dict:
    """
    Orchestrate all analysis steps via LangGraph.
    - Independent steps (fundamental, technical, dcf, sentiment, hot_stocks) run in parallel.
    - market_opinion and final_summary run sequentially after.
    - Evaluator retries final_summary once if required sections are missing.
    - Each node checks budget; stops early if < $0.50 remaining.
    Returns dict of analysis strings (empty string = skipped).
    """
    if api_key:
        _init_llms(api_key)
    elif _llm_analysis is None:
        _, _, default_key = load_credentials()
        _init_llms(default_key)

    initial: AnalysisState = {
        "snapshot":             snapshot,
        "historical_comparison": historical_comparison,
        "fundamental":   "",
        "technical":     "",
        "dcf":           "",
        "sentiment":     "",
        "market_opinion": "",
        "hot_stocks":    "",
        "final_summary": "",
        "input_tokens":  0,
        "output_tokens": 0,
        "retry_count":   0,
        "stopped_early": False,
    }

    final = _graph.invoke(initial)

    total_cost = _cost(final["input_tokens"], final["output_tokens"])
    print(f"\n  Budget summary: ${total_cost:.4f} spent of ${TOTAL_BUDGET:.2f}  "
          f"(${TOTAL_BUDGET - total_cost:.4f} remaining)")
    print(f"  Tokens: {final['input_tokens']:,} input / {final['output_tokens']:,} output")
    if final.get("stopped_early"):
        print("  *** One or more steps SKIPPED due to budget limit — partial results returned ***")

    return {
        "fundamental":   final["fundamental"],
        "technical":     final["technical"],
        "dcf":           final["dcf"],
        "sentiment":     final["sentiment"],
        "market_opinion": final["market_opinion"],
        "hot_stocks":    final["hot_stocks"],
        "final_summary": final["final_summary"],
    }

# 01 · Product Vision
**Summary:** A personal, production-grade quant research and portfolio platform for NSE equities that turns investing from ad-hoc decisions into a disciplined, evidence-gated process. **Purpose:** anchor all other documents. **Scope:** vision-level only. **Assumptions:** single operator; Indian tax residency. **Risks:** vision drift toward feature accumulation. **Open questions:** none at this level. **Future extensions:** agent interface layer (ADR-015).

## Mission
Make one investor's capital decisions systematic, explainable, tax-aware, and honest about
uncertainty — at a total operating cost under ₹1,000/month and under 2 hours/week of upkeep.

## Vision
A platform that could plausibly live inside a small quant firm: owned bias-free data,
one deterministic engine driving both research and live proposals, every decision logged
and reproducible — scaled to one person, one box, and free official data sources.

## Problem statement
Retail investment decisions in India are dominated by emotion, tips, and tools that are
either survivorship-biased, look-ahead-contaminated, or opaque. Institutional-quality
research infrastructure is not purchasable at retail cost ceilings. Without owned PIT data
and honest cost/tax modeling, every backtest-driven decision rests on fiction.

## Success metrics
1. **Process:** ≥ 95% of executed trades originate from logged, explained proposals; every override reason-coded.
2. **Data:** index-reconstruction correlation ≥ 0.999; zero unexplained data-quality failures per quarter.
3. **Ops:** ≤ 2 hrs/week steady-state; feed death detected < 24h; restore drill ≤ 4h.
4. **Investment (honest):** champion book beats better of Nifty 50 / Midcap 150 TRI net of all costs and taxes over rolling 3y — or the system says so and recommends indexing (the no-go path is a success mode, not a failure).
5. **Judgment:** override-alpha report answers, with data, whether the human adds value.

## Guiding principles
Data before models · rules before ML · geometric growth under a drawdown budget ·
reproducibility by rebuild · loud failure over silent staleness · every component pays
for its maintenance · the human gate is architectural · the platform must be prepared
to conclude "index instead."

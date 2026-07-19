"""The doc-16 golden scenario, adjustment slice: 3 stocks x 8 quarters, hand-computed.

Every expected value below was computed BY HAND from doc 21 §1 before any code ran; they are
sacred — never update an expected value to make a run pass without written justification
(doc 16). P1-03 extends this same scenario with tax lots (LTCG/STCG boundary, exemption).

Quarter dates: the 15th of Jan/Apr/Jul/Oct 2024 and 2025 (Q1..Q8).

ALPHA (INE000GOLDA1) — the full factor chain:
  raw closes:   Q1 100.00  Q2 110.00  Q3 22.50  Q4 24.00  Q5 25.50  Q6 13.20  Q7 14.10  Q8 4.80
  actions:      split 10→2 ex 2024-06-01 (f=1/5) · dividend ₹5 ex 2024-09-01 (NO price effect)
                · bonus 1:1 ex 2025-02-01 (f=1/2) · SAME-DAY bonus 1:2 (2/3) + split 2→1 (1/2)
                ex 2025-08-01 (f=1/3 combined)
  adj_factor:   Q1,Q2: 1/5·1/2·1/3 = 1/30 · Q3..Q5: 1/2·1/3 = 1/6 · Q6,Q7: 1/3 · Q8: 1
  adjusted:     Q1 100/30=3.33 · Q2 110/30=3.67 · Q3 22.50/6=3.75 · Q4 4.00 · Q5 4.25
                · Q6 4.40 · Q7 4.70 · Q8 4.80          (ROUND_HALF_UP to the paisa)

BRAVO (INE000GOLDB2) — the demerger block:
  raw closes:   Q1 200.00 Q2 210.00 Q3 220.00 Q4 230.00 Q5 160.00 Q6 165.00 Q7 170.00 Q8 175.00
  action:       demerger ex 2024-12-20 (between Q4 2024-10-15 and Q5 2025-01-15), needs_review
  pending:      Q1..Q4 BLOCKED (pre-ex window); Q5..Q8 published at factor 1
  resolved 10:7 (remaining entity keeps 70%): Q1 140.00 · Q2 147.00 · Q3 154.00 · Q4 161.00

CHARLIE (INE000GOLDC3) — delisting + dividend-only:
  raw closes:   Q1 50.00  Q2 51.00  Q3 52.00  Q4 53.00  Q5 54.00  (delists after Q5 — rows stop)
  action:       dividend ₹2 ex 2024-05-01 (no price effect) → all adjusted = raw, factor 1.
"""

from datetime import date, datetime
from decimal import Decimal as D

QUARTERS = [
    date(2024, 1, 15),
    date(2024, 4, 15),
    date(2024, 7, 15),
    date(2024, 10, 15),
    date(2025, 1, 15),
    date(2025, 4, 15),
    date(2025, 7, 15),
    date(2025, 10, 15),
]

ALPHA, BRAVO, CHARLIE = "INE000GOLDA1", "INE000GOLDB2", "INE000GOLDC3"

COVERAGE_FLOOR = date(2024, 1, 1)
COVERAGE_CEILING = date(2025, 12, 31)
ASOF = date(2025, 12, 31)

ALPHA_RAW = [
    D("100.00"),
    D("110.00"),
    D("22.50"),
    D("24.00"),
    D("25.50"),
    D("13.20"),
    D("14.10"),
    D("4.80"),
]
BRAVO_RAW = [
    D("200.00"),
    D("210.00"),
    D("220.00"),
    D("230.00"),
    D("160.00"),
    D("165.00"),
    D("170.00"),
    D("175.00"),
]
CHARLIE_RAW = [D("50.00"), D("51.00"), D("52.00"), D("53.00"), D("54.00")]  # delists after Q5

# Hand-computed expected adjusted closes (see module docstring for the arithmetic).
ALPHA_ADJUSTED = [
    D("3.33"),
    D("3.67"),
    D("3.75"),
    D("4.00"),
    D("4.25"),
    D("4.40"),
    D("4.70"),
    D("4.80"),
]
BRAVO_ADJUSTED_PENDING = [D("160.00"), D("165.00"), D("170.00"), D("175.00")]  # Q5..Q8 only
BRAVO_ADJUSTED_RESOLVED = [
    D("140.00"),
    D("147.00"),
    D("154.00"),
    D("161.00"),
    *BRAVO_ADJUSTED_PENDING,
]
CHARLIE_ADJUSTED = CHARLIE_RAW  # factor 1 everywhere

# Chosen to sit strictly between Q4 (2024-10-15) and Q5 (2025-01-15): the hand-computation
# blocks exactly Q1..Q4. (The first draft said 2025-01-20, which is AFTER Q5 — a fixture-date
# typo against the documented intent, caught by the golden run and corrected 2026-07-18.)
DEMERGER_EX = date(2024, 12, 20)


def panel_rows() -> list[tuple[date, str, str, str, D | None, int | None]]:
    """(trade_date, symbol, series, isin, close, volume) rows for the conftest factory."""
    rows = []
    for q, c in zip(QUARTERS, ALPHA_RAW, strict=True):
        rows.append((q, "ALPHA", "EQ", ALPHA, c, 1000))
    for q, c in zip(QUARTERS, BRAVO_RAW, strict=True):
        rows.append((q, "BRAVO", "EQ", BRAVO, c, 1000))
    for q, c in zip(QUARTERS[:5], CHARLIE_RAW, strict=True):
        rows.append((q, "CHARLIE", "EQ", CHARLIE, c, 1000))
    return rows


def ca_entries(demerger_status: str = "needs_review") -> list[tuple]:
    """corporate_actions rows; demerger_status flips BRAVO between pending and resolved."""
    demerger_ratio = (10, 7) if demerger_status == "resolved" else (None, None)
    a = datetime
    return [
        (ALPHA, date(2024, 6, 1), "split", 10, 2, None, "auto", "FV 10->2", a(2024, 6, 1)),
        (
            ALPHA,
            date(2024, 9, 1),
            "dividend",
            None,
            None,
            D("5.00"),
            "auto",
            "div 5",
            a(2024, 9, 1),
        ),
        (ALPHA, date(2025, 2, 1), "bonus", 1, 1, None, "auto", "bonus 1:1", a(2025, 2, 1)),
        (ALPHA, date(2025, 8, 1), "bonus", 1, 2, None, "auto", "bonus 1:2", a(2025, 8, 1)),
        (ALPHA, date(2025, 8, 1), "split", 2, 1, None, "auto", "FV 2->1", a(2025, 8, 1)),
        (
            BRAVO,
            DEMERGER_EX,
            "demerger",
            *demerger_ratio,
            None,
            demerger_status,
            "scheme",
            a(2024, 12, 20),
        ),
        (
            CHARLIE,
            date(2024, 5, 1),
            "dividend",
            None,
            None,
            D("2.00"),
            "auto",
            "div 2",
            a(2024, 5, 1),
        ),
    ]

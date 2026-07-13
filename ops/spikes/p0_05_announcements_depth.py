"""P0-05 sub-spike C: how deep does the NSE corporate-announcements API archive go?

Operator tooling (ops/spikes/ — no tests by design; never run from tests or CI): run manually
from a residential IP. One cookie warmup + six 1-week windows stepping back through the years
(>=3.5s delays, hard stop on 403/429). Prints per-window row counts, a sample payload's keys,
and the bracketed archive floor. Findings land in doc 09 (feeds P0-21 and ADR-002).
Run: uv run python ops/spikes/p0_05_announcements_depth.py
"""

import time

import httpx

# Finding (2026-07-13): www.nseindia.com returns 403 pre-cookie to BOTH httpx and curl from a
# residential IP — the edge blocks non-browser TLS fingerprints outright. This script is kept
# as the record of that probe; the P0-21 collector must use a browser-grade client.
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/126.0 Safari/537.36"
    ),
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://www.nseindia.com/companies-listing/corporate-filings-announcements",
}
DELAY_S = 3.5

# 1-week windows (from, to) in DD-MM-YYYY, stepping back through the years.
WINDOWS = [
    ("06-01-2025", "10-01-2025"),
    ("09-01-2023", "13-01-2023"),
    ("11-01-2021", "15-01-2021"),
    ("07-01-2019", "11-01-2019"),
    ("09-01-2017", "13-01-2017"),
    ("12-01-2015", "16-01-2015"),
]


def main() -> None:
    client = httpx.Client(headers=HEADERS, timeout=30, follow_redirects=True)
    print("warmup: GET https://www.nseindia.com (cookie dance)")
    warm = client.get("https://www.nseindia.com")
    print(f"    HTTP {warm.status_code}, cookies: {sorted(client.cookies)}")
    if warm.status_code in (403, 429):
        print("BLOCKED at warmup — stopping immediately.")
        return

    earliest_nonempty: str | None = None
    sample_keys: list[str] = []
    for frm, to in WINDOWS:
        time.sleep(DELAY_S)
        url = (
            "https://www.nseindia.com/api/corporate-announcements"
            f"?index=equities&from_date={frm}&to_date={to}"
        )
        resp = client.get(url)
        if resp.status_code in (403, 429):
            print(f"{frm}..{to}: BLOCKED ({resp.status_code}) — stopping immediately.")
            break
        try:
            payload = resp.json()
            rows = payload if isinstance(payload, list) else payload.get("data", [])
        except ValueError:
            rows = None
        n = len(rows) if rows is not None else -1
        print(f"{frm}..{to}: HTTP {resp.status_code}, rows={n}")
        if rows:
            earliest_nonempty = frm
            if not sample_keys:
                sample_keys = sorted(rows[0].keys())

    print("\n=== RESULT ===")
    print(f"earliest non-empty window starts: {earliest_nonempty}")
    print(f"sample row keys: {sample_keys}")


if __name__ == "__main__":
    main()

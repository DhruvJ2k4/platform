"""P0-05 sub-spike B: survey NSE bhavcopy archive format epochs across 2010-2026.

Operator tooling (ops/spikes/ — no tests by design; never run from tests or CI): run manually
from a residential IP. Downloads ~10 sample bhavcopies politely (>=3.5s delay, browser UA,
hard stop on 403/429), hoards every hit via RawStore (raw is hoarded forever, doc 08), and
prints the epoch map: date -> URL pattern -> exact header signature. Findings land in doc 09.
Run: uv run python ops/spikes/p0_05_epoch_survey.py
"""

import io
import time
import zipfile
from datetime import date, timedelta

import httpx

from quant.ingest import RawStore

# Finding (2026-07-13): a bare UA gets HTTP 403 from the Akamai edge even from a residential
# IP; the full browser header set below gets HTTP 200. P0-06's adapter must send all four.
UA = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/126.0 Safari/537.36"
    ),
    "Accept": "*/*",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://www.nseindia.com/",
}
DELAY_S = 3.5
UDIFF_CUTOVER = date(2024, 7, 8)

# Mid-week sample dates spread across eras; 404 = holiday, retried once next weekday.
SAMPLE_DATES = [
    date(2010, 1, 13),
    date(2013, 1, 16),
    date(2016, 1, 13),
    date(2019, 1, 16),
    date(2022, 1, 12),
    date(2024, 1, 10),
    date(2024, 6, 12),
    date(2024, 8, 14),
    date(2025, 1, 15),
    date(2026, 7, 8),
]

MONTHS = ["JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"]


def classic_url(d: date) -> str:
    mon = MONTHS[d.month - 1]
    return (
        "https://archives.nseindia.com/content/historical/EQUITIES/"
        f"{d.year}/{mon}/cm{d.day:02d}{mon}{d.year}bhav.csv.zip"
    )


def udiff_urls(d: date) -> list[str]:
    ymd = d.strftime("%Y%m%d")
    name = f"BhavCopy_NSE_CM_0_0_0_{ymd}_F_0000.csv.zip"
    return [
        f"https://nsearchives.nseindia.com/content/cm/{name}",
        f"https://archives.nseindia.com/products/content/cm/{name}",
    ]


def header_of(zip_bytes: bytes) -> str:
    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
        member = zf.namelist()[0]
        first_line = zf.read(member).split(b"\n", 1)[0].decode("utf-8", "replace").strip()
    return first_line


def main() -> None:
    store = RawStore()
    client = httpx.Client(headers=UA, timeout=30, follow_redirects=True)
    working_udiff: str | None = None
    results: list[tuple[date, str, str]] = []  # (date, pattern-name, header)

    for d in SAMPLE_DATES:
        candidates = (
            [("classic", classic_url(d))]
            if d < UDIFF_CUTOVER
            else (
                [("udiff", working_udiff.format(ymd=d.strftime("%Y%m%d")))]
                if working_udiff
                else [("udiff", u) for u in udiff_urls(d)]
            )
        )
        hit = False
        for day_offset in (0, 1):  # holiday retry: next day, once
            dd = d + timedelta(days=day_offset)
            if day_offset:
                candidates = (
                    [("classic", classic_url(dd))]
                    if dd < UDIFF_CUTOVER
                    else [("udiff", u) for u in udiff_urls(dd)]
                )
            for pat, url in candidates:
                time.sleep(DELAY_S)
                resp = client.get(url)
                print(f"{dd} {pat:8s} HTTP {resp.status_code} {len(resp.content):>9d}B  {url}")
                if resp.status_code in (403, 429):
                    print(f"BLOCKED ({resp.status_code}) — stopping host contact immediately.")
                    return
                if resp.status_code == 200 and resp.content[:2] == b"PK":
                    artifact, created = store.put("bhavcopy", dd, resp.content, suffix=".zip")
                    header = header_of(resp.content)
                    results.append((dd, pat, header))
                    print(f"    hoarded sha={artifact.sha256[:12]} created={created}")
                    print(f"    header: {header}")
                    if pat == "udiff" and working_udiff is None:
                        working_udiff = url.replace(dd.strftime("%Y%m%d"), "{ymd}")
                    hit = True
                    break
            if hit:
                break
        if not hit:
            print(f"    {d}: no file found (holiday cluster or pattern miss) — recorded as gap")

    print("\n=== EPOCH MAP (distinct header signatures, chronological) ===")
    seen: dict[str, list[date]] = {}
    for dd, _pat, header in results:
        seen.setdefault(header, []).append(dd)
    for i, (header, dates) in enumerate(seen.items(), 1):
        print(f"[epoch {i}] {min(dates)} .. {max(dates)}  ({len(dates)} samples)")
        print(f"          {header}")


if __name__ == "__main__":
    main()

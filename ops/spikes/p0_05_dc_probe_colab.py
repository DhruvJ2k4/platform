"""P0-05 sub-spike A: NSE datacenter-IP tolerance probe — PASTE INTO GOOGLE COLAB / CODESPACE.

Self-contained (stdlib + requests, both preinstalled in Colab); no repo imports. Makes at most
5 polite requests (3.5s delays, browser UA) and STOPS a host on its first 403/429. Evidence is
single-vantage and informs ADR-009's FALLBACK path only — the home-box decision stands either
way. Paste the printed table back to the operator session.
"""

import time

import requests

UA = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/126.0 Safari/537.36"
    )
}
DELAY_S = 3.5


def probe(session: requests.Session, name: str, url: str) -> tuple[str, int, int]:
    time.sleep(DELAY_S)
    try:
        resp = session.get(url, headers=UA, timeout=30)
        return name, resp.status_code, len(resp.content)
    except requests.RequestException as exc:
        print(f"{name}: EXCEPTION {type(exc).__name__}: {exc}")
        return name, -1, 0


def main() -> None:
    ip = requests.get("https://api.ipify.org", timeout=15).text
    print(f"egress IP (record this): {ip}")

    results = []
    s = requests.Session()

    for name, url in [
        (
            "archives-classic-2019",
            "https://archives.nseindia.com/content/historical/EQUITIES/2019/JAN/"
            "cm16JAN2019bhav.csv.zip",
        ),
        (
            "archives-udiff-2025",
            "https://nsearchives.nseindia.com/content/cm/"
            "BhavCopy_NSE_CM_0_0_0_20250115_F_0000.csv.zip",
        ),
    ]:
        name, status, nbytes = probe(s, name, url)
        results.append((name, status, nbytes))
        print(f"{name}: HTTP {status}, {nbytes} bytes")
        if status in (403, 429):
            print("archives host blocked — not retrying it.")
            break

    name, status, nbytes = probe(s, "www-homepage-warmup", "https://www.nseindia.com")
    results.append((name, status, nbytes))
    print(f"www-homepage-warmup: HTTP {status}, {nbytes} bytes")
    if status not in (403, 429, -1):
        name, status, nbytes = probe(
            s, "www-api-market-status", "https://www.nseindia.com/api/marketStatus"
        )
        results.append((name, status, nbytes))
        print(f"www-api-market-status: HTTP {status}, {nbytes} bytes")
    else:
        print("www host blocked at warmup — skipping the API probe.")

    print("\n=== PASTE EVERYTHING ABOVE THIS LINE BACK, PLUS: ===")
    print(f"RESULT_TABLE ip={ip} " + " ".join(f"{n}={s}" for n, s, _ in results))


if __name__ == "__main__":
    main()

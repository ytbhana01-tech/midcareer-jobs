"""ALIO recruitment API collector. Runs only on GitHub Actions (never in browser)."""
import datetime as dt
import json
import os
from pathlib import Path
from urllib.parse import urlencode, urlsplit
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parent

def fetch_page(page):
    base = os.environ["ALIO_BASE_URL"].rstrip("/")
    parsed = urlsplit(base)
    if parsed.scheme != "https" or parsed.hostname != "opendata.alio.go.kr":
        raise ValueError("ALIO_BASE_URL must be HTTPS on opendata.alio.go.kr")
    params = {
        "serviceKey": os.environ["ALIO_API_KEY"],
        "pageNo": page,
        "numOfRows": 100,
        "ongoingYn": "Y",
        "resultType": "json",
    }
    url = base + "/new/v1/recruit/list.do?" + urlencode(params)
    req = Request(url, method="POST", headers={"Accept": "application/json"})
    try:
        with urlopen(req, timeout=30) as response:
            return json.load(response)
    except Exception:
        raise RuntimeError("ALIO API request failed; credentials and URL withheld") from None

def main():
    # Fail closed: do not publish unverified or structurally unknown records.
    payload = fetch_page(1)
    if not isinstance(payload, dict) or not isinstance(payload.get("result"), list):
        raise RuntimeError("Unexpected API response; existing listing data preserved")
    # Response field mappings and canonical announcement URLs require a real sample.
    print("API response received; publication paused pending field mapping.")
    print("Record count on first page:", len(payload["result"]))

if __name__ == "__main__":
    main()

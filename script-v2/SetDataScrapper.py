import json
import os
import re
import time
from datetime import datetime

import requests
from bs4 import BeautifulSoup

BASE_URL = "https://pocket.limitlesstcg.com"
CARDS_URL = BASE_URL + "/cards"

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RELEASE_DIR = os.path.join(BASE_DIR, "release")
EXPORT_PATH = os.path.join(RELEASE_DIR, "sets.json")

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
}


def fetch_html(url: str) -> str:
    resp = requests.get(url, headers=HEADERS, timeout=30)
    resp.raise_for_status()
    return resp.text


def normalize_code(raw: str) -> str:
    """Uppercase code and convert PROMO-X to P-X."""
    code = raw.strip().upper()
    if code.startswith("PROMO-"):
        code = "P-" + code[6:]
    return code


def parse_date(raw: str) -> str | None:
    """Convert '28 May 26' or '30 Oct 24' to ISO 'YYYY-MM-DD'."""
    raw = raw.strip()
    for fmt in ("%d %b %y", "%d %b %Y"):
        try:
            return datetime.strptime(raw, fmt).strftime("%Y-%m-%d")
        except ValueError:
            continue
    return None


def make_short_name(name: str) -> str:
    cleaned = re.sub(r"['\-]", " ", name)
    words = [w for w in cleaned.split() if w.lower() not in {"and", "of", "the"}]
    return "".join(w[0] for w in words if w).upper()


def extract_series(code: str) -> str:
    if code.startswith("P-"):
        return code[2:]
    return code[0] if code else ""


def scrape_sets_list(html: str) -> list[dict]:
    """
    Parse the /cards listing page.
    Returns list of dicts with: code, name, releaseDate, count, series.
    """
    soup = BeautifulSoup(html, "html.parser")
    sets = []
    current_series = ""

    table = soup.find("table")
    if not table:
        return sets

    for row in table.find_all("tr"):
        # Series header row
        th = row.find("th", class_="sub-heading")
        if th:
            # e.g. "B Series" → "B",  "Promo Cards" → keep as-is for later
            text = th.get_text(strip=True)
            match = re.match(r"^([A-Z])\s+Series", text, re.IGNORECASE)
            current_series = match.group(1).upper() if match else text
            continue

        cells = row.find_all("td")
        if len(cells) < 3:
            continue

        # Cell 0: name + code
        a_tag = cells[0].find("a")
        if not a_tag:
            continue

        code_span = a_tag.find("span", class_="code")
        raw_code = code_span.get_text(strip=True) if code_span else ""
        code = normalize_code(raw_code)
        if not code:
            continue

        # Name = all text excluding the code annotation span
        if code_span:
            code_span.extract()
        name = a_tag.get_text(" ", strip=True)
        # Remove leftover set-icon text
        name = re.sub(r"\s+", " ", name).strip()

        # Cell 1: release date
        release_date = parse_date(cells[1].get_text(strip=True))

        # Cell 2: card count
        try:
            count = int(cells[2].get_text(strip=True))
        except ValueError:
            count = 0

        series = extract_series(code)

        sets.append({
            "code": code,
            "name": name,
            "releaseDate": release_date,
            "count": count,
            "series": series,
        })

    return sets


def scrape_packs(set_code: str) -> list[str]:
    """
    Fetch /cards/{set_code} and extract pack names from the filter select.
    Returns list of pack name strings (empty list if none found).
    """
    url = f"{BASE_URL}/cards/{set_code}"
    try:
        html = fetch_html(url)
    except requests.HTTPError:
        return []

    soup = BeautifulSoup(html, "html.parser")

    # Limitless uses a <select> with pack options; look for one whose options
    # are not card attributes (type, rarity, etc.) but pack names.
    packs = []
    for select in soup.find_all("select"):
        name_attr = select.get("name", "")
        if "pack" not in name_attr.lower():
            continue
        for option in select.find_all("option"):
            val = option.get("value", "").strip()
            label = option.get_text(strip=True)
            if val and val.lower() not in ("", "any", "all"):
                packs.append(label or val)
        if packs:
            return packs

    # Fallback: look for pack filter links / buttons
    for elem in soup.find_all(["a", "button"], class_=re.compile(r"pack", re.I)):
        label = elem.get_text(strip=True)
        if label:
            packs.append(label)

    return packs


def generate_sets() -> list[dict]:
    print(f"[1/2] Fetching set list from {CARDS_URL} …")
    html = fetch_html(CARDS_URL)
    raw_sets = scrape_sets_list(html)
    print(f"      Found {len(raw_sets)} sets.")

    result = []
    for i, s in enumerate(raw_sets, 1):
        code = s["code"]
        print(f"[2/2] ({i}/{len(raw_sets)}) Scraping packs for {code} …")
        packs = scrape_packs(code)
        time.sleep(0.4)   # polite crawl delay

        result.append({
            "code": code,
            "name": s["name"],
            "shortName": make_short_name(s["name"]),
            "series": s["series"],
            "count": s["count"],
            "releaseDate": s["releaseDate"],
            "packs": packs,
        })

    # Sort: series asc, promo sets last within series, then by code
    result.sort(key=lambda s: (s["series"], s["code"].startswith("P-"), s["code"]))
    return result


if __name__ == "__main__":
    sets = generate_sets()
    os.makedirs(RELEASE_DIR, exist_ok=True)
    with open(EXPORT_PATH, "w", encoding="utf-8") as f:
        json.dump(sets, f, indent=4, ensure_ascii=False)
    print(f"\nSaved {len(sets)} sets → {EXPORT_PATH}")


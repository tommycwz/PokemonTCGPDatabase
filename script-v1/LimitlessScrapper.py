import os
import json
import requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin
import unicodedata
import re

BASE_URL = "https://pocket.limitlesstcg.com"
LIST_URL_TEMPLATE = BASE_URL + "/cards/{set_code}"
CARD_URL_TEMPLATE = BASE_URL + "/cards/{set_code}/{number}"

# Align with CardDataScrapper layout: missing ids in misc, cards in release
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MISC_DIR = os.path.join(BASE_DIR, "misc")
RELEASE_DIR = os.path.join(BASE_DIR, "release")
MISSING_DATA_CARD_PATH = os.path.join(MISC_DIR, "missing_data.json")


def scrape_card_links(set_code: str) -> list[str]:
    url = LIST_URL_TEMPLATE.format(set_code=set_code)
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    }
    resp = requests.get(url, headers=headers, timeout=30)
    resp.raise_for_status()

    soup = BeautifulSoup(resp.text, "html.parser")
    grid = soup.find("div", class_="card-search-grid")
    if not grid:
        return []

    links: list[str] = []
    for a in grid.find_all("a", href=True):
        href = a["href"].strip()
        if not href:
            continue
        full_url = urljoin(BASE_URL, href)
        links.append(full_url)
    return links


def _normalize_label(label: str) -> str:
    txt = unicodedata.normalize("NFKD", label).encode("ascii", "ignore").decode()
    return txt.strip().lower()


def _normalize_id_for_cards(cid: str) -> str:
    # Keep ids consistent with cards.json normalization
    return cid.replace("PROMO-", "P-")


def fetch_card_type_info(set_code: str, number: int) -> tuple[str, str | None, str | None] | None:
    url = CARD_URL_TEMPLATE.format(set_code=set_code, number=number)
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    }
    resp = requests.get(url, headers=headers, timeout=30)
    if not resp.ok:
        return None
    soup = BeautifulSoup(resp.text, "html.parser")
    p = soup.select_one("div.card-text-section p.card-text-type")
    if not p:
        # Fallback: any p.card-text-type
        p = soup.select_one("p.card-text-type")
    if not p:
        return None
    raw = p.get_text(" ", strip=True)
    if not raw:
        return None
    # Split type line on hyphen surrounded by spaces to avoid splitting names like "Ho-Oh"
    parts = [seg.strip() for seg in re.split(r"\s+-\s+", raw) if seg.strip()]
    if not parts:
        return None
    main_type = _normalize_label(parts[0])
    subtype: str | None = None
    # For Trainer, the next segment is the subtype (Tool, Stadium, etc.)
    if main_type == "trainer" and len(parts) > 1:
        subtype = _normalize_label(parts[1])

    # For Pokemon, get element from the title line: p.card-text-title
    element: str | None = None
    if main_type == "pokemon":
        tp = soup.select_one("div.card-text-section p.card-text-title")
        if not tp:
            tp = soup.select_one("p.card-text-title")
        if tp:
            title_txt = tp.get_text(" ", strip=True)
            # Split on " - " to preserve internal hyphens in names (e.g., Ho-Oh ex)
            tparts = [seg.strip() for seg in re.split(r"\s+-\s+", title_txt) if seg.strip()]
            # Expect [..., Element, 'XX HP'] — take the penultimate segment as element
            if len(tparts) >= 2:
                element = _normalize_label(tparts[-2])
    return (main_type, subtype, element)


def load_missing_ids(path: str = MISSING_DATA_CARD_PATH) -> list[str]:
    if not os.path.exists(path):
        return []
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, list):
            return [str(x).strip() for x in data if isinstance(x, (str, int)) and str(x).strip()]
    except Exception:
        pass
    return []


def parse_id(card_id: str) -> tuple[str, int] | None:
    # Supports formats like B2-230 and P-A-001 / PROMO-A-001
    s = str(card_id).strip()
    if not s or "-" not in s:
        return None
    parts = s.split("-")
    if len(parts) >= 3 and parts[0].upper() in ("P", "PROMO"):
        # Preserve the promo prefix in the set code, e.g. P-A
        set_code = f"{parts[0]}-{parts[1]}"
        num_part = parts[-1]
    else:
        set_code = parts[0]
        num_part = parts[-1]
    try:
        number = int(num_part)
    except Exception:
        # Extract digits and convert to int (strips leading zeros)
        digits = "".join(ch for ch in num_part if ch.isdigit())
        if not digits:
            return None
        number = int(digits)
    return set_code, number


if __name__ == "__main__":
    # If missing_data.json exists, fetch types/elements and update cards.json
    missing_ids = load_missing_ids(MISSING_DATA_CARD_PATH)
    if missing_ids:
        total = len(missing_ids)
        # Prepare updates
        updates: dict[str, dict[str, str]] = {}
        for idx, cid in enumerate(missing_ids, start=1):
            parsed = parse_id(cid)
            if not parsed:
                print(f"[{idx}/{total}] {cid}: unable to parse id")
                continue
            set_code, number = parsed
            info = fetch_card_type_info(set_code, number)
            if not info:
                print(f"[{idx}/{total}] {cid}: unknown")
                continue
            main_type, subtype, element = info
            if main_type == "trainer" and subtype:
                updates[cid] = {"type": subtype}
                print(f"[{idx}/{total}] {cid}: trainer -> {subtype}")
            elif main_type == "pokemon":
                entry: dict[str, str] = {"type": "pokemon"}
                if element:
                    entry["element"] = element
                updates[cid] = entry
                elog = element if element else "(no element)"
                print(f"[{idx}/{total}] {cid}: pokemon -> {elog}")
            else:
                updates[cid] = {"type": main_type}
                print(f"[{idx}/{total}] {cid}: {main_type}")

        # Load cards.json from release folder
        cards_path = os.path.join(RELEASE_DIR, "cards.json")
        try:
            with open(cards_path, "r", encoding="utf-8") as f:
                cards = json.load(f)
            if not isinstance(cards, list):
                raise ValueError("cards.json is not a list")
        except Exception as e:
            print(f"Failed to load cards.json: {e}")
            cards = []

        # Apply updates by id
        updated_count = 0
        updated_ids: set[str] = set()
        if cards:
            id_to_index = {str(c.get("id", "")): i for i, c in enumerate(cards) if isinstance(c, dict)}
            for cid, change in updates.items():
                # Try exact id, then normalized id (PROMO- -> P-)
                idx = id_to_index.get(cid)
                if idx is None:
                    norm = _normalize_id_for_cards(cid)
                    idx = id_to_index.get(norm)
                if idx is None:
                    continue
                card = cards[idx]
                if "type" in change:
                    card["type"] = change["type"]
                if "element" in change:
                    card["element"] = change["element"]
                updated_count += 1
                updated_ids.add(cid)

            # Save back
            try:
                with open(cards_path, "w", encoding="utf-8") as f:
                    json.dump(cards, f, ensure_ascii=False, indent=2)
                print(f"Updated {updated_count} cards in {cards_path}")
            except Exception as e:
                print(f"Failed to write cards.json: {e}")
        else:
            print("No cards to update or failed to load cards.json")

        # Remove resolved ids from missing_data.json
        try:
            remaining = [cid for cid in missing_ids if cid not in updated_ids]
            with open(MISSING_DATA_CARD_PATH, "w", encoding="utf-8") as f:
                json.dump(sorted(remaining), f, ensure_ascii=False, indent=2)
            print(f"Resolved {len(updated_ids)}/{total}. Remaining: {len(remaining)} in {MISSING_DATA_CARD_PATH}")
        except Exception as e:
            print(f"Failed to update missing_data.json: {e}")
    else:
        # Fallback demo: scrape set list URLs
        print("ERROR: missing_data.json not found or empty.")
        set_code = "B2"
        urls = scrape_card_links(set_code)
        print(urls)
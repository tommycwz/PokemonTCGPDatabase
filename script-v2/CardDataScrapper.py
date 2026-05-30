import json
import os
import re
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Dict, List, Optional

import requests
from bs4 import BeautifulSoup

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

BASE_URL = "https://pocket.limitlesstcg.com"
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RELEASE_DIR = os.path.join(BASE_DIR, "release")
TEMP_DIR = os.path.join(BASE_DIR, "temp")
SETS_PATH = os.path.join(RELEASE_DIR, "sets.json")
EXPORT_CARDS_PATH = os.path.join(RELEASE_DIR, "cards.json")

CONCURRENCY_LIMIT = 10

RARITY_MAP: Dict[str, str] = {
    "◊": "C",
    "◊◊": "U",
    "◊◊◊": "R",
    "◊◊◊◊": "RR",
    "☆": "AR",
    "☆☆": "SR",
    "🌈": "SAR",
    "☆☆☆": "IM",
    "👑": "UR",
    "✵": "S",
    "✵✵": "SSR",
}

# Pre-fetched shiny lookup: card URL path -> 'S' or 'SSR'
# Populated once at startup by build_shiny_lookup().
_SHINY_LOOKUP: Dict[str, str] = {}

# ---------------------------------------------------------------------------
# Thread-local HTTP sessions
# ---------------------------------------------------------------------------

_thread_local = threading.local()

_REQUEST_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}


def _get_session() -> requests.Session:
    if not hasattr(_thread_local, "session"):
        s = requests.Session()
        s.headers.update(_REQUEST_HEADERS)
        _thread_local.session = s
    return _thread_local.session


def fetch_html(url: str) -> BeautifulSoup:
    session = _get_session()
    resp = session.get(url, timeout=30)
    resp.raise_for_status()
    return BeautifulSoup(resp.text, "html.parser")


# ---------------------------------------------------------------------------
# Shiny lookup
# ---------------------------------------------------------------------------

def build_shiny_lookup() -> Dict[str, str]:
    """
    Fetch shiny card lists and return a mapping of card URL paths to
    their shiny rarity ('S' or 'SSR').

    Strategy:
      - /cards/?q=is:shiny,sfa&show=all  ->  all shiny cards (S + SSR)
      - /cards/?q=is:sfa&show=all        ->  shiny full art only (SSR / ✵✵)
      Cards in sfa         -> 'SSR'
      Cards in shiny only  -> 'S'
    """
    def _fetch_paths(query: str) -> set:
        url = f"{BASE_URL}/cards/?q={query}&show=all"
        print(f"  GET {url}")
        soup = fetch_html(url)
        grid = soup.find("div", class_="card-search-grid")
        if not grid:
            print(f"  WARNING: card-search-grid not found for query '{query}'")
            return set()
        return {
            a["href"].strip()
            for a in grid.find_all("a", href=True)
            if a.get("href", "").strip()
        }

    print("Building shiny lookup …")
    all_shiny = _fetch_paths("is:shiny,sfa")
    sfa = _fetch_paths("is:sfa")

    lookup: Dict[str, str] = {}
    for path in all_shiny:
        lookup[path] = "SSR" if path in sfa else "S"

    ssr_count = sum(1 for v in lookup.values() if v == "SSR")
    s_count = len(lookup) - ssr_count
    print(f"  Shiny lookup: {len(lookup)} cards ({s_count} S, {ssr_count} SSR)\n")
    return lookup


# ---------------------------------------------------------------------------
# Sets loading
# ---------------------------------------------------------------------------

def load_sets(path: str = SETS_PATH) -> List[Dict[str, Any]]:
    """Load sets from release/sets.json."""
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def code_to_url_id(code: str) -> str:
    """
    Convert stored uppercase code to the Limitless URL segment.
    e.g. 'A1A' -> 'A1a',  'B3A' -> 'B3a',  'A1' -> 'A1',  'P-A' -> 'P-A'
    Sub-set letter (digit-followed uppercase suffix) is lowercased.
    """
    return re.sub(r"(?<=\d)([A-Z])$", lambda m: m.group(1).lower(), code)


# ---------------------------------------------------------------------------
# Card scraping (ported from TempLimitlessScrapper)
# ---------------------------------------------------------------------------

def extract_pack_name(soup: BeautifulSoup) -> str:
    """Return the pack name from the card-prints-current div, or 'All'."""
    set_info = soup.select_one("div.card-prints-current")
    if not set_info:
        return "All"
    spans = set_info.find_all("span")
    pack_temp = spans[-1].get_text(strip=True) if spans else ""
    pack_info = pack_temp.split("\u00b7")[-1].strip().replace(" ", "").lower()
    if "pack" in pack_info:
        return pack_info.replace("pack", "").strip().title()
    return "All"


def extract_card_info(
    soup: BeautifulSoup,
    card_url: str,
    expansion: Dict[str, Any],
) -> Dict[str, Any]:
    try:
        in_pack_id = int(card_url.rstrip("/").split("/")[-1])
    except ValueError:
        raise ValueError(f"Failed to parse card number from url: {card_url}")

    set_code = expansion["code"]
    card_id = f"{set_code}-{in_pack_id}"

    # Image
    img_elem = soup.select_one("img.card")
    if not img_elem or not img_elem.get("src"):
        raise ValueError(f"No card image found: {card_url}")
    image_url = img_elem["src"]

    # Name & Element
    title_elem = soup.select_one("p.card-text-title")
    title = title_elem.get_text(strip=True) if title_elem else ""
    title_parts = title.split(" - ")
    raw_name = title_parts[0].strip()

    if "-" in raw_name:
        name_parts = raw_name.split("-", 1)
        name = name_parts[0].strip()
        element = name_parts[1].strip().capitalize()
    else:
        name = raw_name
        energy_string = title_parts[1].strip().lower() if len(title_parts) > 1 else "trainer"
        if energy_string == "40 hp" and ("Fossil" in name or name == "Old Amber"):
            energy_string = "trainer"
        element = "" if energy_string == "trainer" else energy_string.capitalize()

    # Card type / evolution stage
    type_elem = soup.select_one("p.card-text-type")
    type_text = type_elem.get_text(strip=True) if type_elem else ""
    type_parts = type_text.split("-")
    evolution_type = type_parts[1].strip().lower() if len(type_parts) > 1 else "basic"

    if "Fossil" in name or name == "Old Amber":
        card_type_final = "Fossil"
    elif evolution_type == "basic" and element != "":
        card_type_final = "pokemon"
    else:
        card_type_final = type_parts[0].strip() if element == "" else evolution_type.title()

    # Series letter
    series = set_code.split("-")[0][0].upper()

    # Rarity
    rarity_section = soup.select_one("table.card-prints-versions tr.current")
    if set_code.startswith("P-"):
        raw_rarity = "P"
    elif rarity_section:
        tds = rarity_section.select("td")
        raw_rarity = tds[-1].get_text(strip=True) if tds else "None"
    else:
        raw_rarity = "None"

    # Check shiny lookup (pre-fetched at startup).
    # Path uses the lowercase URL id (e.g. /cards/A2b/97) to match Limitless hrefs.
    card_path = f"/cards/{code_to_url_id(set_code)}/{in_pack_id}"
    if card_path in _SHINY_LOOKUP:
        raw_rarity = "✵✵" if _SHINY_LOOKUP[card_path] == "SSR" else "✵"

    final_rarity = RARITY_MAP.get(raw_rarity.strip(), raw_rarity)

    pack_name = extract_pack_name(soup)

    print(f"  {card_id} | {name} | {final_rarity} | pack={pack_name}")

    return {
        "series": series,
        "set": set_code,
        "number": in_pack_id,
        "id": card_id,
        "name": name,
        "rarity": final_rarity,
        "image": image_url,
        "packs": [pack_name] if pack_name else [],
        "element": element,
        "type": card_type_final,
        "isFoil": False,
    }


def get_card_details(
    card_url: str,
    expansion: Dict[str, Any],
) -> Optional[Dict[str, Any]]:
    try:
        soup = fetch_html(card_url)
        return extract_card_info(soup, card_url, expansion)
    except Exception as e:
        print(f"  ERROR {card_url}: {e}")
        return None


def get_card_links(set_url: str) -> List[str]:
    soup = fetch_html(set_url)
    links: List[str] = []
    grid = soup.select_one(".card-search-grid")
    if grid:
        for a in grid.select("a[href]"):
            links.append(f"{BASE_URL}{a['href']}")
    return links


def scrape_set(expansion: Dict[str, Any]) -> List[Dict[str, Any]]:
    url_id = code_to_url_id(expansion["code"])
    set_url = f"{BASE_URL}/cards/{url_id}"
    card_links = get_card_links(set_url)
    print(f"  {len(card_links)} cards found.")

    cards: List[Dict[str, Any]] = []
    with ThreadPoolExecutor(max_workers=CONCURRENCY_LIMIT) as executor:
        futures = {
            executor.submit(get_card_details, link, expansion): link
            for link in card_links
        }
        for future in as_completed(futures):
            card = future.result()
            if card:
                cards.append(card)
    return cards


def scrape_cards(sets: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    all_cards: List[Dict[str, Any]] = []
    for expansion in sets:
        print(f"\n[{expansion['code']}] {expansion['name']} …")
        try:
            cards = scrape_set(expansion)
            all_cards.extend(cards)
        except Exception as e:
            print(f"  ERROR scraping {expansion['code']}: {e}")
    return all_cards


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    _SHINY_LOOKUP = build_shiny_lookup()

    sets = load_sets()
    print(f"Loaded {len(sets)} sets from {SETS_PATH}\n")

    all_cards = scrape_cards(sets)
    all_cards.sort(key=lambda c: (c["set"], c["number"]))

    os.makedirs(TEMP_DIR, exist_ok=True)
    with open(EXPORT_CARDS_PATH, "w", encoding="utf-8") as f:
        json.dump(all_cards, f, ensure_ascii=False, indent=2)

    print(f"\nSaved {len(all_cards)} cards → {EXPORT_CARDS_PATH}")

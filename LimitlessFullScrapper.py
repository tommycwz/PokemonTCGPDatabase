import os
import re
import json
import threading
from typing import Any, Dict, List, Optional, Tuple
from concurrent.futures import ThreadPoolExecutor, as_completed

import requests
from bs4 import BeautifulSoup

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

BASE_URL = "https://pocket.limitlesstcg.com"
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TARGET_DIR = os.path.join(BASE_DIR, "debug", "assets")

CONCURRENCY_LIMIT = 10

PACKS: List[str] = [
    "pikachupack",
    "charizardpack",
    "mewtwopack",
    "dialgapack",
    "palkiapack",
    "mewpack",
    "arceuspack",
    "shiningrevelrypack",
    "lunalapack",
    "solgaleopack",
    "buzzwolepack",
    "eeveegrovepack",
    "ho-ohpack",
    "lugiapack",
    "suicunepack",
    "deluxepack",
    "megaaltariapack",
    "megablazikenpack",
    "megagyaradospack",
    "paldeanwonderspack",
    "megashinepack",
    "pulsingaurapack",
    "paradoxdrivepack",
    "allcards",
]

# Inverted mapping to translate Limitless symbols into your shortcodes
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
    "✵✵": "SSR"
}

# ---------------------------------------------------------------------------
# Expansion definitions
# ---------------------------------------------------------------------------

ALL_EXPANSIONS: List[Dict[str, Any]] = [
    {"id": "A1"}, {"id": "A1a"}, {"id": "A2"}, {"id": "A2a"}, {"id": "A2b"},
    {"id": "A3"}, {"id": "A3a"}, {"id": "A3b"}, {"id": "A4"}, {"id": "A4a"},
    {"id": "A4b"}, {"id": "B1"}, {"id": "B1a"}, {"id": "B2"}, {"id": "B2a"},
    {"id": "B2b"}, {"id": "B3"}, {"id": "B3a"}, {"id": "P-A"}, {"id": "P-B"},
]

RARITY_OVERRIDES: Dict[str, List[Dict[str, Any]]] = {
    "A2b": [
        {"rarity": "✵",   "start": 97,  "end": 106},
        {"rarity": "✵✵", "start": 107, "end": 110},
    ],
    "A3": [
        {"rarity": "✵",   "start": 210, "end": 229},
        {"rarity": "✵✵", "start": 230, "end": 237},
    ],
    "A3a": [
        {"rarity": "✵",   "start": 89,  "end": 98},
        {"rarity": "✵✵", "start": 99,  "end": 102},
    ],
    "A3b": [
        {"rarity": "✵",   "start": 93,  "end": 102},
        {"rarity": "✵✵", "start": 103, "end": 106},
    ],
    "A4": [
        {"rarity": "✵",   "start": 212, "end": 231},
        {"rarity": "✵✵", "start": 232, "end": 239},
    ],
    "A4a": [
        {"rarity": "✵",   "start": 91,  "end": 100},
        {"rarity": "✵✵", "start": 101, "end": 104},
    ],
    "A4b": [
        {"rarity": "✵✵", "start": 377, "end": 378},
    ],
    "B1": [
        {"rarity": "✵",   "start": 287, "end": 316},
        {"rarity": "✵✵", "start": 317, "end": 328},
    ],
    "B1a": [
        {"rarity": "✵",   "start": 88,  "end": 97},
        {"rarity": "✵✵", "start": 98,  "end": 101},
    ],
    "B2": [
        {"rarity": "✵",   "start": 205, "end": 224},
        {"rarity": "✵✵", "start": 225, "end": 232},
    ],
    "B2a": [
        {"rarity": "✵",   "start": 116, "end": 125},
        {"rarity": "✵✵", "start": 126, "end": 129},
    ],
    "B2b": [
        {"rarity": "✵",   "start": 87,  "end": 110},
        {"rarity": "✵✵", "start": 111, "end": 115},
    ],
    "B3": [
        {"rarity": "✵",   "start": 205, "end": 224},
        {"rarity": "✵✵", "start": 225, "end": 232},
    ],
    "B3a": [
        {"rarity": "✵",   "start": 95,  "end": 104},
        {"rarity": "✵✵", "start": 105, "end": 108},
    ],
    "P-B": [{"rarity": "P", "start": 0, "end": 999}],
}

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
        session = requests.Session()
        session.headers.update(_REQUEST_HEADERS)
        _thread_local.session = session
    return _thread_local.session

# ---------------------------------------------------------------------------
# Helper functions
# ---------------------------------------------------------------------------

def fetch_html(url: str) -> BeautifulSoup:
    session = _get_session()
    resp = session.get(url, timeout=30)
    resp.raise_for_status()
    return BeautifulSoup(resp.text, "html.parser")

def extract_set_and_pack_info(soup: BeautifulSoup) -> str:
    set_info = soup.select_one("div.card-prints-current")
    if not set_info:
        return "All"

    spans = set_info.find_all("span")
    pack_temp = spans[-1].get_text(strip=True) if spans else ""
    pack_info = pack_temp.split("\u00b7")[-1].strip().replace(" ", "").lower()
    pack = pack_info if pack_info in PACKS else "everypack"
    
    formatted_pack = pack.replace("pack", "").title()
    if formatted_pack == "Every": 
        formatted_pack = "All"
        
    return formatted_pack

def extract_card_info(
    soup: BeautifulSoup,
    card_url: str,
    expansion: Dict[str, Any],
) -> Dict[str, Any]:
    try:
        in_pack_id = int(card_url.rstrip("/").split("/")[-1])
    except ValueError:
        raise ValueError(f"Failed to parse card id from url: {card_url}")

    card_id = f"{expansion['id']}-{in_pack_id}"

    # --- Image (URL Only) ---
    img_elem = soup.select_one("img.card")
    if not img_elem or not img_elem.get("src"):
        raise ValueError(f"Could not find card image: {card_url}")
    image_url = img_elem["src"]

    # --- Title Extraction ---
    title_elem = soup.select_one("p.card-text-title")
    title = title_elem.get_text(strip=True) if title_elem else ""
    title_parts = title.split(" - ")
    raw_name = title_parts[0].strip()

    # Rules 1 & 2: Process Name and Element via hyphen splitting
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

    # --- Card Type and Evolution ---
    type_elem = soup.select_one("p.card-text-type")
    type_text = type_elem.get_text(strip=True) if type_elem else ""
    type_parts = type_text.split("-")
    evolution_type = type_parts[1].strip().lower() if len(type_parts) > 1 else "basic"

    # Rule 3: If Type is Basic, set it as pokemon
    if "Fossil" in name or name == "Old Amber":
        card_type_final = "Fossil"
    elif evolution_type == "basic" and element != "":
        card_type_final = "pokemon"
    else:
        card_type_final = type_parts[0].strip() if element == "" else evolution_type.title()

    # --- Series derivation ---
    series = expansion["id"].split("-")[0][0].upper()

    # --- Rarity (Rule 4 Mapping) ---
    rarity_section = soup.select_one("table.card-prints-versions tr.current")
    if "P-A" in card_url:
        raw_rarity = "P"
    elif rarity_section:
        tds = rarity_section.select("td")
        raw_rarity = tds[-1].get_text(strip=True) if tds else "None"
    else:
        raw_rarity = "None"

    # Apply structural rarity overrides
    for override in RARITY_OVERRIDES.get(expansion["id"].upper(), []):
        if override["start"] <= in_pack_id <= override["end"]:
            raw_rarity = override["rarity"]

    # Transform symbols to shortcodes via lookup dictionary
    final_rarity = RARITY_MAP.get(raw_rarity.strip(), raw_rarity)

    pack_name = extract_set_and_pack_info(soup)

    print(f"Processed: {card_id} - {name}")
    
    return {
        "series": series,
        "set": expansion["id"].upper(),
        "number": in_pack_id,
        "id": card_id,
        "name": name,
        "rarity": final_rarity,
        "image": image_url,
        "packs": [pack_name] if pack_name else [],
        "element": element,
        "type": card_type_final,
        "isFoil": False
    }


def get_card_details(
    card_url: str,
    expansion: Dict[str, Any],
) -> Optional[Dict[str, Any]]:
    try:
        soup = fetch_html(card_url)
        return extract_card_info(soup, card_url, expansion)
    except Exception as e:
        print(f"Error fetching details for {card_url}: {e}")
        return None


def get_card_links(main_url: str) -> List[str]:
    soup = fetch_html(main_url)
    links: List[str] = []
    grid = soup.select_one(".card-search-grid")
    if grid:
        for a in grid.select("a"):
            href = a.get("href")
            if href:
                links.append(f"{BASE_URL}{href}")
    return links


def scrape_cards() -> List[Dict[str, Any]]:
    all_cards: List[Dict[str, Any]] = []

    for expansion in ALL_EXPANSIONS:
        try:
            main_url = f"{BASE_URL}/cards/{expansion['id']}"
            card_links = get_card_links(main_url)
            print(f"Found {len(card_links)} card links for set {expansion['id']}.")

            with ThreadPoolExecutor(max_workers=CONCURRENCY_LIMIT) as executor:
                futures = {
                    executor.submit(get_card_details, link, expansion): link
                    for link in card_links
                }
                for future in as_completed(futures):
                    card = future.result()
                    if card:
                        all_cards.append(card)

        except Exception as e:
            print(f"Error scraping cards for {expansion['id']}: {e}")

    return all_cards


def main() -> None:
    os.makedirs(TARGET_DIR, exist_ok=True)
    cards = scrape_cards()

    # Sort alphabetically by set then numerically by card index
    cards.sort(
        key=lambda c: (
            c["set"],
            c["number"],
        )
    )

    output_path = os.path.join(TARGET_DIR, "cards.json")
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(cards, f, ensure_ascii=False, indent=2)
    print(f"Cards saved to {output_path}")

if __name__ == "__main__":
    main()
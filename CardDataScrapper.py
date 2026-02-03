
import os
import json
import requests
from typing import List, Dict, Any, Set

from dataclasses import dataclass, asdict

# App Settings
OVERRIDE_EXISTING_DATA = True
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "release")
EXPORT_CARD_PATH = os.path.join(DATA_DIR, "cards.json")
MISSING_DATA_CARD_PATH = os.path.join(DATA_DIR, "missing_data.json")
POCKETDB_CARD_URL = "https://raw.githubusercontent.com/flibustier/pokemon-tcg-pocket-database/main/dist/cards.json"
POCKETDB_CARD_EXTRA_URL = "https://raw.githubusercontent.com/flibustier/pokemon-tcg-pocket-database/main/dist/cards.extra.json"
POCKETDB_IMAGE_URL = "https://raw.githubusercontent.com/flibustier/pokemon-tcg-exchange/refs/heads/main/public/images/cards-by-set/"
TCGDEX_CARD_URL = "https://api.tcgdex.net/v2/en/sets/{SET_CODE}"
FOILED_CARDS_PATH = os.path.join(BASE_DIR, "FoiledCards.txt")


@dataclass
class PokemonCard:
    series: str
    set: str
    number: int
    id: str
    name: str
    rarity: str
    image: str
    packs: List[str]
    element: str
    type: str
    isFoil: bool

    @classmethod
    def from_json(cls, obj: Dict[str, Any]) -> "PokemonCard":
        original_set_code = str(obj.get("set", "")).strip()
        set_code = original_set_code
        num_raw = obj.get("number", "")
        num_str = str(num_raw).strip()
        if num_str.isdigit():
            num_pad = num_str.zfill(3)
            number_value = int(num_str)
        else:
            digits = "".join(ch for ch in num_str if ch.isdigit())
            number_value = int(digits) if digits.isdigit() else 0
            num_pad = digits.zfill(3) if digits else "000"

        # Normalize promotional set codes: PROMO- -> P-
        if set_code.startswith("PROMO-"):
            set_code = set_code.replace("PROMO-", "P-")

        # Uppercase set code for consistency (e.g., a1 -> A1, p-a -> P-A)
        set_code = set_code.upper()

        # Series: if set like "P-A" use the segment after '-', else first char
        if set_code and "-" in set_code:
            seg = set_code.split("-")[-1]
            series = seg[:1] if seg else ""
        else:
            series = set_code[:1] if set_code else ""
        id_val = f"{set_code}-{num_pad}"

        name = str(obj.get("name", "")).strip()
        if "PROMO" in name:
            name = name.replace("PROMO", "P")
        rarity = str(obj.get("rarity", "")).strip()
        # Use original set code for image path to match repository layout
        image = POCKETDB_IMAGE_URL + original_set_code + "/" + str(num_raw) + ".webp"
        packs = obj.get("packs") if isinstance(obj.get("packs"), list) else []
        element = str(obj.get("element", "")).strip()
        type_val = str(obj.get("type", "")).strip()
        is_foil = bool(obj.get("isFoil", False))

        return cls(
            series=series,
            set=set_code,
            number=number_value,
            id=id_val,
            name=name,
            rarity=rarity,
            image=image,
            packs=packs,
            element=element,
            type=type_val,
            isFoil=is_foil,
        )

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

def fetch_pocketdb_cards(url: str = POCKETDB_CARD_URL) -> List[Dict[str, Any]]:
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "application/json,text/plain,*/*",
    }
    resp = requests.get(url, headers=headers, timeout=30)
    resp.raise_for_status()
    data = resp.json()

    # Handle both array and object forms
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        # common shape: { "cards": [...] }
        cards = data.get("cards")
        if isinstance(cards, list):
            return cards
    raise ValueError("Unexpected PocketDB JSON format")


def fetch_pocketdb_card_extras(url: str = POCKETDB_CARD_EXTRA_URL) -> List[Dict[str, Any]]:
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "application/json,text/plain,*/*",
    }
    resp = requests.get(url, headers=headers, timeout=30)
    resp.raise_for_status()
    data = resp.json()
    if isinstance(data, list):
        return data
    raise ValueError("Unexpected PocketDB EXTRA JSON format")


def build_extras_lookup(extras: List[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    lookup: Dict[str, Dict[str, Any]] = {}
    for e in extras:
        set_code = str(e.get("set", "")).strip().upper()
        number_raw = e.get("number", 0)
        try:
            number_int = int(number_raw)
        except Exception:
            # Fall back to extracting digits
            digits = "".join(ch for ch in str(number_raw) if ch.isdigit())
            number_int = int(digits) if digits else 0
        key = f"{set_code}-{str(number_int).zfill(3)}"
        lookup[key] = e
    return lookup


def save_cards(path: str, cards: List[Dict[str, Any]]) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(cards, f, ensure_ascii=False, indent=2)


def load_foiled_ids(path: str = FOILED_CARDS_PATH) -> Set[str]:
    ids: Set[str] = set()
    try:
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                s = line.strip()
                if not s:
                    continue
                if s.startswith("#") or s.startswith("//"):
                    continue
                ids.add(s.upper())
    except FileNotFoundError:
        # Foiled list not found; proceed without overrides
        pass
    return ids


def load_missing_ids(path: str = MISSING_DATA_CARD_PATH) -> Set[str]:
    ids: Set[str] = set()
    if not os.path.exists(path):
        return ids
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, list):
            for v in data:
                if isinstance(v, str) and v.strip():
                    ids.add(v.strip())
    except Exception:
        pass
    return ids


def save_missing_ids(path: str, ids: Set[str]) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(sorted(ids), f, ensure_ascii=False, indent=2)


def load_existing_cards(path: str) -> Dict[str, Dict[str, Any]]:
    if not os.path.exists(path):
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, list):
            return {}
        result: Dict[str, Dict[str, Any]] = {}
        for item in data:
            if isinstance(item, dict):
                cid = str(item.get("id", "")).strip()
                if not cid:
                    continue
                # Normalize promotional IDs and set codes in existing data
                norm_id = cid.replace("PROMO-", "P-").upper()
                set_code = str(item.get("set", ""))
                if set_code:
                    item["set"] = set_code.replace("PROMO-", "P-").upper()
                # Update the id field if normalization changed it
                if norm_id != cid:
                    item["id"] = norm_id
                result[norm_id] = item
        return result
    except Exception:
        return {}


def merge_cards(existing: Dict[str, Dict[str, Any]], new_cards: List[Dict[str, Any]], override: bool) -> Dict[str, Dict[str, Any]]:
    merged = dict(existing)
    for c in new_cards:
        cid = str(c.get("id", "")).strip()
        if not cid:
            continue
        if override or cid not in merged:
            merged[cid] = c
    return merged


def main():
    # Fetch latest cards

    raw_cards = fetch_pocketdb_cards()
    card_objs = [PokemonCard.from_json(c) for c in raw_cards]

    # Override foil status from FoiledCards.txt if present
    foiled_ids = load_foiled_ids(FOILED_CARDS_PATH)
    if foiled_ids:
        for c in card_objs:
            if c.id and c.id.upper() in foiled_ids:
                c.isFoil = True

    # Enrich element/type from cards.extra.json (matched by set+number)
    try:
        extras = fetch_pocketdb_card_extras()
        extras_lookup = build_extras_lookup(extras)
        for c in card_objs:
            key = f"{c.set}-{str(c.number).zfill(3)}"
            extra = extras_lookup.get(key)
            if not extra:
                continue
            elem = extra.get("element")
            typ = extra.get("type")
            if elem:
                c.element = str(elem)
            if typ:
                c.type = str(typ)
    except Exception as e:
        # Non-fatal: proceed without extra enrichment
        pass
    serialized = [c.to_dict() for c in card_objs]

    # Collect IDs with missing type and store to MISSING_DATA_CARD_PATH
    missing_now: Set[str] = set()
    for c in card_objs:
        if not str(c.type).strip():
            if c.id:
                # Normalize promotional IDs: replace 'PROMO-' with 'P-'
                normalized_id = c.id.replace("PROMO-", "P-").upper()
                missing_now.add(normalized_id)
    if missing_now:
        existing_missing = load_missing_ids(MISSING_DATA_CARD_PATH)
        combined_missing = existing_missing | missing_now
        save_missing_ids(MISSING_DATA_CARD_PATH, combined_missing)

    # Load existing and merge according to OVERRIDE_EXISTING_DATA
    existing_map = load_existing_cards(EXPORT_CARD_PATH)
    before_count = len(existing_map)
    merged_map = merge_cards(existing_map, serialized, override=OVERRIDE_EXISTING_DATA)
    after_count = len(merged_map)
    merged_list = sorted(merged_map.values(), key=lambda x: str(x.get("id", "")))

    save_cards(EXPORT_CARD_PATH, merged_list)
    action = "overridden/added" if OVERRIDE_EXISTING_DATA else "added"
    print(f"Wrote {after_count} cards to {EXPORT_CARD_PATH} ({action}: {after_count - before_count})")
    # Print a small sample to verify
    for c in card_objs[:5]:
        print({"id": c.id, "series": c.series, "set": c.set, "number": c.number, "name": c.name})


if __name__ == "__main__":
    main()



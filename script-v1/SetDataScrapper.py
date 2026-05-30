import requests
import json
from datetime import datetime
import os

# ===============================================================
# CONFIGURATION
# ===============================================================

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# Write outputs to project release folder
DATA_DIR = os.path.join(BASE_DIR, "release")
EXPORT_SET_PATH = os.path.join(DATA_DIR, "sets.json")

POCKETDB_SET_URL = "https://raw.githubusercontent.com/flibustier/pokemon-tcg-pocket-database/main/dist/sets.json"
REQUEST_TIMEOUT = (6, 30)

# ===============================================================
# HTTP
# ===============================================================

# ===============================================================
# UTILITY FUNCTIONS
# ===============================================================

def fetch_json(url: str):
    headers = {
        "User-Agent": "PokemonTCGPCollector/2.0 (+https://github.com/tommycwz)",
        "Accept": "application/json",
        "Accept-Encoding": "gzip, deflate",
    }
    resp = requests.get(url, headers=headers, timeout=REQUEST_TIMEOUT)
    resp.raise_for_status()
    return resp.json()

def extract_series(code: str) -> str:
    if code.startswith("P-"):
        return code[2:]
    else:
        return code[0] if code else ""

# (removed card-related helpers)

# ===============================================================
# MAIN GENERATORS
# ===============================================================

def generate_sets():
    print("[generate_sets] Fetching sets data...")
    try:
        pocketdb_data = fetch_json(POCKETDB_SET_URL)

        # PocketDB sets.json is a dict keyed by series (e.g., "A", "B") or a flat list
        iterable_sets = []
        if isinstance(pocketdb_data, dict):
            for arr in pocketdb_data.values():
                if isinstance(arr, list):
                    iterable_sets.extend(arr)
        elif isinstance(pocketdb_data, list):
            iterable_sets = pocketdb_data

        processed_sets = []
        for s in iterable_sets:
            if not isinstance(s, dict):
                continue
            code = str(s.get("code", "")).upper()
            if code.startswith("PROMO-"):
                code = code.replace("PROMO-", "P-")
            series = extract_series(code)

            # Name may be dict or string depending on source
            name_val = s.get("name")
            name = None
            if isinstance(name_val, dict):
                name = name_val.get("en")
            elif isinstance(name_val, str):
                name = name_val
            if not name:
                name = s.get("label", {}).get("en", "Unknown")

            short_name = ""
            if isinstance(name, str) and name:
                cleaned = name.replace('-', ' ').replace('and', ' ').replace('of', ' ')
                parts = [p for p in cleaned.split() if p]
                if parts:
                    short_name = ''.join(p[0] for p in parts).upper()

            processed_sets.append({
                "code": code,
                "name": name,
                "shortName": short_name,
                "series": series,
                "count": s.get("count", s.get("total", 0)),
                "releaseDate": s.get("releaseDate"),
                "packs": s.get("packs", [])
            })

        # Sort sets
        def sort_key(s):
            return (s["series"], s["code"].startswith("P-"), s["code"])

        processed_sets.sort(key=sort_key)

        os.makedirs(os.path.dirname(EXPORT_SET_PATH), exist_ok=True)
        with open(EXPORT_SET_PATH, "w", encoding="utf-8") as f:
            json.dump(processed_sets, f, ensure_ascii=False, indent=4)

        print(f"[generate_sets] ✅ Wrote {len(processed_sets)} sets to {EXPORT_SET_PATH}")
        return processed_sets

    except Exception as e:
        print(f"[generate_sets] ❌ Error: {e}")
        return []


# (removed card generation; script now set-only)

# ===============================================================
# MAIN
# ===============================================================

def main():
    start = datetime.now()
    print("=== Pokémon TCG Pocket Data Generation ===")

    # Generate only set data
    generate_sets()

    print(f"✅ Completed in {datetime.now() - start}")

if __name__ == "__main__":
    main()

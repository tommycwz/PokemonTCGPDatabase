import json
import os
import re
from typing import Any, Dict, List


def load_reference(path: str) -> List[Dict[str, Any]]:
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, list):
        raise ValueError("reference.json is expected to be a JSON array of objects")
    return data


_URL_NUM_RE = re.compile(r"/cards/[^/]+/(\d+)(?:/|$)", re.IGNORECASE)


def extract_number_from_url(url: str) -> int:
    m = _URL_NUM_RE.search(url)
    if not m:
        raise ValueError(f"Cannot parse card number from url: {url}")
    return int(m.group(1))


def extract_number_from_carddef(card_def_key: str) -> int:
    # Fallback: PK_10_000030_00 -> (000030 // 10) + suffix
    parts = card_def_key.split("_")
    if len(parts) < 4:
        raise ValueError(f"Unexpected cardDefKey format: {card_def_key}")
    base_num = int(parts[2]) // 10
    suffix = int(parts[3])
    return base_num + suffix


def build_sync_map(ref_items: List[Dict[str, Any]]) -> Dict[str, str]:
    sync: Dict[str, str] = {}

    def get_expansion_from_value(v: str) -> str:
        # "A1-003" -> "A1"
        hyphen = v.find("-")
        return v[:hyphen] if hyphen != -1 else v

    def normalize_expansion(exp: str) -> str:
        s = (exp or "").strip()
        up = s.upper()
        # Map PROMO-x -> P-X
        if up.startswith("PROMO-"):
            return "P-" + up.split("-", 1)[1]
        return up

    for item in ref_items:
        card_def_key = item.get("cardDefKey")
        expansion_id = item.get("expansionId")
        url = item.get("url", "")
        if not card_def_key or not expansion_id:
            # skip invalid entries
            continue
        try:
            number = extract_number_from_url(url)
        except Exception:
            number = extract_number_from_carddef(card_def_key)

        # Normalize expansion: upper-case and PROMO-x -> P-X
        normalized_expansion = normalize_expansion(expansion_id)
        candidate_value = f"{normalized_expansion}-{number:03d}"

        if card_def_key not in sync:
            sync[card_def_key] = candidate_value
            continue

        # Duplicate rule: when duplicates exist for same key, do not take A4b.
        existing_value = sync[card_def_key]
        existing_expansion = get_expansion_from_value(existing_value).upper()

        if existing_expansion == "A4B" and normalized_expansion != "A4B":
            # Prefer non-A4b over A4b
            sync[card_def_key] = candidate_value
        elif existing_expansion != "A4B" and normalized_expansion == "A4B":
            # Keep existing non-A4b, skip A4b
            pass
        else:
            # If both are same preference (both A4b or both non-A4b), keep the first seen
            # Alternatively, choose the one with smaller card number; uncomment if needed.
            # if int(existing_value.split("-")[1]) > number:
            #     sync[card_def_key] = candidate_value
            pass

    return sync


def write_sync(path: str, mapping: Dict[str, str]) -> None:
    # Deterministic order: sort by expansion prefix + number + optional suffix, then card number, then key
    # Supports expansions like "A1", "A4B", etc.
    def sort_key(kv: tuple[str, str]):
        value = kv[1]  # e.g., "A1-003" or "A4B-123"
        m = re.match(r"([A-Za-z]+)(\d+)([A-Za-z]*)-(\d+)", value)
        if m:
            prefix = m.group(1).upper()
            num = int(m.group(2))
            suffix = m.group(3).upper()
            card_no = int(m.group(4))
            return (prefix, num, suffix, card_no, kv[0])
        # Fallback to value string order if pattern not matched
        return (value.upper(), 0, "", 0, kv[0])

    sorted_items = dict(sorted(mapping.items(), key=sort_key))
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(sorted_items, f, ensure_ascii=False, indent=2)


def main():
    root = os.path.dirname(os.path.dirname(__file__))
    ref_path = os.path.join(root, "misc", "reference.json")
    out_path = os.path.join(root, "release", "sync.json")
    ref_items = load_reference(ref_path)
    mapping = build_sync_map(ref_items)
    write_sync(out_path, mapping)
    print(f"Wrote {len(mapping)} entries to {out_path}")


if __name__ == "__main__":
    main()

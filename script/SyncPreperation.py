import json
import re
from pathlib import Path


def extract_set_and_number(url: str):
	# Normalize and split
	s = url.strip()
	s = s.strip("/")
	parts = [p for p in s.split("/") if p]

	if not parts:
		raise ValueError(f"Unexpected URL format: {url}")

	# If path contains 'cards', prefer segments immediately after it
	try:
		idx = parts.index("cards")
		if idx + 2 < len(parts):
			set_code = parts[idx + 1]
			number = parts[idx + 2]
		else:
			raise ValueError
	except ValueError:
		# General heuristic: take the first numeric segment; previous is set code
		set_code = None
		number = None
		for i, seg in enumerate(parts):
			if seg.isdigit():
				number = seg
				if i > 0:
					set_code = parts[i - 1]
				break
		if set_code is None or number is None:
			# Fallback: last two segments
			if len(parts) >= 2:
				set_code = parts[-2]
				number = parts[-1]
			else:
				raise ValueError(f"Unexpected URL format: {url}")

	digits = "".join(ch for ch in number if ch.isdigit())

	# Normalize promo set codes: PROMO-A -> P-A, PROMO-B -> P-B
	sc = set_code.upper()
	if sc.startswith("PROMO-"):
		sc = "P-" + sc.split("-", 1)[1]

	return sc, digits.zfill(3)


def build_sync_mapping(reference_data):
	mapping = {}

	if isinstance(reference_data, list):
		for item in reference_data:
			if not isinstance(item, dict):
				continue
			# Support multiple possible key names
			card_ref_key = (
				item.get("cardRefKey") or
				item.get("cardDefKey") or
				item.get("cardKey") or
				item.get("defKey")
			)
			url = item.get("url")
			if not card_ref_key or not url:
				continue
			set_code, padded_num = extract_set_and_number(url)
			mapping[card_ref_key] = f"{set_code}-{padded_num}"

	elif isinstance(reference_data, dict):
		for card_ref_key, value in reference_data.items():
			if isinstance(value, str):
				url = value
			elif isinstance(value, dict):
				url = value.get("url")
				# Prefer an explicit key in value if present
				card_ref_key = (
					value.get("cardRefKey") or
					value.get("cardDefKey") or
					value.get("cardKey") or
					value.get("defKey") or
					card_ref_key
				)
			else:
				continue

			if not card_ref_key or not url:
				continue

			set_code, padded_num = extract_set_and_number(url)
			mapping[card_ref_key] = f"{set_code}-{padded_num}"

	return mapping


def parse_reference_text(text: str):
	# Try standard JSON first
	try:
		data = json.loads(text)
		return data
	except json.JSONDecodeError:
		pass

	# Try NDJSON (one JSON object per line)
	lines = [ln for ln in text.splitlines() if ln.strip()]
	ndjson_items = []
	ndjson_ok = True
	for ln in lines:
		try:
			ndjson_items.append(json.loads(ln))
		except json.JSONDecodeError:
			ndjson_ok = False
			break
	if ndjson_ok and ndjson_items:
		return ndjson_items

	# Try concatenated JSON objects with a streaming decoder
	decoder = json.JSONDecoder()
	s = text.strip()
	idx = 0
	items = []
	while idx < len(s):
		try:
			obj, end = decoder.raw_decode(s, idx)
		except json.JSONDecodeError:
			break
		items.append(obj)
		idx = end
		# Skip whitespace between objects
		while idx < len(s) and s[idx].isspace():
			idx += 1
	if items:
		# If only one item, return it directly; else return list
		return items if len(items) > 1 else items[0]

	raise ValueError("Unable to parse reference.json in any known format")


def main():
	# Ensure paths are resolved from the project root, not the script folder
	project_root = Path(__file__).resolve().parent.parent
	primary_reference = project_root / "reference.json"
	fallback_reference = project_root / "misc" / "reference.json"
	reference_path = primary_reference if primary_reference.exists() else fallback_reference

	release_dir = project_root / "release"
	sync_path = release_dir / "sync.json"

	if not reference_path.exists():
		print(f"reference.json not found. Checked: {primary_reference} and {fallback_reference}")
		return

	try:
		text = reference_path.read_text(encoding="utf-8")
		reference_data = parse_reference_text(text)
	except Exception as e:
		print(f"Failed to parse reference.json: {e}")
		return

	mapping = build_sync_mapping(reference_data)

	# Fallback: extract pairs via regex if mapping is empty
	if not mapping:
		# Find blocks with key and url (cardRefKey or cardDefKey)
		pattern = re.compile(
			r"\{[^}]*\"(?:cardRefKey|cardDefKey|cardKey|defKey)\"\s*:\s*\"([^\"]+)\"[^}]*\"url\"\s*:\s*\"([^\"]+)\"[^}]*\}",
			re.DOTALL,
		)
		pairs = pattern.findall(text)
		for card_ref_key, url in pairs:
			try:
				set_code, padded_num = extract_set_and_number(url)
				mapping[card_ref_key] = f"{set_code}-{padded_num}"
			except Exception:
				continue
		print(f"Regex fallback extracted {len(pairs)} pairs; mapping now has {len(mapping)} items.")

	release_dir.mkdir(parents=True, exist_ok=True)

	# Sort output by mapped value (e.g., set-code then number)
	ordered_items = sorted(mapping.items(), key=lambda kv: kv[1])
	ordered_mapping = {k: v for k, v in ordered_items}

	with sync_path.open("w", encoding="utf-8") as f:
		json.dump(ordered_mapping, f, ensure_ascii=False, indent=2)

	print(f"Generated sync mapping for {len(mapping)} items at {sync_path}")


if __name__ == "__main__":
	main()
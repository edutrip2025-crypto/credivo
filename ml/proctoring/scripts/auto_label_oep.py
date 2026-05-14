from __future__ import annotations

import argparse
import csv
import re
from pathlib import Path


def extract_last_digit_stem(filename: str) -> int | None:
    stem = Path(filename).stem
    m = re.search(r"(\d)$", stem)
    if not m:
        return None
    return int(m.group(1))


def auto_label_row(modality: str, filename: str, existing_label: str) -> int:
    # OEP heuristic:
    # - video clip ending with "...1" => normal (0)
    # - video clip ending with "...2" => cheating (1)
    # - audio rows default to 0 for now unless manually overridden later.
    if str(existing_label).strip() in {"0", "1"}:
        base_label = int(existing_label)
    else:
        base_label = 0
    if modality != "video":
        return base_label
    d = extract_last_digit_stem(filename)
    if d == 2:
        return 1
    if d == 1:
        return 0
    return base_label


def main() -> None:
    parser = argparse.ArgumentParser(description="Auto-label OEP manifest into normal(0)/cheating(1).")
    parser.add_argument("--manifest", required=True, help="Input manifest CSV")
    parser.add_argument("--output", required=True, help="Output labeled manifest CSV")
    args = parser.parse_args()

    manifest = Path(args.manifest).resolve()
    if not manifest.exists():
        raise FileNotFoundError(f"Manifest not found: {manifest}")

    rows: list[dict] = []
    with manifest.open("r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        fieldnames = reader.fieldnames or []
        if not fieldnames:
            raise RuntimeError("Manifest has no header.")
        for r in reader:
            modality = str(r.get("modality", "")).strip().lower()
            filename = str(r.get("filename", "")).strip()
            existing_label = str(r.get("label", "")).strip()
            r["label"] = str(auto_label_row(modality, filename, existing_label))
            rows.append(r)

    out = Path(args.output).resolve()
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    total = len(rows)
    pos = sum(1 for x in rows if str(x.get("label", "0")) == "1")
    neg = total - pos
    print(f"wrote {out}")
    print(f"rows={total} label0={neg} label1={pos}")


if __name__ == "__main__":
    main()

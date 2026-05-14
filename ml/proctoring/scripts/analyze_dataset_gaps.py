from __future__ import annotations

import argparse
import csv
import json
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path


RISK_KEYWORDS: dict[str, tuple[str, ...]] = {
    "mobile_phone": ("phone", "mobile"),
    "reading_aloud": ("talk", "speaking", "read"),
    "multiple_person": ("multiple_person", "multiple", "person2", "person3"),
    "looking_away": ("looking_away", "lookaway", "away"),
    "side_glance": ("side_glance", "sideglance"),
}


def _row_label(row: dict[str, str]) -> int:
    raw = str(row.get("label", "")).strip()
    if raw in {"0", "1"}:
        return int(raw)
    path = str(row.get("path", "")).lower()
    return 1 if path.endswith("2.avi") else 0 if path.endswith("1.avi") else 0


def _keyword_tag(path_value: str) -> str | None:
    lowered = path_value.lower()
    for tag, words in RISK_KEYWORDS.items():
        if any(w in lowered for w in words):
            return tag
    return None


def _safe_pct(num: int, den: int) -> float:
    if den <= 0:
        return 0.0
    return round((num / den) * 100.0, 2)


def main() -> None:
    parser = argparse.ArgumentParser(description="Analyze local proctoring training dataset gaps.")
    parser.add_argument(
        "--manifest",
        default="data/proctoring/processed/manifest_labeled.csv",
        help="Manifest CSV path (fallback to manifest.csv if missing).",
    )
    parser.add_argument(
        "--output",
        default="data/proctoring/processed/dataset_gap_report.json",
        help="Output JSON path for coverage/gap report.",
    )
    parser.add_argument("--min-total", type=int, default=500, help="Minimum desired total samples.")
    parser.add_argument("--min-positive", type=int, default=180, help="Minimum desired suspicious samples.")
    parser.add_argument("--min-negative", type=int, default=180, help="Minimum desired clean samples.")
    parser.add_argument("--min-per-risk-tag", type=int, default=40, help="Minimum desired samples per risk tag.")
    args = parser.parse_args()

    manifest_path = Path(args.manifest).resolve()
    if not manifest_path.exists():
        fallback = manifest_path.parent / "manifest.csv"
        if fallback.exists():
            manifest_path = fallback.resolve()
        else:
            raise FileNotFoundError(f"Manifest not found: {manifest_path}")

    rows: list[dict[str, str]] = []
    with manifest_path.open("r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            if str(row.get("modality", "")).strip().lower() not in {"video", "image", "audio"}:
                continue
            rows.append(row)

    if not rows:
        raise RuntimeError(f"No usable media rows found in manifest: {manifest_path}")

    by_modality = Counter()
    by_label = Counter()
    by_modality_label: dict[str, Counter] = defaultdict(Counter)
    risk_tag_counts = Counter()
    unique_subjects = set()
    for row in rows:
        modality = str(row.get("modality", "")).strip().lower() or "unknown"
        label = _row_label(row)
        path_value = str(row.get("path", "")).strip()
        parent = str(row.get("parent", "")).strip().lower()
        by_modality[modality] += 1
        by_label[label] += 1
        by_modality_label[modality][label] += 1
        if parent.startswith("subject"):
            unique_subjects.add(parent)
        tag = _keyword_tag(path_value)
        if tag:
            risk_tag_counts[tag] += 1

    total = len(rows)
    positives = int(by_label.get(1, 0))
    negatives = int(by_label.get(0, 0))
    positive_ratio = _safe_pct(positives, total)

    gaps: list[str] = []
    if total < args.min_total:
        gaps.append(f"Total samples low ({total} < {args.min_total})")
    if positives < args.min_positive:
        gaps.append(f"Suspicious samples low ({positives} < {args.min_positive})")
    if negatives < args.min_negative:
        gaps.append(f"Clean samples low ({negatives} < {args.min_negative})")
    if positives and negatives:
        skew = max(positives, negatives) / max(1, min(positives, negatives))
        if skew > 2.5:
            gaps.append(f"Class imbalance high ({skew:.2f}x)")
    for tag in sorted(RISK_KEYWORDS.keys()):
        cnt = int(risk_tag_counts.get(tag, 0))
        if cnt < args.min_per_risk_tag:
            gaps.append(f"Risk tag '{tag}' under-covered ({cnt} < {args.min_per_risk_tag})")

    recommendations: list[str] = []
    if positives < args.min_positive:
        recommendations.append("Add more labeled suspicious samples: phone usage, reading aloud, and look-away.")
    if negatives < args.min_negative:
        recommendations.append("Add more clean baseline recordings across lighting/background variations.")
    if int(risk_tag_counts.get("mobile_phone", 0)) < args.min_per_risk_tag:
        recommendations.append("Add at least 40+ mobile-phone-in-frame samples from diverse camera angles.")
    if int(risk_tag_counts.get("reading_aloud", 0)) < args.min_per_risk_tag:
        recommendations.append("Add 40+ speaking/reading-aloud samples with varied noise conditions.")
    if len(unique_subjects) < 40:
        recommendations.append("Increase identity diversity (40+ unique subjects) to reduce overfitting.")

    report = {
        "manifest_path": str(manifest_path),
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "summary": {
            "total_samples": total,
            "positives": positives,
            "negatives": negatives,
            "positive_ratio_pct": positive_ratio,
            "unique_subject_count": len(unique_subjects),
        },
        "breakdown": {
            "by_modality": dict(by_modality),
            "by_label": {str(k): v for k, v in by_label.items()},
            "by_modality_label": {
                mod: {str(lbl): cnt for lbl, cnt in counts.items()}
                for mod, counts in by_modality_label.items()
            },
            "risk_tag_counts": dict(risk_tag_counts),
        },
        "thresholds": {
            "min_total": args.min_total,
            "min_positive": args.min_positive,
            "min_negative": args.min_negative,
            "min_per_risk_tag": args.min_per_risk_tag,
        },
        "gaps": gaps,
        "recommendations": recommendations,
    }

    out_path = Path(args.output).resolve()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(report, indent=2), encoding="utf-8")

    print(f"Dataset report -> {out_path}")
    print(json.dumps(report["summary"], indent=2))
    if gaps:
        print("Gaps detected:")
        for gap in gaps:
            print(f"- {gap}")
    else:
        print("No major gaps detected with current thresholds.")


if __name__ == "__main__":
    main()

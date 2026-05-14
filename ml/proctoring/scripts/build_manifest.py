from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd

VIDEO_EXTS = {".mp4", ".avi", ".mov", ".mkv", ".webm"}
IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".bmp"}
AUDIO_EXTS = {".wav", ".mp3", ".m4a", ".flac", ".ogg"}


def infer_label(path: Path) -> int:
    parts = [p.lower() for p in path.parts]
    joined = " ".join(parts)
    suspicious_keywords = [
        "cheat",
        "malpractice",
        "phone",
        "talk",
        "speaking",
        "copy",
        "suspicious",
        "unauthorized",
        "multiple_person",
        "looking_away",
    ]
    return 1 if any(k in joined for k in suspicious_keywords) else 0


def infer_modality(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix in VIDEO_EXTS:
        return "video"
    if suffix in IMAGE_EXTS:
        return "image"
    if suffix in AUDIO_EXTS:
        return "audio"
    return "other"


def main() -> None:
    parser = argparse.ArgumentParser(description="Build manifest for local proctoring training data.")
    parser.add_argument("--input", required=True, help="Root folder containing downloaded OEP dataset")
    parser.add_argument("--output", required=True, help="Output CSV path")
    args = parser.parse_args()

    root = Path(args.input).resolve()
    if not root.exists():
        raise FileNotFoundError(f"Input path not found: {root}")

    rows: list[dict] = []
    for p in root.rglob("*"):
        if not p.is_file():
            continue
        modality = infer_modality(p)
        if modality == "other":
            continue
        rows.append(
            {
                "path": str(p),
                "modality": modality,
                "label": infer_label(p),
                "parent": p.parent.name,
                "filename": p.name,
            },
        )

    if not rows:
        raise RuntimeError("No media files found. Check dataset path.")

    df = pd.DataFrame(rows).sort_values(["modality", "label", "path"]).reset_index(drop=True)
    out = Path(args.output).resolve()
    out.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(out, index=False)
    print(f"manifest rows={len(df)} -> {out}")
    print(df.groupby(["modality", "label"]).size())


if __name__ == "__main__":
    main()

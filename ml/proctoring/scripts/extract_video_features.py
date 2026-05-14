from __future__ import annotations

import argparse
from pathlib import Path

import cv2
import numpy as np
import pandas as pd
from tqdm import tqdm


def sample_frames(video_path: str, max_frames: int = 40) -> list[np.ndarray]:
    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        return []
    total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
    if total <= 0:
        cap.release()
        return []
    indices = np.linspace(0, max(total - 1, 1), num=min(max_frames, total), dtype=int)
    frames: list[np.ndarray] = []
    for idx in indices:
        cap.set(cv2.CAP_PROP_POS_FRAMES, int(idx))
        ok, frame = cap.read()
        if ok and frame is not None:
            frames.append(frame)
    cap.release()
    return frames


def frame_features(frame: np.ndarray) -> np.ndarray:
    frame = cv2.resize(frame, (320, 180))
    hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)

    h_mean = float(np.mean(hsv[:, :, 0]))
    s_mean = float(np.mean(hsv[:, :, 1]))
    v_mean = float(np.mean(hsv[:, :, 2]))
    v_std = float(np.std(hsv[:, :, 2]))
    edge = cv2.Canny(gray, 80, 160)
    edge_ratio = float(np.mean(edge > 0))
    return np.array([h_mean, s_mean, v_mean, v_std, edge_ratio], dtype=np.float32)


def aggregate_video_features(frames: list[np.ndarray]) -> np.ndarray | None:
    if not frames:
        return None
    feats = np.stack([frame_features(f) for f in frames], axis=0)
    return np.concatenate([np.mean(feats, axis=0), np.std(feats, axis=0)], axis=0)


def video_features(video_path: str, max_frames: int = 40) -> np.ndarray | None:
    frames = sample_frames(video_path, max_frames=max_frames)
    return aggregate_video_features(frames)


def main() -> None:
    parser = argparse.ArgumentParser(description="Extract baseline video features from manifest.")
    parser.add_argument("--manifest", required=True, help="Input manifest CSV from build_manifest.py")
    parser.add_argument("--output", required=True, help="Output features CSV")
    parser.add_argument("--max-frames", type=int, default=40)
    parser.add_argument(
        "--windows-per-video",
        type=int,
        default=1,
        help="Split each video into this many temporal windows and emit one row per window.",
    )
    args = parser.parse_args()

    df = pd.read_csv(args.manifest)
    df = df[df["modality"] == "video"].copy()
    if df.empty:
        raise RuntimeError("No video rows found in manifest.")

    rows: list[dict] = []
    for rec in tqdm(df.to_dict(orient="records"), desc="extract-video-features"):
        frames = sample_frames(rec["path"], max_frames=args.max_frames)
        if not frames:
            continue
        windows = max(1, int(args.windows_per_video))
        frame_chunks = np.array_split(np.arange(len(frames)), windows)
        chunk_idx = 0
        for chunk in frame_chunks:
            if len(chunk) == 0:
                continue
            chunk_frames = [frames[int(i)] for i in chunk]
            vec = aggregate_video_features(chunk_frames)
            if vec is None:
                continue
            row = {
                "path": f"{rec['path']}#w{chunk_idx:02d}",
                "label": int(rec["label"]),
            }
            for i, value in enumerate(vec.tolist()):
                row[f"f{i:02d}"] = float(value)
            rows.append(row)
            chunk_idx += 1

    out_df = pd.DataFrame(rows)
    if out_df.empty:
        raise RuntimeError("No features extracted.")
    out = Path(args.output).resolve()
    out.parent.mkdir(parents=True, exist_ok=True)
    out_df.to_csv(out, index=False)
    print(f"features rows={len(out_df)} -> {out}")


if __name__ == "__main__":
    main()

from __future__ import annotations

import argparse
import json
import socket
import subprocess
import sys
import time
import shutil
from pathlib import Path
from urllib.error import ContentTooShortError, HTTPError, URLError
from urllib.request import Request, urlopen


OPENSLR_PACKS = {
    "musan": [
        "https://www.openslr.org/resources/17/musan.tar.gz",
    ],
    "rirs_noises": [
        "https://www.openslr.org/resources/28/rirs_noises.zip",
    ],
    "librispeech_mini": [
        "https://www.openslr.org/resources/12/dev-clean.tar.gz",
        "https://www.openslr.org/resources/12/dev-other.tar.gz",
        "https://www.openslr.org/resources/12/test-clean.tar.gz",
        "https://www.openslr.org/resources/12/test-other.tar.gz",
        "https://www.openslr.org/resources/12/train-clean-100.tar.gz",
    ],
    "librispeech_full": [
        "https://www.openslr.org/resources/12/dev-clean.tar.gz",
        "https://www.openslr.org/resources/12/dev-other.tar.gz",
        "https://www.openslr.org/resources/12/test-clean.tar.gz",
        "https://www.openslr.org/resources/12/test-other.tar.gz",
        "https://www.openslr.org/resources/12/train-clean-100.tar.gz",
        "https://www.openslr.org/resources/12/train-clean-360.tar.gz",
        "https://www.openslr.org/resources/12/train-other-500.tar.gz",
    ],
}

HF_DATASETS = {
    "speech_commands": "google/speech_commands",
    "voxconverse": "diarizers-community/voxconverse",
}

KAGGLE_DATASETS = {
    "exam_cheating": "ardutraagiginting/exam-cheating-dataset",
    "oep": "raajanwankhade/oep-dataset",
}


def _print_progress(downloaded: int, total: int | None) -> None:
    downloaded_mb = downloaded / (1024 * 1024)
    if total:
        total_mb = total / (1024 * 1024)
        pct = min(downloaded * 100 / total, 100.0)
        print(
            f"\r  progress: {downloaded_mb:8.2f} MB / {total_mb:8.2f} MB ({pct:5.1f}%)",
            end="",
            flush=True,
        )
    else:
        print(f"\r  progress: {downloaded_mb:8.2f} MB", end="", flush=True)


def _download_once(url: str, target: Path, timeout: float, chunk_size: int) -> None:
    partial = target.with_suffix(target.suffix + ".part")
    req = Request(url, headers={"User-Agent": "certora-downloader/1.0"})
    with urlopen(req, timeout=timeout) as response, partial.open("wb") as handle:
        total = response.headers.get("Content-Length")
        total_bytes = int(total) if total else None
        downloaded = 0
        while True:
            chunk = response.read(chunk_size)
            if not chunk:
                break
            handle.write(chunk)
            downloaded += len(chunk)
            _print_progress(downloaded, total_bytes)
    print()
    partial.replace(target)


def _download_url(url: str, out_dir: Path, retries: int, timeout: float, chunk_size: int, force: bool) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    filename = url.split("/")[-1]
    target = out_dir / filename
    if force and target.exists():
        target.unlink()
    if target.exists() and target.stat().st_size > 0:
        print(f"skip existing: {target}")
        return target
    attempts = retries + 1
    for attempt in range(1, attempts + 1):
        print(f"downloading: {url}")
        print(f"target: {target}")
        try:
            _download_once(url, target, timeout=timeout, chunk_size=chunk_size)
            print(f"saved: {target}")
            return target
        except (ConnectionAbortedError, ConnectionResetError, TimeoutError, ContentTooShortError, HTTPError, URLError, OSError, socket.timeout) as exc:
            partial = target.with_suffix(target.suffix + ".part")
            if partial.exists():
                partial.unlink()
            if attempt >= attempts:
                raise RuntimeError(f"download failed after {attempts} attempts: {url}") from exc
            wait_seconds = min(2 ** (attempt - 1), 10)
            print(f"download attempt {attempt}/{attempts} failed: {exc}")
            print(f"retrying in {wait_seconds}s...")
            time.sleep(wait_seconds)
    raise RuntimeError(f"unreachable download state for: {url}")


def _run(cmd: list[str]) -> None:
    print(">", " ".join(cmd))
    subprocess.run(cmd, check=True)


def _resolve_kaggle_cmd() -> list[str]:
    kaggle_on_path = shutil.which("kaggle")
    if kaggle_on_path:
        return [kaggle_on_path]
    exe_dir = Path(sys.executable).resolve().parent
    candidates = [
        exe_dir / "kaggle.exe",
        exe_dir / "kaggle",
    ]
    for candidate in candidates:
        if candidate.exists():
            return [str(candidate)]
    raise RuntimeError("Kaggle CLI not found. Install kaggle in the active environment.")


def _download_hf(dataset_id: str, out_dir: Path) -> None:
    try:
        from huggingface_hub import snapshot_download
    except Exception as exc:  # pragma: no cover
        raise RuntimeError("huggingface_hub is required. pip install huggingface_hub") from exc
    out_dir.mkdir(parents=True, exist_ok=True)
    snapshot_download(
        repo_id=dataset_id,
        repo_type="dataset",
        local_dir=str(out_dir),
        local_dir_use_symlinks=False,
    )
    print(f"hf dataset downloaded: {dataset_id} -> {out_dir}")


def _dir_has_files(path: Path) -> bool:
    if not path.exists() or not path.is_dir():
        return False
    return any(path.rglob("*"))


def main() -> None:
    parser = argparse.ArgumentParser(description="Bulk downloader for proctoring audio datasets.")
    parser.add_argument("--root", default="data/proctoring/audio_pack", help="Root download directory")
    parser.add_argument(
        "--pack",
        default="all",
        choices=["all", "fast", "speech", "noise", "kaggle"],
        help="Preset pack selection",
    )
    parser.add_argument("--include-librispeech-full", action="store_true", help="Download full 1000h LibriSpeech")
    parser.add_argument("--skip-hf", action="store_true", help="Skip Hugging Face datasets")
    parser.add_argument("--skip-kaggle", action="store_true", help="Skip Kaggle datasets")
    parser.add_argument("--kaggle-unzip", action="store_true", help="Pass --unzip for Kaggle downloads")
    parser.add_argument("--retries", type=int, default=3, help="Retries for each direct file download")
    parser.add_argument("--timeout", type=float, default=30.0, help="Socket timeout in seconds for direct downloads")
    parser.add_argument("--chunk-size-mb", type=int, default=1, help="Chunk size in MB for progress updates")
    parser.add_argument("--force", action="store_true", help="Redownload files even if they already exist")
    args = parser.parse_args()

    root = Path(args.root).resolve()
    openslr_dir = root / "openslr"
    hf_dir = root / "huggingface"
    kaggle_dir = root / "kaggle"
    root.mkdir(parents=True, exist_ok=True)

    if args.pack == "all":
        openslr_targets = ["musan", "rirs_noises", "librispeech_mini"]
    elif args.pack == "fast":
        openslr_targets = ["musan", "rirs_noises"]
    elif args.pack == "speech":
        openslr_targets = ["librispeech_mini"]
    elif args.pack == "noise":
        openslr_targets = ["musan", "rirs_noises"]
    else:
        openslr_targets = []

    if args.include_librispeech_full and "librispeech_full" not in openslr_targets:
        openslr_targets.append("librispeech_full")

    downloaded = {"openslr": [], "huggingface": [], "kaggle": []}

    for key in openslr_targets:
        urls = OPENSLR_PACKS[key]
        dst = openslr_dir / key
        for u in urls:
            path = _download_url(
                u,
                dst,
                retries=max(args.retries, 0),
                timeout=max(args.timeout, 1.0),
                chunk_size=max(args.chunk_size_mb, 1) * 1024 * 1024,
                force=args.force,
            )
            downloaded["openslr"].append({"pack": key, "file": str(path)})

    if not args.skip_hf and args.pack in {"all", "fast", "speech"}:
        for name, ds in HF_DATASETS.items():
            out = hf_dir / name
            _download_hf(ds, out)
            downloaded["huggingface"].append({"name": name, "dataset": ds, "dir": str(out)})

    if not args.skip_kaggle and args.pack in {"all", "kaggle", "fast"}:
        kaggle_cmd = _resolve_kaggle_cmd()
        for name, ds in KAGGLE_DATASETS.items():
            out = kaggle_dir / name
            out.mkdir(parents=True, exist_ok=True)
            if not args.force and _dir_has_files(out):
                print(f"skip existing kaggle dataset dir: {out}")
                downloaded["kaggle"].append({"name": name, "dataset": ds, "dir": str(out), "skipped_existing": True})
                continue
            cmd = [*kaggle_cmd, "datasets", "download", "-d", ds, "-p", str(out)]
            if args.kaggle_unzip:
                cmd.append("--unzip")
            try:
                _run(cmd)
                downloaded["kaggle"].append({"name": name, "dataset": ds, "dir": str(out)})
            except Exception as exc:
                print(f"kaggle download failed for {ds}: {exc}")

    manifest_path = root / "download_manifest.json"
    manifest_path.write_text(json.dumps(downloaded, indent=2), encoding="utf-8")
    print(f"manifest -> {manifest_path}")
    print("done")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\ninterrupted")
        sys.exit(130)

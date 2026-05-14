# Local Proctoring Training (Temporary Setup)

This setup is fully local and isolated from your app backend runtime.

## 1) Create isolated environment

From `D:\certora`:

```powershell
python -m venv .venv-proctoring
.\.venv-proctoring\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r ml\proctoring\requirements.txt
```

## 2) Download dataset locally (Kaggle CLI)

Install and configure Kaggle API once:

```powershell
pip install kaggle
```

Place `kaggle.json` at:
- `C:\Users\<your-user>\.kaggle\kaggle.json`

Download:

```powershell
mkdir data\proctoring\raw -Force
kaggle datasets download -d raajanwankhade/oep-dataset -p data\proctoring\raw --unzip
```

## 3) Build manifest

```powershell
python ml\proctoring\scripts\build_manifest.py `
  --input data\proctoring\raw `
  --output data\proctoring\processed\manifest.csv
```

## 4) Extract baseline video features

```powershell
python ml\proctoring\scripts\extract_video_features.py `
  --manifest data\proctoring\processed\manifest.csv `
  --output data\proctoring\processed\video_features.csv `
  --max-frames 40
```

## 5) Train baseline model

```powershell
python ml\proctoring\scripts\train_baseline.py `
  --features data\proctoring\processed\video_features.csv `
  --model-out data\proctoring\models\proctor_risk_baseline.joblib `
  --metrics-out data\proctoring\models\metrics.json
```

## 6) Supervised training (with true cheating label=1)

This flow auto-labels OEP clips where filename ends with `...2` as cheating (`1`) and `...1` as normal (`0`) for video rows.

```powershell
python ml\proctoring\scripts\auto_label_oep.py `
  --manifest data\proctoring\processed\manifest.csv `
  --output data\proctoring\processed\manifest_labeled.csv
```

```powershell
python ml\proctoring\scripts\extract_video_features.py `
  --manifest data\proctoring\processed\manifest_labeled.csv `
  --output data\proctoring\processed\video_features_labeled.csv `
  --max-frames 40
```

Install optional models:

```powershell
pip install -r ml\proctoring\requirements-optional.txt
```

Train logistic + XGBoost + CNN (if optional deps are present):

```powershell
python ml\proctoring\scripts\train_supervised_models.py `
  --features data\proctoring\processed\video_features_labeled.csv `
  --out-dir data\proctoring\models\supervised
```

## 7) Bulk audio dataset pack (for stronger voice cheating detection)

Install helper deps:

```powershell
pip install huggingface_hub kaggle
```

Fast pack (noise + core speech + Kaggle):

```powershell
python ml\proctoring\scripts\download_audio_data_pack.py `
  --root data\proctoring\audio_pack `
  --pack fast `
  --kaggle-unzip
```

Large pack (adds LibriSpeech mini + HF datasets):

```powershell
python ml\proctoring\scripts\download_audio_data_pack.py `
  --root data\proctoring\audio_pack `
  --pack all `
  --kaggle-unzip
```

Max pack (includes full 1000h LibriSpeech):

```powershell
python ml\proctoring\scripts\download_audio_data_pack.py `
  --root data\proctoring\audio_pack `
  --pack all `
  --include-librispeech-full `
  --kaggle-unzip
```

This script pulls from:
- OpenSLR: MUSAN, RIRS_NOISES, LibriSpeech
- Hugging Face datasets: `google/speech_commands`, `diarizers-community/voxconverse`
- Kaggle: `exam-cheating-dataset`, `oep-dataset`

It writes a dataset manifest at:
- `data/proctoring/audio_pack/download_manifest.json`

## 8) Dataset gap analysis (before retraining)

Run this before every training cycle to see class/risk-tag coverage gaps:

```powershell
python ml\proctoring\scripts\analyze_dataset_gaps.py `
  --manifest data\proctoring\processed\manifest_labeled.csv `
  --output data\proctoring\processed\dataset_gap_report.json
```

The report includes:
- class balance (`label=0` vs `label=1`)
- risk-tag coverage (phone, reading aloud, look-away, etc.)
- minimum-threshold gaps and recommendations

## 9) Curated hard-negative ingestion (real sessions)

Use admin API to ingest false-positive sessions (model marked suspicious, reviewer marked incorrect) into:

- `data/proctoring/processed/hard_negatives.json`

This dataset is consumed automatically during training with elevated weight so the model reduces false positives over time.

Example:

```http
POST /proctoring/admin/hard-negatives/ingest
{
  "lookback_days": 45,
  "limit": 1000,
  "min_model_probability": 0.45,
  "include_preview_sessions": false
}
```

## Outputs

- Model: `data/proctoring/models/proctor_risk_baseline.joblib`
- Metrics: `data/proctoring/models/metrics.json`
- Supervised bundle: `data/proctoring/models/supervised/supervised_bundle.joblib`
- Holdout metrics: `data/proctoring/models/supervised/evaluation_report.json`
- Conservative policy rules: `data/proctoring/models/supervised/deduction_rules.json`
- Dataset gap report: `data/proctoring/processed/dataset_gap_report.json`

## Cost / storage note

- This is local only.
- No dataset is stored in DB.
- You can delete all training data anytime:

```powershell
powershell -ExecutionPolicy Bypass -File ml\proctoring\scripts\cleanup_local_training_data.ps1
```

This removes `data\proctoring`.

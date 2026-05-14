from __future__ import annotations

import argparse
import json
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from sklearn.compose import ColumnTransformer
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import accuracy_score, classification_report, roc_auc_score
from sklearn.model_selection import train_test_split
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler
from sklearn.ensemble import IsolationForest


def main() -> None:
    parser = argparse.ArgumentParser(description="Train baseline proctor risk model from extracted features.")
    parser.add_argument("--features", required=True, help="Features CSV from extract_video_features.py")
    parser.add_argument("--model-out", required=True, help="Output .joblib path")
    parser.add_argument("--metrics-out", required=True, help="Output metrics JSON path")
    args = parser.parse_args()

    df = pd.read_csv(args.features)
    if df.empty:
        raise RuntimeError("Features file is empty.")
    feature_cols = [c for c in df.columns if c.startswith("f")]
    if not feature_cols:
        raise RuntimeError("No feature columns found.")

    X = df[feature_cols]
    y = df["label"].astype(int)
    unique_classes = np.unique(y)
    X_train, X_test, y_train, y_test = train_test_split(
        X,
        y,
        test_size=0.2,
        random_state=42,
        stratify=y if len(unique_classes) > 1 else None,
    )

    pre = ColumnTransformer(
        transformers=[
            (
                "num",
                Pipeline(
                    steps=[
                        ("imputer", SimpleImputer(strategy="median")),
                        ("scaler", StandardScaler()),
                    ],
                ),
                feature_cols,
            ),
        ],
    )
    if len(unique_classes) > 1:
        clf = LogisticRegression(max_iter=1000, class_weight="balanced")
        pipe = Pipeline([("pre", pre), ("clf", clf)])
        pipe.fit(X_train, y_train)

        pred = pipe.predict(X_test)
        proba = pipe.predict_proba(X_test)[:, 1] if len(np.unique(y_train)) > 1 else np.zeros(len(y_test))
        metrics = {
            "model_type": "logistic_regression",
            "supervised": True,
            "accuracy": float(accuracy_score(y_test, pred)),
            "roc_auc": float(roc_auc_score(y_test, proba)) if len(np.unique(y_test)) > 1 else None,
            "report": classification_report(y_test, pred, output_dict=True, zero_division=0),
            "rows_total": int(len(df)),
            "rows_train": int(len(X_train)),
            "rows_test": int(len(X_test)),
            "features": feature_cols,
            "class_distribution": {str(int(k)): int((y == k).sum()) for k in unique_classes},
        }
    else:
        # Fallback when only one class is available: train anomaly detector on "normal" samples.
        pre.fit(X_train)
        X_train_t = pre.transform(X_train)
        X_test_t = pre.transform(X_test)
        iso = IsolationForest(
            n_estimators=300,
            contamination=0.1,
            random_state=42,
        )
        iso.fit(X_train_t)
        # IsolationForest: 1 normal, -1 anomaly
        pred_raw = iso.predict(X_test_t)
        pred = np.where(pred_raw == 1, 0, 1)
        model = {"pre": pre, "clf": iso, "mode": "one_class"}
        pipe = model
        metrics = {
            "model_type": "isolation_forest",
            "supervised": False,
            "note": "Only one class found in labels. Trained one-class anomaly detector.",
            "pseudo_anomaly_rate_on_test": float(np.mean(pred == 1)),
            "rows_total": int(len(df)),
            "rows_train": int(len(X_train)),
            "rows_test": int(len(X_test)),
            "features": feature_cols,
            "class_distribution": {str(int(k)): int((y == k).sum()) for k in unique_classes},
        }

    model_out = Path(args.model_out).resolve()
    model_out.parent.mkdir(parents=True, exist_ok=True)
    joblib.dump(pipe, model_out)

    metrics_out = Path(args.metrics_out).resolve()
    metrics_out.parent.mkdir(parents=True, exist_ok=True)
    metrics_out.write_text(json.dumps(metrics, indent=2), encoding="utf-8")

    print(f"model -> {model_out}")
    print(f"metrics -> {metrics_out}")
    if metrics.get("supervised"):
        print(f"accuracy={metrics['accuracy']:.4f} roc_auc={metrics['roc_auc']}")
    else:
        print(f"pseudo_anomaly_rate_on_test={metrics['pseudo_anomaly_rate_on_test']:.4f}")


if __name__ == "__main__":
    main()

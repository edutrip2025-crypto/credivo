from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import joblib
import numpy as np
import pandas as pd
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import confusion_matrix, precision_score, recall_score, roc_auc_score
from sklearn.model_selection import StratifiedGroupKFold, train_test_split
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

try:
    from tqdm import trange
except Exception:  # pragma: no cover
    trange = None

try:
    from xgboost import XGBClassifier  # type: ignore
except Exception:  # pragma: no cover
    XGBClassifier = None

try:
    import torch
    import torch.nn as nn
except Exception:  # pragma: no cover
    torch = None
    nn = None


def calc_metrics(y_true: np.ndarray, prob: np.ndarray, threshold: float) -> dict[str, float]:
    y_pred = (prob >= threshold).astype(int)
    tn, fp, fn, tp = confusion_matrix(y_true, y_pred, labels=[0, 1]).ravel()
    precision = precision_score(y_true, y_pred, zero_division=0)
    recall = recall_score(y_true, y_pred, zero_division=0)
    fpr = fp / max(fp + tn, 1)
    return {
        "threshold": float(threshold),
        "precision": float(precision),
        "recall": float(recall),
        "fpr": float(fpr),
        "tp": int(tp),
        "fp": int(fp),
        "tn": int(tn),
        "fn": int(fn),
    }


def pick_conservative_threshold(y_true: np.ndarray, prob: np.ndarray) -> dict[str, float]:
    best: dict[str, float] | None = None
    for t in np.linspace(0.5, 0.95, 19):
        m = calc_metrics(y_true, prob, float(t))
        if m["precision"] >= 0.90 and m["fpr"] <= 0.08:
            if best is None or m["recall"] > best["recall"]:
                best = m
    if best is None:
        # fallback to stricter threshold even if recall drops
        candidates = [calc_metrics(y_true, prob, float(t)) for t in np.linspace(0.6, 0.98, 20)]
        candidates.sort(key=lambda x: (x["fpr"], -x["precision"], -x["recall"]))
        best = candidates[0]
    return best


def train_logistic(X_train: np.ndarray, y_train: np.ndarray) -> Any:
    model = LogisticRegression(max_iter=2000, class_weight="balanced")
    model.fit(X_train, y_train)
    return model


def train_xgb(
    X_train: np.ndarray,
    y_train: np.ndarray,
    n_estimators: int,
    max_depth: int,
    learning_rate: float,
) -> Any | None:
    if XGBClassifier is None:
        return None
    model = XGBClassifier(
        n_estimators=n_estimators,
        max_depth=max_depth,
        learning_rate=learning_rate,
        subsample=0.9,
        colsample_bytree=0.9,
        reg_lambda=1.0,
        eval_metric="logloss",
        random_state=42,
    )
    model.fit(X_train, y_train)
    return model


if nn is not None:
    class TinyCNN(nn.Module):  # type: ignore[misc]
        def __init__(self, n_features: int):
            super().__init__()
            self.net = nn.Sequential(
                nn.Conv1d(1, 16, kernel_size=3, padding=1),
                nn.ReLU(),
                nn.Conv1d(16, 32, kernel_size=3, padding=1),
                nn.ReLU(),
                nn.AdaptiveAvgPool1d(8),
                nn.Flatten(),
                nn.Linear(32 * 8, 32),
                nn.ReLU(),
                nn.Linear(32, 1),
            )

        def forward(self, x):
            return self.net(x)


def train_cnn(
    X_train: np.ndarray,
    y_train: np.ndarray,
    X_val: np.ndarray,
    y_val: np.ndarray,
    epochs: int,
    lr: float,
) -> dict[str, Any] | None:
    if torch is None or nn is None:
        return None
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    xtr = torch.tensor(X_train, dtype=torch.float32, device=device).unsqueeze(1)
    ytr = torch.tensor(y_train, dtype=torch.float32, device=device).unsqueeze(1)
    xva = torch.tensor(X_val, dtype=torch.float32, device=device).unsqueeze(1)
    n_features = X_train.shape[1]

    model = TinyCNN(n_features).to(device)
    opt = torch.optim.Adam(model.parameters(), lr=lr)
    loss_fn = nn.BCEWithLogitsLoss()

    model.train()
    loop = trange(epochs, desc="cnn-train", leave=False) if trange is not None else range(epochs)
    for _ in loop:
        opt.zero_grad()
        logits = model(xtr)
        loss = loss_fn(logits, ytr)
        loss.backward()
        opt.step()

    model.eval()
    with torch.no_grad():
        logits = model(xva)
        prob = torch.sigmoid(logits).squeeze(1).cpu().numpy()
    return {"model": model.cpu(), "prob": prob}


def main() -> None:
    parser = argparse.ArgumentParser(description="Train supervised proctor models and export conservative policy.")
    parser.add_argument("--features", required=True, help="Feature CSV with label column")
    parser.add_argument("--out-dir", required=True, help="Output directory")
    parser.add_argument("--test-size", type=float, default=0.2, help="Holdout split ratio")
    parser.add_argument("--random-state", type=int, default=42, help="Random seed")
    parser.add_argument("--xgb-estimators", type=int, default=300, help="XGBoost number of trees")
    parser.add_argument("--xgb-max-depth", type=int, default=4, help="XGBoost max tree depth")
    parser.add_argument("--xgb-learning-rate", type=float, default=0.05, help="XGBoost learning rate")
    parser.add_argument("--cnn-epochs", type=int, default=40, help="CNN training epochs")
    parser.add_argument("--cnn-lr", type=float, default=1e-3, help="CNN learning rate")
    parser.add_argument(
        "--disable-group-split",
        action="store_true",
        help="Disable group-aware split (not recommended when using video window augmentation).",
    )
    args = parser.parse_args()

    df = pd.read_csv(args.features)
    if "label" not in df.columns:
        raise RuntimeError("Features CSV must contain 'label'")
    feature_cols = [c for c in df.columns if c.startswith("f")]
    if not feature_cols:
        raise RuntimeError("No feature columns found.")

    y = df["label"].astype(int).to_numpy()
    if len(np.unique(y)) < 2:
        raise RuntimeError("Need both classes (0 and 1) for supervised training.")

    X = df[feature_cols].to_numpy()
    split_meta: dict[str, Any] = {"group_split_used": False}
    if (not args.disable_group_split) and "path" in df.columns:
        base_path = (
            df["path"]
            .astype(str)
            .str.replace(r"#w\d+$", "", regex=True)
            .to_numpy()
        )
        n_splits = max(2, min(5, int(round(1.0 / max(args.test_size, 0.05)))))
        sgkf = StratifiedGroupKFold(n_splits=n_splits, shuffle=True, random_state=args.random_state)
        train_idx, test_idx = next(sgkf.split(X, y, groups=base_path))
        X_train, X_test = X[train_idx], X[test_idx]
        y_train, y_test = y[train_idx], y[test_idx]
        split_meta = {
            "group_split_used": True,
            "group_column": "path(base video id)",
            "groups_train": int(len(np.unique(base_path[train_idx]))),
            "groups_test": int(len(np.unique(base_path[test_idx]))),
            "rows_train": int(len(train_idx)),
            "rows_test": int(len(test_idx)),
        }
    else:
        X_train, X_test, y_train, y_test = train_test_split(
            X,
            y,
            test_size=args.test_size,
            random_state=args.random_state,
            stratify=y,
        )

    pre = Pipeline(
        [
            ("imputer", SimpleImputer(strategy="median")),
            ("scaler", StandardScaler()),
        ],
    )
    X_train_t = pre.fit_transform(X_train)
    X_test_t = pre.transform(X_test)

    artifacts: dict[str, Any] = {}
    reports: dict[str, Any] = {}

    # Logistic
    lr = train_logistic(X_train_t, y_train)
    lr_prob = lr.predict_proba(X_test_t)[:, 1]
    lr_auc = roc_auc_score(y_test, lr_prob)
    lr_pick = pick_conservative_threshold(y_test, lr_prob)
    reports["logistic"] = {"roc_auc": float(lr_auc), "selected": lr_pick}
    artifacts["logistic"] = lr

    # XGBoost (optional)
    if XGBClassifier is not None:
        xgb = train_xgb(
            X_train_t,
            y_train,
            n_estimators=max(50, args.xgb_estimators),
            max_depth=max(2, args.xgb_max_depth),
            learning_rate=max(0.005, args.xgb_learning_rate),
        )
        if xgb is not None:
            xgb_prob = xgb.predict_proba(X_test_t)[:, 1]
            xgb_auc = roc_auc_score(y_test, xgb_prob)
            xgb_pick = pick_conservative_threshold(y_test, xgb_prob)
            reports["xgboost"] = {"roc_auc": float(xgb_auc), "selected": xgb_pick}
            artifacts["xgboost"] = xgb
    else:
        reports["xgboost"] = {"skipped": True, "reason": "xgboost not installed"}

    # CNN (optional torch)
    if torch is not None and nn is not None:
        cnn_out = train_cnn(
            X_train_t,
            y_train,
            X_test_t,
            y_test,
            epochs=max(10, args.cnn_epochs),
            lr=max(1e-5, args.cnn_lr),
        )
        if cnn_out is not None:
            cnn_prob = cnn_out["prob"]
            cnn_auc = roc_auc_score(y_test, cnn_prob)
            cnn_pick = pick_conservative_threshold(y_test, cnn_prob)
            reports["cnn"] = {"roc_auc": float(cnn_auc), "selected": cnn_pick}
            artifacts["cnn"] = cnn_out["model"]
    else:
        reports["cnn"] = {"skipped": True, "reason": "torch not installed"}

    # choose best by precision first, then recall, then lowest fpr
    scored: list[tuple[str, dict[str, float]]] = []
    for name, rep in reports.items():
        if "selected" in rep:
            scored.append((name, rep["selected"]))
    scored.sort(key=lambda x: (-x[1]["precision"], -x[1]["recall"], x[1]["fpr"]))
    best_name, best_sel = scored[0]

    # Conservative policy:
    # only allow automatic score deductions after sufficient holdout validation size.
    min_holdout_for_auto_deduction = 100
    auto_deduction = bool(
        len(y_test) >= min_holdout_for_auto_deduction
        and best_sel["precision"] >= 0.95
        and best_sel["fpr"] <= 0.02
        and best_sel["recall"] >= 0.60
    )
    rules = {
        "model": best_name,
        "manual_review_threshold": float(best_sel["threshold"]),
        "warning_threshold": float(max(0.45, best_sel["threshold"] - 0.15)),
        "critical_threshold": float(min(0.98, best_sel["threshold"] + 0.12)),
        "auto_deduction_enabled": auto_deduction,
        "deduction_policy": {
            "per_warning_pct": 2 if auto_deduction else 0,
            "high_risk_event_pct": 5 if auto_deduction else 0,
            "max_total_deduction_pct": 12 if auto_deduction else 0,
        },
        "guardrails": {
            "require_two_signals": True,
            "require_min_confidence": 0.70,
            "always_manual_review_if_critical": True,
            "min_holdout_for_auto_deduction": min_holdout_for_auto_deduction,
        },
    }

    out_dir = Path(args.out_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    joblib.dump({"pre": pre, "models": artifacts}, out_dir / "supervised_bundle.joblib")
    (out_dir / "evaluation_report.json").write_text(
        json.dumps(
            {
                "rows_total": int(len(df)),
                "rows_train": int(len(X_train)),
                "rows_test": int(len(X_test)),
                "split": split_meta,
                "class_distribution": {str(int(k)): int((y == k).sum()) for k in np.unique(y)},
                "reports": reports,
                "chosen_model": best_name,
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    (out_dir / "deduction_rules.json").write_text(json.dumps(rules, indent=2), encoding="utf-8")

    print(f"bundle -> {out_dir / 'supervised_bundle.joblib'}")
    print(f"report -> {out_dir / 'evaluation_report.json'}")
    print(f"rules  -> {out_dir / 'deduction_rules.json'}")
    print(f"chosen_model={best_name} precision={best_sel['precision']:.4f} recall={best_sel['recall']:.4f} fpr={best_sel['fpr']:.4f}")
    print(f"auto_deduction_enabled={rules['auto_deduction_enabled']}")


if __name__ == "__main__":
    main()

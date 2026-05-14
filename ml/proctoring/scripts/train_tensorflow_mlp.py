import json
from pathlib import Path
import numpy as np
import pandas as pd
import tensorflow as tf
from sklearn.model_selection import StratifiedGroupKFold
from sklearn.preprocessing import StandardScaler
from sklearn.metrics import roc_auc_score, precision_score, recall_score, f1_score

df = pd.read_csv("data/proctoring/processed/video_features_labeled.csv")
feat = [c for c in df.columns if c.startswith("f")]
X = df[feat].to_numpy(dtype=np.float32)
y = df["label"].astype(int).to_numpy()
groups = df["path"].astype(str).str.replace(r"#w\d+$","",regex=True).to_numpy()

sgkf = StratifiedGroupKFold(n_splits=5, shuffle=True, random_state=42)
tr, te = next(sgkf.split(X,y,groups=groups))
X_train, X_test, y_train, y_test = X[tr], X[te], y[tr], y[te]

sc = StandardScaler()
X_train = sc.fit_transform(X_train).astype(np.float32)
X_test = sc.transform(X_test).astype(np.float32)

m = tf.keras.Sequential([
    tf.keras.layers.Input(shape=(X_train.shape[1],)),
    tf.keras.layers.Dense(128, activation="relu"),
    tf.keras.layers.Dropout(0.25),
    tf.keras.layers.Dense(64, activation="relu"),
    tf.keras.layers.Dropout(0.20),
    tf.keras.layers.Dense(1, activation="sigmoid"),
])
m.compile(optimizer=tf.keras.optimizers.Adam(1e-3), loss="binary_crossentropy", metrics=[tf.keras.metrics.AUC(name="auc")])
m.fit(X_train, y_train, validation_split=0.2, epochs=600, batch_size=32, verbose=2,
      callbacks=[tf.keras.callbacks.EarlyStopping(monitor="val_auc", mode="max", patience=50, restore_best_weights=True)])

p = m.predict(X_test, verbose=0).reshape(-1)
pred = (p >= 0.5).astype(int)

out = Path("data/proctoring/models/tensorflow")
out.mkdir(parents=True, exist_ok=True)
m.save(out / "proctor_tf.keras")
metrics = {
    "roc_auc": float(roc_auc_score(y_test, p)),
    "precision@0.5": float(precision_score(y_test, pred, zero_division=0)),
    "recall@0.5": float(recall_score(y_test, pred, zero_division=0)),
    "f1@0.5": float(f1_score(y_test, pred, zero_division=0)),
    "rows_train": int(len(X_train)),
    "rows_test": int(len(X_test)),
}
(out / "metrics.json").write_text(json.dumps(metrics, indent=2), encoding="utf-8")
print(json.dumps(metrics, indent=2))

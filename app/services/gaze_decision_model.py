"""
Three-layer gaze / attention decision model (implemented primarily in `app/web/assets/app.js`).

Layer 1 — raw observations (per tick, throttled logs)
    Normalized face landmarks → UI zone labels relative to calibration:
    primary (question band), secondary (options band), tertiary (timer / chrome band),
    neutral (padding), suspicious (elsewhere). Also: cluster key for spatial consistency,
    gaze variance for static-vs-reading heuristic.

Layer 2 — suspicion events (incremental points, debounced)
    Examples: long dwell in suspicious zone, repeated entries to same cluster,
    low-variance gaze in suspicious zone, correct answer shortly after suspicion
    (extra weight when question marks ≥ 2), same dominant cluster across 3 consecutive questions.

Layer 3 — rolling window + thresholds (~120s)
    Sum of points in window maps to:
      3–4  → silent log (gaze_suspicion_silent_log)
      5–6  → internal signal (gaze_suspicion_internal)
      7–8  → soft toast + log (gaze_soft_attention_notice); no modal
      9+   → review flag + one formal warning (gaze_pattern_review_flag)

Server-side, `proctoring_ai.evaluate_proctor_session` ingests logged `ProctorEvent` rows;
see `_weighted_event_signals` for weights on gaze-related event types.

Principles: grace period after question changes, no immediate “looked away once” warnings,
repeated off-UI cluster dependency matters more than a single glance.
"""

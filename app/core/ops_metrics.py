from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone
from threading import Lock


class OpsMetrics:
    def __init__(self) -> None:
        self._lock = Lock()
        self._started_at = datetime.now(timezone.utc)
        self._total_requests = 0
        self._total_errors = 0
        self._status_counts: dict[int, int] = defaultdict(int)
        self._route_counts: dict[str, int] = defaultdict(int)
        self._route_error_counts: dict[str, int] = defaultdict(int)
        self._route_latency_ms_total: dict[str, float] = defaultdict(float)

    def record(self, *, route: str, status_code: int, latency_ms: float) -> None:
        safe_route = str(route or "/")
        ms = float(max(0.0, latency_ms))
        with self._lock:
            self._total_requests += 1
            self._status_counts[int(status_code)] += 1
            self._route_counts[safe_route] += 1
            self._route_latency_ms_total[safe_route] += ms
            if int(status_code) >= 500:
                self._total_errors += 1
                self._route_error_counts[safe_route] += 1

    def snapshot(self) -> dict:
        with self._lock:
            total = int(self._total_requests)
            error_rate_pct = round((self._total_errors / total) * 100.0, 2) if total > 0 else 0.0
            routes = []
            for route, count in sorted(self._route_counts.items(), key=lambda kv: kv[1], reverse=True)[:30]:
                total_latency = self._route_latency_ms_total.get(route, 0.0)
                routes.append(
                    {
                        "route": route,
                        "requests": int(count),
                        "errors_5xx": int(self._route_error_counts.get(route, 0)),
                        "avg_latency_ms": round(total_latency / max(1, count), 2),
                    },
                )
            return {
                "started_at": self._started_at.isoformat(),
                "uptime_seconds": int((datetime.now(timezone.utc) - self._started_at).total_seconds()),
                "totals": {
                    "requests": total,
                    "errors_5xx": int(self._total_errors),
                    "error_rate_pct": error_rate_pct,
                },
                "status_counts": {str(k): int(v) for k, v in sorted(self._status_counts.items())},
                "routes_top": routes,
            }

    def reset(self) -> dict:
        with self._lock:
            self._started_at = datetime.now(timezone.utc)
            self._total_requests = 0
            self._total_errors = 0
            self._status_counts.clear()
            self._route_counts.clear()
            self._route_error_counts.clear()
            self._route_latency_ms_total.clear()
        return self.snapshot()


ops_metrics = OpsMetrics()

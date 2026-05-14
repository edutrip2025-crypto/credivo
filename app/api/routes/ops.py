from datetime import datetime
import csv
import io

from fastapi import APIRouter, Depends, Query, Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import require_role
from app.core.ops_metrics import ops_metrics
from app.db.session import get_db
from app.models.entities import AuditLog, User, UserRole

router = APIRouter(prefix="/admin/ops", tags=["admin-ops"])


@router.get("/metrics")
def admin_ops_metrics(
    current_user: User = Depends(require_role(UserRole.ADMIN)),
):
    return ops_metrics.snapshot()


@router.post("/metrics/reset")
def admin_ops_metrics_reset(
    current_user: User = Depends(require_role(UserRole.ADMIN)),
):
    return {"status": "ok", "metrics": ops_metrics.reset()}


@router.get("/metrics/export.csv")
def admin_ops_metrics_export_csv(
    current_user: User = Depends(require_role(UserRole.ADMIN)),
):
    snap = ops_metrics.snapshot()
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["started_at", snap.get("started_at", "")])
    writer.writerow(["uptime_seconds", snap.get("uptime_seconds", 0)])
    totals = snap.get("totals", {})
    writer.writerow(["total_requests", totals.get("requests", 0)])
    writer.writerow(["errors_5xx", totals.get("errors_5xx", 0)])
    writer.writerow(["error_rate_pct", totals.get("error_rate_pct", 0)])
    writer.writerow([])
    writer.writerow(["route", "requests", "errors_5xx", "avg_latency_ms"])
    for row in snap.get("routes_top", []):
        writer.writerow([row.get("route", ""), row.get("requests", 0), row.get("errors_5xx", 0), row.get("avg_latency_ms", 0)])
    return Response(
        content=output.getvalue(),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=ops_metrics.csv"},
    )


@router.get("/audit/recent")
def admin_ops_audit_recent(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.ADMIN)),
    action: str | None = Query(default=None),
    target_type: str | None = Query(default=None),
    actor_user_id: int | None = Query(default=None),
    since_iso: str | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
):
    q = select(AuditLog).order_by(AuditLog.created_at.desc())
    if action:
        q = q.where(AuditLog.action == action.strip())
    if target_type:
        q = q.where(AuditLog.target_type == target_type.strip())
    if actor_user_id:
        q = q.where(AuditLog.actor_user_id == int(actor_user_id))
    if since_iso:
        try:
            dt = datetime.fromisoformat(str(since_iso).replace("Z", "+00:00"))
            q = q.where(AuditLog.created_at >= dt)
        except ValueError:
            pass
    items = list(db.scalars(q.limit(limit)).all())
    return {
        "count": len(items),
        "items": [
            {
                "id": it.id,
                "actor_user_id": it.actor_user_id,
                "action": it.action,
                "target_type": it.target_type,
                "target_id": it.target_id,
                "details_json": it.details_json or {},
                "created_at": it.created_at,
            }
            for it in items
        ],
    }

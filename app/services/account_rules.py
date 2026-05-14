from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models.entities import ApprovalStatus, User, UserApproval, UserRole
from app.services.firebase_auth import get_firebase_uid_by_email, set_firebase_custom_claims


def sync_existing_accounts(
    db: Session,
    *,
    apply_legacy_student_approval_rollback: bool = False,
    sync_firebase_claims: bool = True,
) -> dict:
    settings = get_settings()
    users = db.scalars(select(User)).all()

    users_scanned = 0
    roles_updated = 0
    approvals_created = 0
    approvals_updated = 0
    firebase_claims_synced = 0
    firebase_users_missing = 0
    firebase_sync_errors = 0

    for user in users:
        users_scanned += 1
        user_changed = False
        email = (user.email or "").strip().lower()

        approval = db.scalar(select(UserApproval).where(UserApproval.user_id == user.id))
        if not approval:
            approval = UserApproval(
                user_id=user.id,
                status=ApprovalStatus.APPROVED,
                rejection_reason=None,
                reviewed_by_admin_id=None,
                reviewed_at=None,
            )
            db.add(approval)
            approvals_created += 1
            user_changed = True
        elif (
            approval.status != ApprovalStatus.APPROVED or approval.rejection_reason
        ):
            approval.status = ApprovalStatus.APPROVED
            approval.rejection_reason = None
            approvals_updated += 1
            user_changed = True
        elif (
            apply_legacy_student_approval_rollback
            and user.role == UserRole.STUDENT
            and approval.status == ApprovalStatus.APPROVED
            and approval.reviewed_at is None
            and approval.reviewed_by_admin_id is None
        ):
            approval.status = ApprovalStatus.PENDING
            approval.rejection_reason = None
            approvals_updated += 1
            user_changed = True

        if user_changed:
            db.flush()

        if not sync_firebase_claims or settings.auth_mode.lower() != "firebase":
            continue

        try:
            uid = get_firebase_uid_by_email(user.email)
            if not uid:
                firebase_users_missing += 1
                continue
            set_firebase_custom_claims(
                uid,
                {
                    "role": user.role.value,
                    "approval_status": approval.status.value if approval else ApprovalStatus.PENDING.value,
                    "app_user_id": user.id,
                    "is_active": bool(user.is_active),
                },
            )
            firebase_claims_synced += 1
        except Exception:
            firebase_sync_errors += 1

    db.commit()
    return {
        "users_scanned": users_scanned,
        "roles_updated": roles_updated,
        "approvals_created": approvals_created,
        "approvals_updated": approvals_updated,
        "firebase_claims_synced": firebase_claims_synced,
        "firebase_users_missing": firebase_users_missing,
        "firebase_sync_errors": firebase_sync_errors,
    }

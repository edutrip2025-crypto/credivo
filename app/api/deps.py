from fastapi import Depends, Header, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db.session import get_db
from app.models.entities import ApprovalStatus, BannedIdentity, ProviderProfile, User, UserApproval, UserRole
from app.services.firebase_auth import set_firebase_custom_claims, verify_firebase_token

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/firebase/login", auto_error=False)


def _dummy_user(
    db: Session,
    dummy_user_id: int | None,
    dummy_role: str | None,
    dummy_email: str | None,
    dummy_name: str | None,
) -> User:
    user_id = dummy_user_id or 1
    role_value = (dummy_role or UserRole.ADMIN.value).lower()
    email = dummy_email or f"dummy{user_id}@local.test"
    name = dummy_name or f"Dummy {role_value.title()}"
    try:
        role = UserRole(role_value)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Invalid X-Dummy-Role header") from exc

    user = db.get(User, user_id)
    taken = db.scalar(select(User).where(User.email == email, User.id != user_id))
    if taken:
        local, _, domain = email.partition("@")
        domain_part = domain if domain else "local.test"
        email = f"{local}+u{user_id}@{domain_part}"
    if not user:
        user = User(
            id=user_id,
            email=email,
            full_name=name,
            password_hash="dummy",
            role=role,
            is_active=True,
        )
        db.add(user)
        db.commit()
        db.refresh(user)
        return user

    user.role = role
    user.email = email
    user.full_name = name
    db.commit()
    db.refresh(user)
    return user


def _resolve_non_admin_role(
    db: Session,
    *,
    user_id: int,
    role_claim: str,
) -> UserRole:
    if role_claim in {UserRole.PROVIDER.value, UserRole.STUDENT.value}:
        return UserRole(role_claim)
    provider_profile_id = db.scalar(select(ProviderProfile.id).where(ProviderProfile.user_id == user_id))
    return UserRole.PROVIDER if provider_profile_id else UserRole.STUDENT


def get_current_user(
    token: str | None = Depends(oauth2_scheme),
    db: Session = Depends(get_db),
    x_dummy_user_id: int | None = Header(default=None),
    x_dummy_role: str | None = Header(default=None),
    x_dummy_email: str | None = Header(default=None),
    x_dummy_name: str | None = Header(default=None),
) -> User:
    settings = get_settings()
    if settings.is_production and settings.auth_mode.lower() == "dummy":
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Dummy auth mode is disabled in production.")
    if settings.auth_mode.lower() == "dummy":
        return _dummy_user(db, x_dummy_user_id, x_dummy_role, x_dummy_email, x_dummy_name)

    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
    )
    if not token:
        raise credentials_exception
    try:
        payload = verify_firebase_token(token)
        firebase_uid = payload.get("uid")
        email = payload.get("email")
        phone_number = str(payload.get("phone_number") or "").strip() or None
        email_norm = str(email or "").strip().lower() or None
        name = payload.get("name") or (email.split("@")[0] if email else "Firebase User")
        role_claim = str(payload.get("role") or "").strip().lower()
        approval_claim = str(payload.get("approval_status") or "").strip().lower()
        if not firebase_uid:
            raise credentials_exception
    except Exception as exc:
        raise credentials_exception from exc

    user = db.scalar(select(User).where(func.lower(func.trim(User.email)) == email_norm)) if email_norm else None
    if not user and email_norm:
        if db.scalar(select(BannedIdentity.id).where(func.lower(func.trim(BannedIdentity.email)) == email_norm)):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="This account is banned.")
    if not user and phone_number:
        if db.scalar(select(BannedIdentity.id).where(BannedIdentity.phone_number == phone_number)):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="This account is banned.")
    if not user:
        if role_claim in {UserRole.PROVIDER.value, UserRole.STUDENT.value}:
            role = UserRole(role_claim)
        elif role_claim == UserRole.ADMIN.value and email_norm and email_norm in settings.admin_email_set:
            role = UserRole.ADMIN
        elif email_norm and email_norm in settings.admin_email_set:
            role = UserRole.ADMIN
        else:
            role = UserRole.STUDENT
        user = User(
            email=email_norm or f"{firebase_uid}@firebase.local",
            phone_number=phone_number,
            full_name=name,
            password_hash="firebase",
            role=role,
            is_active=True,
            account_state="active",
        )
        db.add(user)
        db.flush()
        approval = db.scalar(select(UserApproval).where(UserApproval.user_id == user.id))
        if not approval:
            approval = UserApproval(user_id=user.id)
            db.add(approval)
        approval.status = ApprovalStatus.APPROVED
        approval.rejection_reason = None
        db.commit()
        db.refresh(user)
        return user

    changed = False
    if user.role == UserRole.ADMIN and (not email_norm or email_norm not in settings.admin_email_set):
        user.role = _resolve_non_admin_role(
            db,
            user_id=user.id,
            role_claim=role_claim,
        )
        changed = True
    if user.full_name != name:
        user.full_name = name
        changed = True
    if changed:
        db.commit()
        db.refresh(user)

    state = str(user.account_state or "active").lower()
    if state in {"banned", "deleted"}:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="This account is not allowed to access the platform.")
    if state == "frozen":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="This account is temporarily frozen.")

    approval = db.scalar(select(UserApproval).where(UserApproval.user_id == user.id))
    if not approval:
        default_status = ApprovalStatus.APPROVED
        db.add(
            UserApproval(
                user_id=user.id,
                status=default_status,
                rejection_reason=None,
            ),
        )
        db.commit()
        approval = db.scalar(select(UserApproval).where(UserApproval.user_id == user.id))
    elif approval and approval.status != ApprovalStatus.APPROVED:
        approval.status = ApprovalStatus.APPROVED
        approval.rejection_reason = None
        db.commit()

    if approval:
        try:
            set_firebase_custom_claims(
                str(firebase_uid),
                {
                    "role": user.role.value,
                    "approval_status": approval.status.value,
                    "app_user_id": user.id,
                    "is_active": bool(user.is_active),
                },
            )
        except Exception:
            pass
    return user


def is_user_approved(db: Session, user: User) -> tuple[bool, str | None]:
    if user.role == UserRole.ADMIN:
        return True, None
    approval = db.scalar(select(UserApproval).where(UserApproval.user_id == user.id))
    if not approval:
        return True, None
    if approval.status == ApprovalStatus.APPROVED:
        return True, None
    if approval.status == ApprovalStatus.REJECTED:
        return False, "Profile is invalid. Contact support."
    return False, "Profile is pending approval."


def require_role(*roles: UserRole, allow_unapproved: bool = False):
    def checker(user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> User:
        if user.role not in roles:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient permissions")
        if not allow_unapproved:
            approved, reason = is_user_approved(db, user)
            if not approved:
                raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=reason)
        return user

    return checker

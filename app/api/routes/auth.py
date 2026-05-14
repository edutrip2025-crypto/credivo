import hmac
import re

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.exc import IntegrityError
from sqlalchemy import and_, func, select
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, require_role
from app.core.config import get_settings
from app.core.security import create_access_token, hash_password, verify_password
from app.db.session import get_db
from app.models.entities import ApprovalStatus, ProviderProfile, User, UserApproval, UserIdentityVerification, UserRole
from app.schemas import AdminRecoveryRequest, AdminSetUserPasswordRequest, LoginRequest, RegisterRoleRequest, SignupRequest, TokenResponse, UserOut
from app.services.firebase_auth import (
    create_firebase_custom_token,
    ensure_firebase_user_uid,
    set_firebase_custom_claims,
    set_firebase_password_by_email,
    verify_firebase_token,
)
from app.services.identity_verification import verify_identity_via_api

router = APIRouter(prefix="/auth", tags=["auth"])
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/firebase/login", auto_error=False)

_ALLOWED_STUDENT_ID_TYPES = {
    "aadhaar",
    "passport",
    "national_id",
    "driving_license",
    "voter_id",
    "pan",
    "other",
}
_ALLOWED_PROVIDER_ID_TYPES = {
    "cin",
    "gst",
    "pan",
    "passport",
    "national_id",
    "tax_id",
    "other",
}


def _public_uid(user_id: int | None) -> str:
    if not user_id:
        return "CR-000000"
    return f"CR-{int(user_id):06d}"


def _safe_sync_claims(firebase_uid: str, user: User, approval_status: ApprovalStatus) -> None:
    try:
        set_firebase_custom_claims(
            firebase_uid,
            {
                "role": user.role.value,
                "approval_status": approval_status.value,
                "app_user_id": user.id,
                "is_active": bool(user.is_active),
            },
        )
    except Exception:
        # Keep auth flow resilient even when Firebase admin claim writes fail.
        pass


def _normalized_user_query(email_norm: str | None):
    if not email_norm:
        return None
    return select(User).where(func.lower(func.trim(User.email)) == email_norm)


def _safe_int(value) -> int | None:
    try:
        if value is None:
            return None
        return int(value)
    except Exception:
        return None


def _firebase_local_email(firebase_uid: str, suffix: int | None = None) -> str:
    uid = str(firebase_uid or "").strip().lower()
    # Keep local-part email safe and deterministic across providers.
    safe_uid = re.sub(r"[^a-z0-9._+-]+", "_", uid).strip("._+-")
    if not safe_uid:
        safe_uid = "firebase_user"
    if suffix and suffix > 0:
        safe_uid = f"{safe_uid}.{suffix}"
    return f"{safe_uid}@firebase.local"


def _find_user_for_identity(
    db: Session,
    *,
    claim_user_id: int | None,
    email_norm: str | None,
    firebase_uid: str,
) -> User | None:
    if claim_user_id:
        by_id = db.get(User, claim_user_id)
        if by_id:
            return by_id
    if email_norm:
        by_email = db.scalar(_normalized_user_query(email_norm))
        if by_email:
            return by_email
    # Prefer sanitized deterministic firebase-local email.
    local_email = _firebase_local_email(firebase_uid)
    by_local = db.scalar(_normalized_user_query(local_email))
    if by_local:
        return by_local
    # Backward compatibility for any previously stored legacy uid-based email.
    legacy_email = f"{str(firebase_uid or '').strip().lower()}@firebase.local"
    if legacy_email != local_email:
        by_legacy = db.scalar(_normalized_user_query(legacy_email))
        if by_legacy:
            return by_legacy
    return None


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


def _assert_recovery_key_or_403(submitted_key: str, configured_key: str) -> None:
    given = (submitted_key or "").strip()
    expected = (configured_key or "").strip()
    if not expected:
        raise HTTPException(status_code=503, detail="Admin recovery is not configured.")
    if not hmac.compare_digest(given, expected):
        raise HTTPException(status_code=403, detail="Invalid admin recovery key.")


def _normalize_country_code(value: str | None) -> str:
    text = re.sub(r"[^A-Za-z]", "", str(value or "").strip()).upper()
    return text[:8] if text else "IN"


def _normalize_id_number(value: str | None) -> str:
    return re.sub(r"\s+", "", str(value or "").strip()).upper()


def _normalize_phone_number(value: str | None) -> str | None:
    raw = str(value or "").strip()
    if not raw:
        return None
    cleaned = re.sub(r"[^\d+]", "", raw)
    return cleaned or None


def _assert_not_banned_identity(
    db: Session,
    *,
    email: str | None,
    phone_number: str | None,
    id_type: str | None = None,
    id_number: str | None = None,
    country_code: str | None = None,
) -> None:
    from app.models.entities import BannedIdentity

    e_norm = str(email or "").strip().lower() or None
    p_norm = _normalize_phone_number(phone_number)
    t_norm = str(id_type or "").strip().lower() or None
    n_norm = _normalize_id_number(id_number) if id_number else None
    c_norm = _normalize_country_code(country_code) if country_code else None

    if e_norm and db.scalar(select(BannedIdentity.id).where(func.lower(func.trim(BannedIdentity.email)) == e_norm)):
        raise HTTPException(status_code=403, detail="This account is banned and cannot be registered.")
    if p_norm and db.scalar(select(BannedIdentity.id).where(BannedIdentity.phone_number == p_norm)):
        raise HTTPException(status_code=403, detail="This account is banned and cannot be registered.")
    if t_norm and n_norm:
        q = select(BannedIdentity.id).where(
            and_(
                BannedIdentity.id_type == t_norm,
                BannedIdentity.id_number == n_norm,
            ),
        )
        if c_norm:
            q = q.where(BannedIdentity.country_code == c_norm)
        if db.scalar(q):
            raise HTTPException(status_code=403, detail="This KYC identity is banned and cannot be registered.")


def _validate_identity_input(
    *,
    role: UserRole,
    id_type: str | None,
    id_number: str | None,
    country_code: str | None,
) -> tuple[str, str, str]:
    t = str(id_type or "").strip().lower()
    n = _normalize_id_number(id_number)
    c = _normalize_country_code(country_code)
    if not t or not n:
        raise HTTPException(status_code=400, detail="Verification ID type and number are required.")
    allowed = _ALLOWED_STUDENT_ID_TYPES if role == UserRole.STUDENT else _ALLOWED_PROVIDER_ID_TYPES
    if t not in allowed:
        raise HTTPException(status_code=400, detail=f"Unsupported verification ID type for {role.value}.")
    if t == "aadhaar" and not re.fullmatch(r"\d{12}", n):
        raise HTTPException(status_code=400, detail="Aadhaar must be exactly 12 digits.")
    if t == "pan" and not re.fullmatch(r"[A-Z]{5}\d{4}[A-Z]", n):
        raise HTTPException(status_code=400, detail="PAN format is invalid.")
    if t == "gst" and not re.fullmatch(r"\d{2}[A-Z]{5}\d{4}[A-Z][A-Z0-9][Zz][A-Z0-9]", n):
        raise HTTPException(status_code=400, detail="GSTIN format is invalid.")
    if t == "cin" and not re.fullmatch(r"[A-Z0-9]{21}", n):
        raise HTTPException(status_code=400, detail="CIN format is invalid.")
    return t, n, c


def _upsert_identity_verification(
    *,
    db: Session,
    user_id: int,
    role: UserRole,
    id_type: str | None,
    id_number: str | None,
    country_code: str | None,
    document_url: str | None = None,
) -> None:
    existing_identity = db.scalar(select(UserIdentityVerification).where(UserIdentityVerification.user_id == user_id))
    if role not in {UserRole.STUDENT, UserRole.PROVIDER}:
        return
    if existing_identity is None and (not id_type or not id_number):
        raise HTTPException(status_code=400, detail="Verification ID is required for student/provider accounts.")
    if not id_type and not id_number:
        return
    _assert_not_banned_identity(
        db,
        email=None,
        phone_number=None,
        id_type=id_type,
        id_number=id_number,
        country_code=country_code,
    )
    v_type, v_number, v_country = _validate_identity_input(
        role=role,
        id_type=id_type,
        id_number=id_number,
        country_code=country_code,
    )
    verification = verify_identity_via_api(
        id_type=v_type,
        id_number=v_number,
        country_code=v_country,
        role=role.value,
    )
    if not verification.verified:
        detail = verification.message or "Identity verification failed."
        status_code = 503 if ("unavailable" in detail or "not configured" in detail or "http_error=5" in detail) else 400
        raise HTTPException(status_code=status_code, detail=detail)
    if not existing_identity:
        existing_identity = UserIdentityVerification(user_id=user_id)
        db.add(existing_identity)
    existing_identity.id_type = v_type
    existing_identity.id_number = v_number
    existing_identity.country_code = v_country
    existing_identity.document_url = (document_url or "").strip() or None
    existing_identity.status = ApprovalStatus.APPROVED
    existing_identity.reviewed_by_admin_id = None
    existing_identity.reviewed_at = None


def _firebase_identity_or_401(token: str | None) -> tuple[str, str | None, str | None, str, dict]:
    if not token:
        raise HTTPException(status_code=401, detail="Could not validate credentials")
    try:
        payload = verify_firebase_token(token)
        firebase_uid = payload.get("uid")
        email = payload.get("email")
        phone_number = _normalize_phone_number(payload.get("phone_number"))
        name = payload.get("name") or (email.split("@")[0] if email else "Firebase User")
        if not firebase_uid:
            raise HTTPException(status_code=401, detail="Could not validate credentials")
        return str(firebase_uid), email, phone_number, str(name), payload
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=401, detail="Could not validate credentials") from exc


@router.post("/signup", response_model=UserOut, status_code=status.HTTP_201_CREATED)
def signup(payload: SignupRequest, db: Session = Depends(get_db)):
    existing = db.scalar(select(User).where(User.email == payload.email))
    if existing:
        raise HTTPException(status_code=400, detail="Email already in use")
    user = User(
        email=payload.email,
        full_name=payload.full_name,
        password_hash=hash_password(payload.password),
        role=payload.role,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


@router.post("/login", response_model=TokenResponse)
def login(payload: LoginRequest, db: Session = Depends(get_db)):
    settings = get_settings()
    if settings.auth_mode.lower() == "dummy" and not settings.is_production:
        email = payload.email.strip().lower()
        if "provider" in email:
            role = UserRole.PROVIDER
        elif "student" in email:
            role = UserRole.STUDENT
        else:
            role = UserRole.ADMIN
        token = create_access_token("1", role.value)
        return TokenResponse(access_token=token, role=role)

    user = db.scalar(select(User).where(User.email == payload.email))
    if not user or not verify_password(payload.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Invalid credentials")
    token = create_access_token(str(user.id), user.role.value)
    return TokenResponse(access_token=token, role=user.role)


@router.get("/me", response_model=UserOut)
def me(current_user: User = Depends(get_current_user)):
    return current_user


@router.get("/me/context")
def me_context(
    token: str | None = Depends(oauth2_scheme),
    db: Session = Depends(get_db),
):
    firebase_uid, email, phone_number, fallback_name, token_payload = _firebase_identity_or_401(token)
    email_norm = str(email or "").strip().lower() or None
    current_user = db.scalar(_normalized_user_query(email_norm)) if email_norm else None
    settings = get_settings()
    role_claim = str(token_payload.get("role") or "").strip().lower()
    role_from_claim: UserRole | None = None
    if role_claim in {r.value for r in UserRole}:
        role_from_claim = UserRole(role_claim)
    if not current_user:
        _assert_not_banned_identity(db, email=email_norm, phone_number=phone_number)
        desired_role: UserRole
        if role_from_claim in {UserRole.STUDENT, UserRole.PROVIDER}:
            desired_role = role_from_claim
        elif role_from_claim == UserRole.ADMIN:
            desired_role = UserRole.ADMIN if (email_norm and email_norm in settings.admin_email_set) else UserRole.STUDENT
        elif email_norm and email_norm in settings.admin_email_set:
            desired_role = UserRole.ADMIN
        else:
            desired_role = UserRole.STUDENT
        if desired_role == UserRole.ADMIN:
            current_user = User(
                email=email_norm,
                full_name=fallback_name,
                password_hash="firebase",
                role=UserRole.ADMIN,
                is_active=True,
            )
            db.add(current_user)
            db.flush()
            approval = db.scalar(select(UserApproval).where(UserApproval.user_id == current_user.id))
            if not approval:
                db.add(
                    UserApproval(
                        user_id=current_user.id,
                        status=ApprovalStatus.APPROVED,
                        rejection_reason=None,
                    ),
                )
            else:
                approval.status = ApprovalStatus.APPROVED
                approval.rejection_reason = None
            db.commit()
            db.refresh(current_user)
            _safe_sync_claims(firebase_uid, current_user, ApprovalStatus.APPROVED)
        else:
            current_user = User(
                email=email_norm or _firebase_local_email(firebase_uid),
                phone_number=phone_number,
                full_name=fallback_name,
                password_hash="firebase",
                role=desired_role,
                is_active=True,
                account_state="active",
            )
            db.add(current_user)
            db.flush()
            approval = db.scalar(select(UserApproval).where(UserApproval.user_id == current_user.id))
            if not approval:
                approval = UserApproval(user_id=current_user.id)
                db.add(approval)
            approval.status = ApprovalStatus.APPROVED
            approval.rejection_reason = None
            db.commit()
            db.refresh(current_user)
            _safe_sync_claims(firebase_uid, current_user, approval.status)
    else:
        changed = False
        if current_user.role == UserRole.ADMIN and (not email_norm or email_norm not in settings.admin_email_set):
            current_user.role = _resolve_non_admin_role(
                db,
                user_id=current_user.id,
                role_claim=role_claim,
            )
            changed = True
        if current_user.full_name != fallback_name:
            current_user.full_name = fallback_name
            changed = True
        if phone_number and current_user.phone_number != phone_number:
            current_user.phone_number = phone_number
            changed = True
        if str(current_user.account_state or "active").lower() in {"banned", "deleted"}:
            raise HTTPException(status_code=403, detail="This account is not allowed to access the platform.")
        if str(current_user.account_state or "active").lower() == "frozen":
            raise HTTPException(status_code=403, detail="This account is temporarily frozen. Contact support.")
        if changed:
            db.commit()
            db.refresh(current_user)

    approval = db.scalar(select(UserApproval).where(UserApproval.user_id == current_user.id))
    if not approval:
        default_status = ApprovalStatus.APPROVED
        approval = UserApproval(
            user_id=current_user.id,
            status=default_status,
            rejection_reason=None,
        )
        db.add(approval)
        db.commit()
        db.refresh(current_user)
    elif approval.status != ApprovalStatus.APPROVED:
        approval.status = ApprovalStatus.APPROVED
        approval.rejection_reason = None
        db.commit()
    approval_status = approval.status
    rejection_reason = approval.rejection_reason
    identity = db.scalar(select(UserIdentityVerification).where(UserIdentityVerification.user_id == current_user.id))
    _safe_sync_claims(firebase_uid, current_user, approval_status)
    return {
        "setup_required": False,
        "id": current_user.id,
        "public_uid": _public_uid(current_user.id),
        "email": current_user.email,
        "phone_number": current_user.phone_number,
        "student_age": current_user.student_age,
        "full_name": current_user.full_name,
        "role": current_user.role,
        "account_state": str(current_user.account_state or "active"),
        "approval_status": approval_status,
        "rejection_reason": rejection_reason,
        "verification_id_type": identity.id_type if identity else None,
        "verification_country_code": identity.country_code if identity else None,
        "verification_status": identity.status if identity else None,
    }


@router.post("/register-role", response_model=UserOut)
def register_role(
    payload: RegisterRoleRequest,
    token: str | None = Depends(oauth2_scheme),
    db: Session = Depends(get_db),
):
    firebase_uid, email, phone_number, fallback_name, token_payload = _firebase_identity_or_401(token)
    email_norm = str(email or "").strip().lower() or None
    settings = get_settings()
    if payload.role == UserRole.ADMIN and (not email_norm or email_norm not in settings.admin_email_set):
        raise HTTPException(status_code=403, detail="Admin role can only be assigned to configured admin accounts")
    claim_user_id = _safe_int((token_payload or {}).get("app_user_id"))
    current_user = _find_user_for_identity(
        db,
        claim_user_id=claim_user_id,
        email_norm=email_norm,
        firebase_uid=firebase_uid,
    )

    target_email = email_norm or (current_user.email if current_user else _firebase_local_email(firebase_uid))
    if not email_norm and (not target_email or target_email.endswith("@firebase.local")):
        target_email = _firebase_local_email(firebase_uid)

    _assert_not_banned_identity(
        db,
        email=target_email,
        phone_number=phone_number,
        id_type=payload.verification_id_type,
        id_number=payload.verification_id_number,
        country_code=payload.verification_country_code,
    )

    if not current_user:
        current_user = User(
            email=target_email,
            phone_number=phone_number,
            full_name=payload.full_name or fallback_name,
            password_hash="firebase",
            role=payload.role,
            student_age=int(payload.student_age) if payload.student_age else None,
            is_active=True,
            account_state="active",
        )
        db.add(current_user)
        db.flush()
    else:
        current_user.email = target_email
        if phone_number:
            current_user.phone_number = phone_number
        current_user.full_name = payload.full_name or fallback_name
        current_user.role = payload.role
        current_user.student_age = int(payload.student_age) if payload.student_age else None
        if str(current_user.account_state or "active").lower() in {"banned", "deleted"}:
            raise HTTPException(status_code=403, detail="This account is not allowed to access the platform.")
        if str(current_user.account_state or "active").lower() == "frozen":
            raise HTTPException(status_code=403, detail="This account is temporarily frozen. Contact support.")

    _upsert_identity_verification(
        db=db,
        user_id=current_user.id,
        role=payload.role,
        id_type=payload.verification_id_type,
        id_number=payload.verification_id_number,
        country_code=payload.verification_country_code,
        document_url=payload.verification_document_url,
    )

    approval = db.scalar(select(UserApproval).where(UserApproval.user_id == current_user.id))
    if not approval:
        approval = UserApproval(user_id=current_user.id)
        db.add(approval)
    if payload.role == UserRole.ADMIN:
        approval.status = ApprovalStatus.APPROVED
        approval.rejection_reason = None
    else:
        approval.status = ApprovalStatus.APPROVED
        approval.rejection_reason = None
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        # Handle duplicate/race conditions gracefully (common right after Firebase signup).
        recovered = _find_user_for_identity(
            db,
            claim_user_id=claim_user_id,
            email_norm=email_norm,
            firebase_uid=firebase_uid,
        )
        if not recovered:
            # Last resort: create a deterministic local-email user for this Firebase UID.
            recovered = User(
                email=_firebase_local_email(firebase_uid),
                phone_number=phone_number,
                full_name=payload.full_name or fallback_name,
                password_hash="firebase",
                role=payload.role,
                student_age=int(payload.student_age) if payload.student_age else None,
                is_active=True,
                account_state="active",
            )
            db.add(recovered)
            db.flush()

        recovered.full_name = payload.full_name or fallback_name
        recovered.role = payload.role
        recovered.student_age = int(payload.student_age) if payload.student_age else None
        _upsert_identity_verification(
            db=db,
            user_id=recovered.id,
            role=payload.role,
            id_type=payload.verification_id_type,
            id_number=payload.verification_id_number,
            country_code=payload.verification_country_code,
            document_url=payload.verification_document_url,
        )
        recovered_approval = db.scalar(select(UserApproval).where(UserApproval.user_id == recovered.id))
        if not recovered_approval:
            recovered_approval = UserApproval(user_id=recovered.id)
            db.add(recovered_approval)
        recovered_approval.status = ApprovalStatus.APPROVED
        recovered_approval.rejection_reason = None
        try:
            db.commit()
        except IntegrityError:
            db.rollback()
            # Final idempotent fallback: if the row now exists due a concurrent request,
            # return that row instead of failing signup.
            recovered = _find_user_for_identity(
                db,
                claim_user_id=claim_user_id,
                email_norm=email_norm,
                firebase_uid=firebase_uid,
            )
            if not recovered:
                # Last-resort recovery: create a deterministic firebase-local identity
                # and keep retrying with a suffix to avoid uniqueness races.
                created = None
                for idx in range(6):
                    probe_email = _firebase_local_email(firebase_uid, idx if idx > 0 else None)
                    created = db.scalar(_normalized_user_query(probe_email))
                    if created:
                        break
                    try:
                        created = User(
                            email=probe_email,
                            phone_number=phone_number,
                            full_name=payload.full_name or fallback_name,
                            password_hash="firebase",
                            role=payload.role,
                            is_active=True,
                            account_state="active",
                        )
                        db.add(created)
                        db.flush()
                        break
                    except IntegrityError:
                        db.rollback()
                        created = None
                        continue
                recovered = created
            if not recovered:
                raise HTTPException(status_code=500, detail="Account profile setup failed. Please retry login once.")
            recovered_approval = db.scalar(select(UserApproval).where(UserApproval.user_id == recovered.id))
            if recovered_approval and recovered_approval.status != ApprovalStatus.APPROVED:
                recovered_approval.status = ApprovalStatus.APPROVED
                recovered_approval.rejection_reason = None
                try:
                    db.commit()
                except IntegrityError:
                    db.rollback()
            elif not recovered_approval:
                recovered_approval = UserApproval(
                    user_id=recovered.id,
                    status=ApprovalStatus.APPROVED,
                    rejection_reason=None,
                )
                db.add(recovered_approval)
                try:
                    db.commit()
                except IntegrityError:
                    db.rollback()
        current_user = recovered
        approval = recovered_approval

    db.refresh(current_user)
    _safe_sync_claims(firebase_uid, current_user, approval.status)
    return current_user


@router.post("/admin/recover-self")
def recover_self_as_admin(
    payload: AdminRecoveryRequest,
    token: str | None = Depends(oauth2_scheme),
    db: Session = Depends(get_db),
):
    settings = get_settings()
    _assert_recovery_key_or_403(payload.recovery_key, settings.admin_recovery_key)
    firebase_uid, email, phone_number, fallback_name, _ = _firebase_identity_or_401(token)
    email_norm = str(email or "").strip().lower()
    if not email_norm:
        raise HTTPException(status_code=400, detail="Authenticated Firebase account has no email.")

    user = db.scalar(_normalized_user_query(email_norm))
    if not user:
        user = User(
            email=email_norm,
            phone_number=phone_number,
            full_name=fallback_name,
            password_hash="firebase",
            role=UserRole.ADMIN,
            is_active=True,
            account_state="active",
        )
        db.add(user)
        db.flush()
    else:
        user.role = UserRole.ADMIN
        user.full_name = fallback_name
        if phone_number:
            user.phone_number = phone_number
        user.is_active = True
        user.account_state = "active"

    approval = db.scalar(select(UserApproval).where(UserApproval.user_id == user.id))
    if not approval:
        approval = UserApproval(user_id=user.id)
        db.add(approval)
    approval.status = ApprovalStatus.APPROVED
    approval.rejection_reason = None
    db.commit()
    db.refresh(user)
    _safe_sync_claims(firebase_uid, user, ApprovalStatus.APPROVED)
    return {
        "ok": True,
        "email": user.email,
        "public_uid": _public_uid(user.id),
        "role": user.role.value,
        "approval_status": ApprovalStatus.APPROVED.value,
    }


@router.post("/admin/set-user-password")
def admin_set_user_password(
    payload: AdminSetUserPasswordRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.ADMIN)),
):
    settings = get_settings()
    _assert_recovery_key_or_403(payload.recovery_key, settings.admin_recovery_key)
    email_norm = str(payload.email or "").strip().lower()
    uid = set_firebase_password_by_email(email_norm, payload.new_password)
    if not uid:
        raise HTTPException(status_code=404, detail="Firebase user not found for this email.")
    local_user = db.scalar(_normalized_user_query(email_norm))
    if local_user and not local_user.is_active:
        local_user.is_active = True
        db.commit()
    return {
        "ok": True,
        "email": email_norm,
        "firebase_uid": uid,
        "updated_by": current_user.email,
    }


@router.post("/admin/breakglass-login")
def admin_breakglass_login(
    payload: LoginRequest,
    db: Session = Depends(get_db),
):
    settings = get_settings()
    _assert_recovery_key_or_403(payload.password, settings.admin_recovery_key)
    email_norm = str(payload.email or "").strip().lower()
    if not email_norm:
        raise HTTPException(status_code=400, detail="Email is required.")
    if email_norm != "admin@certora.in":
        raise HTTPException(status_code=403, detail="Break-glass login is allowed only for admin@certora.in")
    try:
        uid = ensure_firebase_user_uid(email_norm, display_name="Classagon Admin")
        if not uid:
            raise HTTPException(status_code=500, detail="Failed to resolve Firebase admin user.")
        # Ensure client password sign-in can always work without mailbox access.
        updated_uid = set_firebase_password_by_email(email_norm, payload.password)
        if not updated_uid:
            raise HTTPException(status_code=500, detail="Failed to set Firebase admin password.")
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Firebase admin recovery failed: {str(exc)}")

    user = db.scalar(_normalized_user_query(email_norm))
    if not user:
        user = User(
            email=email_norm,
            full_name="Classagon Admin",
            password_hash="firebase",
            role=UserRole.ADMIN,
            is_active=True,
        )
        db.add(user)
        db.flush()
    else:
        user.role = UserRole.ADMIN
        user.is_active = True

    approval = db.scalar(select(UserApproval).where(UserApproval.user_id == user.id))
    if not approval:
        approval = UserApproval(user_id=user.id)
        db.add(approval)
    approval.status = ApprovalStatus.APPROVED
    approval.rejection_reason = None
    db.commit()
    db.refresh(user)
    _safe_sync_claims(uid, user, ApprovalStatus.APPROVED)
    custom_token = None
    try:
        custom_token = create_firebase_custom_token(
            uid,
            {
                "role": UserRole.ADMIN.value,
                "approval_status": ApprovalStatus.APPROVED.value,
                "app_user_id": user.id,
                "is_active": True,
            },
        )
    except Exception:
        # Fallback path: frontend can sign in using admin email + recovery key password.
        custom_token = None
    return {
        "ok": True,
        "email": user.email,
        "public_uid": _public_uid(user.id),
        "role": user.role.value,
        "custom_token": custom_token,
        "password_login_ready": True,
    }

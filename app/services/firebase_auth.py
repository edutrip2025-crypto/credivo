import json
import secrets
from pathlib import Path
from typing import Any

import firebase_admin
from firebase_admin import auth, credentials

from app.core.config import get_settings


def init_firebase() -> None:
    if firebase_admin._apps:
        return
    settings = get_settings()
    service_account_json = (settings.firebase_service_account_json or "").strip()
    service_account_path = (settings.firebase_service_account_path or "").strip()

    cred = None
    if service_account_json:
        try:
            cred = credentials.Certificate(json.loads(service_account_json))
        except json.JSONDecodeError as exc:
            raise RuntimeError("FIREBASE_SERVICE_ACCOUNT_JSON is not valid JSON") from exc
    elif service_account_path:
        path = Path(service_account_path)
        if not path.exists():
            raise RuntimeError(f"Firebase service account file not found: {path}")
        cred = credentials.Certificate(str(path))
    else:
        raise RuntimeError(
            "Firebase credentials are missing. Set FIREBASE_SERVICE_ACCOUNT_JSON on Vercel "
            "or FIREBASE_SERVICE_ACCOUNT_PATH for local/file-based environments.",
        )

    app_options: dict[str, Any] = {"projectId": settings.firebase_project_id or None}
    if settings.firebase_storage_bucket:
        app_options["storageBucket"] = settings.firebase_storage_bucket
    firebase_admin.initialize_app(cred, app_options)


def verify_firebase_token(id_token: str) -> dict[str, Any]:
    init_firebase()
    return auth.verify_id_token(id_token)


def set_firebase_custom_claims(uid: str, claims: dict[str, Any]) -> None:
    init_firebase()
    auth.set_custom_user_claims(uid, claims)


def ensure_firebase_user_uid(email: str | None, *, display_name: str | None = None) -> str | None:
    if not email:
        return None
    init_firebase()
    email_norm = str(email).strip().lower()
    try:
        user = auth.get_user_by_email(email_norm)
        return user.uid
    except auth.UserNotFoundError:
        created = auth.create_user(
            email=email_norm,
            password=secrets.token_urlsafe(24),
            display_name=display_name or email_norm.split("@")[0],
        )
        return created.uid


def create_firebase_custom_token(uid: str, claims: dict[str, Any] | None = None) -> str:
    init_firebase()
    token = auth.create_custom_token(uid, claims=claims or {})
    if isinstance(token, bytes):
        return token.decode("utf-8")
    return str(token)


def get_firebase_uid_by_email(email: str | None) -> str | None:
    if not email:
        return None
    init_firebase()
    try:
        user = auth.get_user_by_email(email)
        return user.uid
    except auth.UserNotFoundError:
        return None


def set_firebase_password_by_email(email: str | None, new_password: str) -> str | None:
    if not email:
        return None
    init_firebase()
    try:
        user = auth.get_user_by_email(email)
    except auth.UserNotFoundError:
        return None
    auth.update_user(user.uid, password=new_password)
    return user.uid

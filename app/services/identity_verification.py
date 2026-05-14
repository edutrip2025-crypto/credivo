import json
from dataclasses import dataclass
from urllib import error, request

from app.core.config import get_settings


@dataclass
class IdentityVerificationResult:
    verified: bool
    source: str
    message: str = ""
    raw: dict | None = None


def _endpoint_for_id_type(id_type: str) -> str:
    s = get_settings()
    mapping = {
        "aadhaar": s.identity_verify_aadhaar_url,
        "pan": s.identity_verify_pan_url,
        "cin": s.identity_verify_cin_url,
        "gst": s.identity_verify_gst_url,
        "passport": s.identity_verify_passport_url,
        "national_id": s.identity_verify_national_id_url,
        "driving_license": s.identity_verify_driving_license_url,
        "voter_id": s.identity_verify_voter_id_url,
        "tax_id": s.identity_verify_tax_id_url,
        "other": s.identity_verify_other_url,
    }
    return str(mapping.get(id_type, "") or "").strip()


def _coerce_verified(raw: dict) -> bool:
    if not raw:
        return False
    direct = raw.get("verified")
    if isinstance(direct, bool):
        return direct
    for key in ("is_verified", "success", "valid", "is_valid"):
        val = raw.get(key)
        if isinstance(val, bool):
            return val
    status = str(raw.get("status") or raw.get("state") or "").strip().lower()
    if status in {"verified", "success", "ok", "valid", "active"}:
        return True
    data = raw.get("data")
    if isinstance(data, dict):
        return _coerce_verified(data)
    result = raw.get("result")
    if isinstance(result, dict):
        return _coerce_verified(result)
    return False


def verify_identity_via_api(
    *,
    id_type: str,
    id_number: str,
    country_code: str,
    role: str,
) -> IdentityVerificationResult:
    settings = get_settings()
    endpoint = _endpoint_for_id_type(id_type)
    if not endpoint:
        msg = f"Identity verification endpoint is not configured for {id_type}."
        if settings.identity_verify_enforce:
            return IdentityVerificationResult(verified=False, source="config", message=msg)
        return IdentityVerificationResult(verified=True, source="config", message="verification skipped")

    payload = {
        "id_type": id_type,
        "id_number": id_number,
        "country_code": country_code,
        "role": role,
    }
    body = json.dumps(payload).encode("utf-8")
    headers: dict[str, str] = {"Content-Type": "application/json", "Accept": "application/json"}
    if settings.identity_verify_api_key:
        headers[str(settings.identity_verify_api_key_header or "x-api-key")] = settings.identity_verify_api_key
    if settings.identity_verify_bearer_token:
        headers["Authorization"] = f"Bearer {settings.identity_verify_bearer_token}"
    if settings.identity_verify_extra_headers_json:
        try:
            extra = json.loads(settings.identity_verify_extra_headers_json)
            if isinstance(extra, dict):
                for k, v in extra.items():
                    if k:
                        headers[str(k)] = str(v)
        except Exception:
            pass

    req = request.Request(endpoint, data=body, headers=headers, method="POST")
    try:
        with request.urlopen(req, timeout=max(3, int(settings.identity_verify_timeout_seconds or 15))) as resp:
            raw_bytes = resp.read() or b"{}"
            text = raw_bytes.decode("utf-8", errors="ignore").strip() or "{}"
            parsed = json.loads(text) if text.startswith("{") else {"status_text": text}
            verified = _coerce_verified(parsed)
            return IdentityVerificationResult(
                verified=verified,
                source=endpoint,
                message="verified" if verified else "verification rejected by provider",
                raw=parsed if isinstance(parsed, dict) else None,
            )
    except error.HTTPError as exc:
        raw = ""
        try:
            raw = (exc.read() or b"").decode("utf-8", errors="ignore")
        except Exception:
            raw = ""
        return IdentityVerificationResult(
            verified=False,
            source=endpoint,
            message=f"verification provider http_error={exc.code} body={raw[:300]}",
        )
    except Exception as exc:
        return IdentityVerificationResult(
            verified=False,
            source=endpoint,
            message=f"verification provider unavailable: {str(exc)}",
        )

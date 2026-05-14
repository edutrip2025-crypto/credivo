import html as html_lib

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import require_role
from app.db.session import get_db
from app.models.entities import Certificate, CertificateStatus, Result, User, UserRole, VerificationRecord
from app.services.certificates import certificate_payload, ensure_certificate_pdf, issue_certificate

router = APIRouter(prefix="/certificates", tags=["certificates"])


def _public_request_base_url(request: Request) -> str:
    xf_proto = (request.headers.get("x-forwarded-proto") or "").split(",")[0].strip()
    xf_host = (request.headers.get("x-forwarded-host") or "").split(",")[0].strip()
    proto = xf_proto or request.url.scheme
    host = xf_host or request.headers.get("host") or request.url.netloc
    return f"{proto}://{host}".rstrip("/")


@router.post("/generate/{result_id}")
def generate_certificate(
    result_id: int,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.ADMIN, UserRole.PROVIDER)),
):
    result = db.get(Result, result_id)
    if not result:
        raise HTTPException(status_code=404, detail="Result not found")
    if not result.passed:
        raise HTTPException(status_code=400, detail="Result is not pass eligible")

    try:
        cert = issue_certificate(db, result, verification_base_url=_public_request_base_url(request))
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    db.commit()
    db.refresh(cert)
    return certificate_payload(db, cert, verification_base_url=_public_request_base_url(request))


@router.get("/verify/{certificate_id}")
def verify_certificate(
    certificate_id: str,
    request: Request,
    vt: str | None = None,
    db: Session = Depends(get_db),
):
    cert = db.scalar(select(Certificate).where(Certificate.certificate_id == certificate_id))
    if not cert or cert.status != CertificateStatus.ACTIVE:
        raise HTTPException(status_code=404, detail="Certificate not found")
    if not vt or vt != cert.verification_token:
        raise HTTPException(status_code=404, detail="Certificate not found")
    try:
        ensure_certificate_pdf(
            db,
            cert,
            force_regenerate=True,
            verification_base_url=_public_request_base_url(request),
        )
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    db.add(
        VerificationRecord(
            certificate_id=cert.id,
            ip_address=request.client.host if request.client else None,
            user_agent=request.headers.get("user-agent"),
        ),
    )
    db.commit()
    db.refresh(cert)
    payload = certificate_payload(
        db,
        cert,
        mask_identity=True,
        verification_base_url=_public_request_base_url(request),
    )
    accept = (request.headers.get("accept") or "").lower()
    wants_html = ("text/html" in accept) and (str(request.query_params.get("format") or "").lower() != "json")
    if wants_html:
        student_name = html_lib.escape(str(payload.get("student_name") or "-"))
        course_name = html_lib.escape(str(payload.get("course_name") or "-"))
        provider_name = html_lib.escape(str(payload.get("provider_name") or "-"))
        certificate_id = html_lib.escape(str(payload.get("certificate_id") or "-"))
        issued_at = html_lib.escape(str(payload.get("issued_at") or "-"))
        percentage = html_lib.escape(str(payload.get("percentage") or "-"))
        html_page = f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>Certificate Verification - Classagon</title>
  <style>
    :root {{ --bg:#f6f3ea; --card:#fffdf8; --ink:#0f172a; --muted:#475569; --line:#d6b35d; --accent:#8a6a1f; }}
    * {{ box-sizing: border-box; }}
    body {{ margin:0; font-family: system-ui, -apple-system, Segoe UI, Roboto, sans-serif; background: var(--bg); color: var(--ink); }}
    .wrap {{ max-width: 880px; margin: 36px auto; padding: 0 16px; }}
    .card {{ background: var(--card); border: 1px solid #eadfc3; border-radius: 14px; padding: 24px; }}
    .logo {{ width: 170px; height: auto; display:block; margin-bottom: 10px; }}
    h1 {{ margin: 0; font-size: 30px; color: var(--accent); }}
    .sub {{ margin-top: 8px; color: var(--muted); }}
    .grid {{ margin-top: 20px; display: grid; grid-template-columns: 1fr 1fr; gap: 10px 18px; }}
    .k {{ color: var(--muted); font-size: 13px; }}
    .v {{ font-weight: 700; }}
  </style>
</head>
<body>
  <div class="wrap">
    <div class="card">
      <img class="logo" src="/assets/classagon_logo.png" alt="Classagon" />
      <h1>Certificate Verified</h1>
      <div class="sub">This certificate is active and issued by Classagon.</div>
      <div class="grid">
        <div><div class="k">Certificate ID</div><div class="v">{certificate_id}</div></div>
        <div><div class="k">Issued On</div><div class="v">{issued_at}</div></div>
        <div><div class="k">Student</div><div class="v">{student_name}</div></div>
        <div><div class="k">Course</div><div class="v">{course_name}</div></div>
        <div><div class="k">Provider</div><div class="v">{provider_name}</div></div>
        <div><div class="k">Score</div><div class="v">{percentage}%</div></div>
      </div>
    </div>
  </div>
</body>
</html>"""
        return HTMLResponse(content=html_page, status_code=200)
    return payload


@router.post("/{certificate_id}/revoke")
def revoke_certificate(
    certificate_id: str,
    reason: str | None = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.ADMIN)),
):
    cert = db.scalar(select(Certificate).where(Certificate.certificate_id == certificate_id))
    if not cert:
        raise HTTPException(status_code=404, detail="Certificate not found")
    cert.status = CertificateStatus.REVOKED
    db.commit()
    return {"revoked": True, "certificate_id": certificate_id, "reason": reason}

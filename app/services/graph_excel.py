from __future__ import annotations

import json
from dataclasses import dataclass
from urllib import error, parse, request

from app.core.config import get_settings


class GraphExcelError(RuntimeError):
    pass


@dataclass(frozen=True)
class GraphExcelStatus:
    configured: bool
    missing: list[str]
    drive_id: str
    item_id: str


def graph_excel_status() -> GraphExcelStatus:
    settings = get_settings()
    fields = {
        "MICROSOFT_GRAPH_TENANT_ID": settings.microsoft_graph_tenant_id,
        "MICROSOFT_GRAPH_CLIENT_ID": settings.microsoft_graph_client_id,
        "MICROSOFT_GRAPH_CLIENT_SECRET": settings.microsoft_graph_client_secret,
        "MICROSOFT_GRAPH_DRIVE_ID": settings.microsoft_graph_drive_id,
        "MICROSOFT_GRAPH_EXCEL_ITEM_ID": settings.microsoft_graph_excel_item_id,
    }
    missing = [key for key, value in fields.items() if not str(value or "").strip()]
    return GraphExcelStatus(
        configured=not missing,
        missing=missing,
        drive_id=settings.microsoft_graph_drive_id,
        item_id=settings.microsoft_graph_excel_item_id,
    )


class GraphExcelClient:
    def __init__(self) -> None:
        self.settings = get_settings()
        status = graph_excel_status()
        if not status.configured:
            raise GraphExcelError(f"Microsoft Graph Excel is not configured. Missing: {', '.join(status.missing)}")
        self.drive_id = self.settings.microsoft_graph_drive_id.strip()
        self.item_id = self.settings.microsoft_graph_excel_item_id.strip()

    def _token(self) -> str:
        tenant = self.settings.microsoft_graph_tenant_id.strip()
        url = f"https://login.microsoftonline.com/{tenant}/oauth2/v2.0/token"
        body = parse.urlencode(
            {
                "client_id": self.settings.microsoft_graph_client_id.strip(),
                "client_secret": self.settings.microsoft_graph_client_secret.strip(),
                "scope": "https://graph.microsoft.com/.default",
                "grant_type": "client_credentials",
            },
        ).encode("utf-8")
        req = request.Request(
            url,
            data=body,
            method="POST",
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        data = self._send(req)
        token = str(data.get("access_token") or "")
        if not token:
            raise GraphExcelError("Microsoft Graph token response did not include access_token")
        return token

    def _graph_request(self, method: str, path: str, payload: dict | None = None, workbook_session_id: str | None = None) -> dict:
        url = f"https://graph.microsoft.com/v1.0{path}"
        body = json.dumps(payload).encode("utf-8") if payload is not None else None
        headers = {
            "Authorization": f"Bearer {self._token()}",
            "Content-Type": "application/json",
        }
        if workbook_session_id:
            headers["workbook-session-id"] = workbook_session_id
        req = request.Request(
            url,
            data=body,
            method=method,
            headers=headers,
        )
        return self._send(req)

    @staticmethod
    def _send(req: request.Request) -> dict:
        try:
            with request.urlopen(req, timeout=30) as resp:
                raw = resp.read().decode("utf-8")
        except error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise GraphExcelError(f"Microsoft Graph HTTP {exc.code}: {detail}") from exc
        except error.URLError as exc:
            raise GraphExcelError(f"Microsoft Graph request failed: {exc.reason}") from exc
        return json.loads(raw) if raw else {}

    def create_session(self, persist_changes: bool = False) -> str:
        path = f"/drives/{self.drive_id}/items/{self.item_id}/workbook/createSession"
        data = self._graph_request("POST", path, {"persistChanges": bool(persist_changes)})
        session_id = str(data.get("id") or "")
        if not session_id:
            raise GraphExcelError("Workbook session response did not include id")
        return session_id

    def read_range(self, worksheet_name: str, address: str, workbook_session_id: str | None = None) -> dict:
        sheet = parse.quote(worksheet_name, safe="")
        range_address = parse.quote(address, safe="")
        path = f"/drives/{self.drive_id}/items/{self.item_id}/workbook/worksheets/{sheet}/range(address='{range_address}')"
        return self._graph_request("GET", path, workbook_session_id=workbook_session_id)

    def write_range(self, worksheet_name: str, address: str, values: list[list[object]], workbook_session_id: str | None = None) -> dict:
        sheet = parse.quote(worksheet_name, safe="")
        range_address = parse.quote(address, safe="")
        path = f"/drives/{self.drive_id}/items/{self.item_id}/workbook/worksheets/{sheet}/range(address='{range_address}')"
        return self._graph_request("PATCH", path, {"values": values}, workbook_session_id=workbook_session_id)

    def calculate(self, workbook_session_id: str | None = None) -> dict:
        path = f"/drives/{self.drive_id}/items/{self.item_id}/workbook/application/calculate"
        return self._graph_request("POST", path, {"calculationType": "Full"}, workbook_session_id=workbook_session_id)

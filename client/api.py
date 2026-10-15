from __future__ import annotations

import httpx

class ClientAccessRevoked(RuntimeError):
    pass

from .models import AuthorizationResult, ClientProfile


class GoldAIServer:
    def __init__(self, profile: ClientProfile, timeout: float = 10.0):
        self.profile = profile
        self.timeout = timeout

    @staticmethod
    def _headers(session_token: str = "") -> dict[str, str]:
        headers = {
            "ngrok-skip-browser-warning": "true",
            "User-Agent": "GOLD_AI_Client/1.0",
        }
        if session_token:
            headers["Authorization"] = f"Bearer {session_token}"
        return headers

    def authorize(self) -> AuthorizationResult:
        """Authorize on startup. No periodic heartbeat is used."""
        try:
            response = httpx.post(
                f"{self.profile.server_url.rstrip('/')}/v1/client/authorize",
                headers=self._headers(),
                json={
                    "client_id": self.profile.client_id,
                    "pairing_code": self.profile.pairing_code,
                    "mt5_login": self.profile.mt5_login,
                    "mt5_server": self.profile.mt5_server,
                    "telegram_username": self.profile.telegram_username or None,
                },
                timeout=self.timeout,
            )
            response.raise_for_status()
            data = response.json()
            return AuthorizationResult(
                allowed=bool(data.get("allowed", False)),
                display_name=str(data.get("display_name", "")),
                status=str(data.get("status", "UNKNOWN")),
                message=str(data.get("message", "")),
                session_token=str(data.get("session_token", "")),
            )
        except Exception as exc:
            return AuthorizationResult(
                allowed=False,
                status="SERVER_UNREACHABLE",
                message=str(exc),
            )

    def register_telegram(self, username: str) -> dict:
        response = httpx.post(
            f"{self.profile.server_url.rstrip('/')}/v1/client/telegram",
            headers=self._headers(),
            json={
                "client_id": self.profile.client_id,
                "pairing_code": self.profile.pairing_code,
                "telegram_username": username,
            },
            timeout=self.timeout,
        )
        response.raise_for_status()
        return response.json()


    def next_instruction(self, session_token: str) -> dict:
        response = httpx.get(
            f"{self.profile.server_url.rstrip('/')}/v1/instructions/next",
            headers=self._headers(session_token),
            timeout=self.timeout,
        )
        if response.status_code == 403:
            detail = ""
            try:
                detail = str(response.json().get("detail", "Access disabled."))
            except Exception:
                detail = "Access disabled."
            raise ClientAccessRevoked(detail)
        response.raise_for_status()
        return response.json()

    def acknowledge(
        self,
        session_token: str,
        instruction_id: int,
        status: str,
        message: str = "",
    ) -> dict:
        response = httpx.post(
            f"{self.profile.server_url.rstrip('/')}/v1/instructions/ack",
            headers=self._headers(session_token),
            json={
                "instruction_id": int(instruction_id),
                "status": status,
                "message": message,
            },
            timeout=self.timeout,
        )
        response.raise_for_status()
        return response.json()

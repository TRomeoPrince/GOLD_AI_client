from __future__ import annotations
from dataclasses import replace
import httpx
from .models import AuthorizationResult, ClientProfile

class ClientAccessRevoked(RuntimeError):
    pass

class SessionExpired(RuntimeError):
    pass

class ServerUnavailable(RuntimeError):
    pass

class GoldAIServer:
    def __init__(self, profile: ClientProfile, timeout: float = 10.0):
        self.profile, self.timeout = profile, timeout

    @staticmethod
    def _headers(session_token=""):
        headers = {"ngrok-skip-browser-warning": "true", "User-Agent": "AZT_Client/2.0"}
        if session_token:
            headers["Authorization"] = f"Bearer {session_token}"
        return headers

    def request(self, method, path, token="", **kwargs):
        headers = self._headers(token)
        try:
            response = httpx.request(method, self.profile.server_url.rstrip("/") + path,
                                     headers=headers, timeout=self.timeout, **kwargs)
        except (httpx.TimeoutException, httpx.NetworkError):
            raise ServerUnavailable("AZT server is unreachable; reconnecting automatically.") from None
        if response.status_code == 401:
            raise SessionExpired("Session expired; authorizing again.")
        if response.status_code == 403:
            try: detail = str(response.json().get("detail", "Access disabled."))
            except (ValueError, TypeError): detail = "Access disabled."
            raise ClientAccessRevoked(detail)
        if response.status_code >= 500:
            raise ServerUnavailable("AZT server is temporarily unavailable.")
        if response.status_code >= 400:
            try: detail = str(response.json().get("detail", "Request rejected."))
            except (ValueError, TypeError): detail = "Request rejected."
            raise ValueError(detail[:500])
        return response.json()

    def authorize(self):
        data = self.request("POST", "/v1/client/authorize", json={
            "pairing_code": self.profile.pairing_code,
            "mt5_login": self.profile.mt5_login,
            "mt5_server": self.profile.mt5_server,
            "telegram_username": self.profile.telegram_username,
            "display_timezone": self.profile.display_timezone,
        })
        return AuthorizationResult(**{key: data.get(key, default) for key, default in {
            "allowed": False, "display_name": "", "status": "UNKNOWN", "message": "",
            "session_token": "", "account_id": None, "max_mt5_accounts": 1,
            "display_timezone": "UTC",
        }.items()})

    def next_instruction(self, token, since=None):
        return self.request("GET", "/v1/instructions/next", token, params={"since": since} if since else {})

    def acknowledge(self, token, instruction_id, status, message=""):
        return self.request("POST", "/v1/instructions/ack", token, json={
            "instruction_id": int(instruction_id), "status": status, "message": message[:2000]})

    def risk_policy(self, token):
        return self.request("GET", "/v1/client/risk-policy", token)

    def subscription(self, session_token):
        return self.request("GET", "/v1/mobile/subscription", session_token)

    def overview(self, token): return self.request("GET", "/v1/azt/overview", token)
    def messages(self, token): return self.request("GET", "/v1/azt/messages", token)
    def mark_read(self, token, message_id): return self.request("POST", f"/v1/azt/messages/{int(message_id)}/read", token)
    def trades(self, token): return self.request("GET", "/v1/azt/trades", token)
    def journal(self, token, date=""):
        return self.request("GET", "/v1/azt/journal", token, params={"date": date} if date else {})
    def referrals(self, token): return self.request("GET", "/v1/azt/referrals", token)
    def link_referral(self, token, code): return self.request("POST", "/v1/azt/referrals/link", token, json={"code": code})
    def redeem(self, token, code): return self.request("POST", "/v1/azt/promos/redeem", token, json={"code": code})
    def preferences(self, token, zone): return self.request("POST", "/v1/azt/preferences", token, json={"display_timezone": zone})
    def plans(self, token): return self.request("GET", "/v1/azt/plans", token)
    def payment_methods(self, token): return self.request("GET", "/v1/azt/payment-methods", token)
    def payments(self, token): return self.request("GET", "/v1/azt/payments", token)
    def submit_payment(self, token, plan, method, proof="", transaction_hash=""):
        return self.request("POST", "/v1/azt/payments", token, json={"plan_code": plan, "method": method,
                            "proof": proof, "transaction_hash": transaction_hash})
    def telemetry(self, token, snapshot): return self.request("POST", "/v1/client/telemetry", token, json={"snapshot": snapshot})

    def register_telegram(self, username):
        return self.request("POST", "/v1/client/telegram", json={"pairing_code": self.profile.pairing_code,
                                                             "telegram_username": username})

def for_account(profile, account):
    return replace(profile, mt5_login=int(account["mt5_login"]), mt5_server=str(account["mt5_server"]))

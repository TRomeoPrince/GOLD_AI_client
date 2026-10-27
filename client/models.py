from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class ClientProfile:
    client_id: str = ""
    display_name: str = ""
    server_url: str = "https://grandpa-skier-sphere.ngrok-free.dev"
    pairing_code: str = ""
    telegram_username: str = ""
    telegram_enabled: bool = False
    mt5_login: Optional[int] = None
    mt5_server: str = ""
    display_timezone: str = "UTC"
    accounts: list[dict] = field(default_factory=list)
    retry_interval: float = 5.0
    retry_cap: float = 30.0
    retries_before_alert: int = 5
    alert_cooldown: float = 300.0


@dataclass
class AuthorizationResult:
    allowed: bool
    display_name: str = ""
    status: str = "UNKNOWN"
    message: str = ""
    session_token: str = ""
    account_id: int | None = None
    max_mt5_accounts: int = 1
    display_timezone: str = "UTC"


@dataclass
class TradeInstruction:
    instruction_id: str
    symbol: str
    side: str
    volume: float
    stop_loss: float
    take_profit: float
    strategy: str

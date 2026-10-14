from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass
class ClientProfile:
    client_id: str = ""
    display_name: str = ""
    server_url: str = "http://127.0.0.1:8765"
    pairing_code: str = ""
    telegram_username: str = ""
    telegram_enabled: bool = False
    mt5_login: Optional[int] = None
    mt5_server: str = ""


@dataclass
class AuthorizationResult:
    allowed: bool
    display_name: str = ""
    status: str = "UNKNOWN"
    message: str = ""


@dataclass
class TradeInstruction:
    instruction_id: str
    symbol: str
    side: str
    volume: float
    stop_loss: float
    take_profit: float
    strategy: str

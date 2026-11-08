from __future__ import annotations

from dataclasses import dataclass
from math import floor, isfinite
from datetime import datetime, timedelta, timezone
import time

import MetaTrader5 as mt5
from .clock import tick_epoch, tick_utc_epoch
from .symbols import resolve_symbol

MAGIC = 560090


@dataclass
class ExecutionResult:
    sent: bool
    ticket: int | None
    message: str
    volume: float = 0.0
    planned_risk_pct: float = 0.0
    portfolio_after_pct: float = 0.0


def _resolve_symbol(hint: str) -> str:
    return resolve_symbol(mt5, hint)


def _loss(direction: str, symbol: str, volume: float, entry: float, sl: float) -> float:
    order_type = mt5.ORDER_TYPE_BUY if direction == "BUY" else mt5.ORDER_TYPE_SELL
    pnl = mt5.order_calc_profit(order_type, symbol, volume, entry, sl)
    if pnl is None or not isfinite(float(pnl)):
        raise RuntimeError(f"Risk calculation failed: {mt5.last_error()}")
    return abs(min(float(pnl), 0.0))


def _volume_for_risk(
    direction: str,
    symbol: str,
    entry: float,
    sl: float,
    target_risk_pct: float,
    max_single_risk_pct: float,
) -> tuple[float, float]:
    account = mt5.account_info()
    info = mt5.symbol_info(symbol)
    if account is None or info is None:
        raise RuntimeError("Account/symbol info unavailable.")

    equity = float(account.equity)
    if not isfinite(equity) or equity<=0:
        raise RuntimeError("Invalid account equity; risk calculation blocked.")
    target_cash = equity * target_risk_pct / 100.0
    loss_one = _loss(direction, symbol, 1.0, entry, sl)
    if loss_one <= 0:
        raise RuntimeError("Invalid stop-loss risk.")

    raw = target_cash / loss_one
    vmin, vmax, step = float(info.volume_min), float(info.volume_max), float(info.volume_step)
    if raw < vmin:
        planned = _loss(direction, symbol, vmin, entry, sl)
        pct = 100.0 * planned / equity
        return (vmin, pct) if pct <= max_single_risk_pct else (0.0, pct)

    volume = floor(raw / step) * step
    volume = min(max(volume, vmin), vmax)
    volume = round(volume, 8)
    planned = _loss(direction, symbol, volume, entry, sl)
    pct = 100.0 * planned / equity
    if pct > max_single_risk_pct:
        return 0.0, pct
    return volume, pct


def _open_risk_pct(include_all_positions=False) -> float:
    account = mt5.account_info()
    if account is None or not isfinite(float(account.equity)) or float(account.equity) <= 0:
        return float("inf")
    equity = float(account.equity)
    total = 0.0
    positions = mt5.positions_get()
    if positions is None:
        return float("inf")
    for p in positions:
        if not include_all_positions and int(getattr(p, "magic", -1)) != MAGIC:
            continue
        sl = float(getattr(p, "sl", 0.0) or 0.0)
        if not isfinite(sl) or sl <= 0:
            return float("inf")
        direction = "BUY" if int(p.type) == int(mt5.POSITION_TYPE_BUY) else "SELL"
        order_type = mt5.ORDER_TYPE_BUY if direction == "BUY" else mt5.ORDER_TYPE_SELL
        pnl = mt5.order_calc_profit(
            order_type,
            str(p.symbol),
            float(p.volume),
            float(p.price_open),
            sl,
        )
        if pnl is None or not isfinite(float(pnl)):
            return float("inf")
        total += abs(min(float(pnl), 0.0))
    return 100.0 * total / equity


def _daily_profit_pct(strict=False, *, clock_offset_seconds=0) -> float:
    account = mt5.account_info()
    if account is None or not isfinite(float(account.equity)) or not isfinite(float(account.balance)):
        return float("inf")

    now = datetime.now(timezone.utc)
    start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    offset = timedelta(seconds=clock_offset_seconds)
    deals = mt5.history_deals_get(start + offset, now + offset)
    if strict and deals is None:
        raise RuntimeError("Daily MT5 history unavailable; order blocked.")
    deals = deals or ()

    realized = 0.0
    for d in deals:
        realized += float(getattr(d, "profit", 0.0) or 0.0)
        realized += float(getattr(d, "commission", 0.0) or 0.0)
        realized += float(getattr(d, "swap", 0.0) or 0.0)
        realized += float(getattr(d, "fee", 0.0) or 0.0)

    start_balance = float(account.balance) - realized
    if not isfinite(realized) or not isfinite(start_balance):
        return float("inf")
    if start_balance <= 0:
        return float("inf")

    profit_cash = max(0.0, float(account.equity) - start_balance)
    return 100.0 * profit_cash / start_balance


def _daily_loss_pct(strict=False, *, clock_offset_seconds=0) -> float:
    account = mt5.account_info()
    if account is None or not isfinite(float(account.equity)) or not isfinite(float(account.balance)):
        return float("inf")

    now = datetime.now(timezone.utc)
    start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    offset = timedelta(seconds=clock_offset_seconds)
    deals = mt5.history_deals_get(start + offset, now + offset)
    if strict and deals is None:
        raise RuntimeError("Daily MT5 history unavailable; order blocked.")
    deals = deals or ()

    realized = 0.0
    for d in deals:
        realized += float(getattr(d, "profit", 0.0) or 0.0)
        realized += float(getattr(d, "commission", 0.0) or 0.0)
        realized += float(getattr(d, "swap", 0.0) or 0.0)
        realized += float(getattr(d, "fee", 0.0) or 0.0)

    start_balance = float(account.balance) - realized
    if not isfinite(realized) or not isfinite(start_balance):
        return float("inf")
    if start_balance <= 0:
        return float("inf")

    loss_cash = max(0.0, start_balance - float(account.equity))
    return 100.0 * loss_cash / start_balance


def execute_instruction(
    payload: dict,
    risk_per_trade_pct: float = 0.9,
    max_open_risk_pct: float = 40.0,
    max_daily_loss_pct: float = 5.0,
    daily_profit_target_enabled: bool = False,
    daily_profit_target_pct: float = 0.0,
    *,
    max_single_risk_pct: float = 2.0,
    before_send=None,
    include_all_positions: bool = True,
    strict_history: bool = True,
) -> ExecutionResult:
    terminal = mt5.terminal_info()
    account = mt5.account_info()
    if terminal is None or account is None:
        raise RuntimeError("MT5 terminal/account unavailable.")
    if not getattr(terminal,"connected",False):
        raise RuntimeError("MT5 terminal disconnected.")
    if not isfinite(float(account.equity)) or not isfinite(float(account.balance)) or float(account.equity)<=0 or float(account.balance)<=0:
        return ExecutionResult(False,None,"Account equity/balance must be finite and positive.")
    controls=(float(risk_per_trade_pct),float(max_open_risk_pct),float(max_daily_loss_pct),float(max_single_risk_pct))
    if not all(isfinite(value) and value>0 for value in controls):
        return ExecutionResult(False,None,"Invalid risk policy; order blocked.")
    risk_per_trade_pct=min(2.0,float(risk_per_trade_pct))
    max_single_risk_pct=min(2.0,float(max_single_risk_pct))
    max_open_risk_pct=min(40.0,float(max_open_risk_pct))
    max_daily_loss_pct=min(10.0,float(max_daily_loss_pct))
    if not bool(getattr(terminal, "trade_allowed", False)):
        return ExecutionResult(False, None, "Algo Trading is disabled.")

    if daily_profit_target_enabled and (not isfinite(float(daily_profit_target_pct)) or float(daily_profit_target_pct) <= 0):
        return ExecutionResult(False, None, "Invalid daily profit target; order blocked.")

    direction = str(payload["direction"]).upper()
    if direction not in {"BUY", "SELL"}:
        raise ValueError("Unsupported trade direction.")
    symbol = _resolve_symbol(
        str(payload.get("market") or payload.get("symbol_hint") or "GOLD")
    )
    sl = float(payload["stop_loss"])
    tp = float(payload["take_profit"])
    tick = mt5.symbol_info_tick(symbol)
    if tick is None:
        return ExecutionResult(False, None, f"No live tick for {symbol}.")

    clock_offset = 0
    if strict_history:
        try:
            quote_utc = tick_utc_epoch(mt5, symbol, tick)
            quote_age = time.time() - quote_utc
            clock_offset = round(tick_epoch(tick) - quote_utc)
        except RuntimeError as exc:
            return ExecutionResult(False, None, f"STALE_QUOTE: {exc}")
        if not -5 <= quote_age <= 120:
            return ExecutionResult(False, None, "STALE_QUOTE: no recent broker tick.")

    # The day is defined in UTC. The broker history query takes feed-clock
    # bounds, as does telemetry, so include today's shifted recent deals.
    if daily_profit_target_enabled:
        daily_profit = _daily_profit_pct(strict_history, clock_offset_seconds=clock_offset)
        if daily_profit >= float(daily_profit_target_pct):
            return ExecutionResult(False, None,
                f"DAILY_PROFIT_TARGET_REACHED: {daily_profit:.2f}% >= {float(daily_profit_target_pct):.2f}%.")
    daily_loss = _daily_loss_pct(strict_history, clock_offset_seconds=clock_offset)
    if daily_loss >= float(max_daily_loss_pct):
        return ExecutionResult(False, None,
            f"DAILY_LOSS_BLOCKED: {daily_loss:.2f}% >= {float(max_daily_loss_pct):.2f}%.")

    price = float(tick.ask if direction == "BUY" else tick.bid)
    valid = sl < price < tp if direction == "BUY" else tp < price < sl
    if not valid:
        return ExecutionResult(
            False,
            None,
            "STALE_SIGNAL: current price is outside SL/TP geometry.",
        )

    volume, single_pct = _volume_for_risk(
        direction,
        symbol,
        price,
        sl,
        float(risk_per_trade_pct),
        min(float(risk_per_trade_pct), float(max_open_risk_pct), float(max_single_risk_pct), 2.0),
    )
    if volume <= 0:
        return ExecutionResult(
            False,
            None,
            f"RISK_BLOCKED: broker minimum would risk {single_pct:.2f}%.",
            planned_risk_pct=single_pct,
        )

    open_pct = _open_risk_pct(include_all_positions)
    post_pct = open_pct + single_pct
    if post_pct > float(max_open_risk_pct) + 0.001:
        return ExecutionResult(
            False,
            None,
            f"PORTFOLIO_RISK_BLOCKED: {post_pct:.2f}% > {float(max_open_risk_pct):.2f}%.",
            volume=volume,
            planned_risk_pct=single_pct,
            portfolio_after_pct=post_pct,
        )

    order_type = mt5.ORDER_TYPE_BUY if direction == "BUY" else mt5.ORDER_TYPE_SELL
    base = {
        "action": mt5.TRADE_ACTION_DEAL,
        "symbol": symbol,
        "volume": volume,
        "type": order_type,
        "price": price,
        "sl": sl,
        "tp": tp,
        "deviation": 20,
        "magic": MAGIC,
        "comment": f"AZT:{str(payload.get('strategy_id','REMOTE'))}"[:31],
        "type_time": mt5.ORDER_TIME_GTC,
    }

    info = mt5.symbol_info(symbol)
    advertised = int(getattr(info, "filling_mode", -1)) if info is not None else -1
    candidates = []
    if advertised & 1:
        candidates.append(int(mt5.ORDER_FILLING_FOK))
    if advertised & 2:
        candidates.append(int(mt5.ORDER_FILLING_IOC))
    candidates += [
        int(mt5.ORDER_FILLING_RETURN),
        int(mt5.ORDER_FILLING_FOK),
        int(mt5.ORDER_FILLING_IOC),
    ]

    tried = set()
    for mode in candidates:
        if mode in tried:
            continue
        tried.add(mode)
        request = dict(base)
        request["type_filling"] = mode
        check = mt5.order_check(request)
        if check is None or int(check.retcode) != 0:
            continue
        if before_send is not None:
            before_send()
        result = mt5.order_send(request)
        if result is None:
            raise RuntimeError("MT5 submission returned no result; review broker orders before retrying.")
        done = int(result.retcode) in {
            int(getattr(mt5, "TRADE_RETCODE_DONE", 10009)),
            int(getattr(mt5, "TRADE_RETCODE_DONE_PARTIAL", 10010)),
        }
        ticket = int(
            getattr(result, "order", 0) or getattr(result, "deal", 0) or 0
        ) or None
        return ExecutionResult(
            done,
            ticket,
            str(getattr(result, "comment", "")),
            volume,
            single_pct,
            post_pct,
        )

    return ExecutionResult(
        False,
        None,
        "ORDER_REJECTED: no supported filling mode.",
        volume,
        single_pct,
        post_pct,
    )

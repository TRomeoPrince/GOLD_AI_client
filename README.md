# GOLD_AI Client

Thin Windows execution client for GOLD_AI Level-2 protection.

## Design
- Core strategies stay on the owner's GOLD_AI server.
- This client contains no strategy logic.
- It connects to the local MT5 terminal, sends account/market state to the server, receives signed trade instructions, and executes them.
- Server authorization is checked at startup and on every trading instruction/request. There is no periodic licensing heartbeat.
- If access is revoked, no new trade instructions are accepted. Existing positions remain locally protected by their existing SL/TP.
- Telegram notifications are optional. The onboarding UI asks for a Telegram username and tells the user to send /start to the configured GOLD_AI Telegram bot.
- The server owns the internal license/customer identity. The owner can label a customer with any friendly name such as SOSA; the end user does not need to see the internal license identifier.

## First milestone
This repository currently contains the client shell and API contract. MT5 execution wiring will be added after the server endpoints are finalized.

## Run
```cmd
py -m venv .venv && .venv\Scripts\python -m pip install -r requirements.txt && .venv\Scripts\python app.py
```

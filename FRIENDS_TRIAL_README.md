# AZT Friends Trial — 14-Day Windows Setup

**Build output:** `AZT_Friends_Trial_Setup.exe` from the GitHub Actions workflow **Build AZT Friends 14-Day Trial Installer**.

1. Have the AZT administrator create a distinct `CLIENT_PC` client and pairing code for you, and issue its **14-day distributor trial** on the owner server.
2. Run the installer (per-user, no admin rights needed). The installation includes an expiry-check Task Scheduler entry created automatically after first successful pairing.
3. Open MetaTrader 5 and sign in to your account. Open **AZT Friends Trial**, add your MT5 account, browse to that terminal's `terminal64.exe`, enter the correct login/server and assigned pairing code, save, and select **Connect / Refresh**.
4. First valid pairing starts your 14 days **on owner UTC time**, independent of when the EXE was downloaded. Adjust client trade risk and select **Start Automated Trading** only when ready. Use a DEMO account for initial testing.
5. Once expired, the server blocks new signals immediately. The client closes its workers safely. Windows checks expiry every 30 minutes when the account is signed in and uninstalls the trial edition after it closes.

**Important:** This is an evaluation trading tool, not a guarantee of profits or uptime. Broker orders already submitted remain with MT5 and the broker; check and manage any open trades independently, especially at expiry. The uninstaller deliberately keeps your local profile, order ledger, logs, MT5 installation, and any paid AZT Client installation intact.

To uninstall early: **Settings → Apps → Installed apps → AGORA ZION TRADER - Friends Trial → Uninstall**. If Task Scheduler access is blocked, the server still stops new trading after 14 days, and you can uninstall manually.

The older 30-day distributor edition and production AZT Client are not changed by this installer. Do not share pairing codes.

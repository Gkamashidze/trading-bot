# Credential exposure and dashboard access

1. Revoke the exposed Telegram token with the official @BotFather `/revoke`
   command. Generate a replacement with `/token` if needed. Do not paste tokens
   into chat, issue descriptions, terminal command text or screenshots.
2. Deploy and verify the log redaction change before setting the replacement in
   Railway `giving-purpose` → `trading-bot` → Variables → `TELEGRAM_BOT_TOKEN`.
   The old token remains invalid even if historical logs retain it.
3. Set a separate password-manager-generated `DASHBOARD_API_KEY` of at least 32
   characters. The browser login is `operator` and that secret as the password.
   API clients use `X-API-Key`; query-string credentials are rejected. Never reuse
   exchange keys or the application's `SECRET_KEY` as the dashboard password.
4. Confirm anonymous dashboard, evidence/export and administrative requests return
   401, while health probes remain accessible. Without configured production
   credentials, protected routes return 503. Browser mutations require same origin.
5. Confirm current Telegram polling succeeds after replacement. Inspect logs using
   a secret-aware filter; never print raw third-party request URLs. Redaction is
   applied after exception formatting to JSON and console logs.
6. Check whether any other credential was exposed. Rotate only affected secrets;
   document the scope and UTC timeline without storing secret values.

The dashboard cannot enable real trading. A separate, current, named approval and
verified readiness evidence are required before that workflow can be considered.

# Deployment rollback

Owner: operator. All times and incident records use UTC.

Use this procedure if a deployment fails readiness, corrupts portfolio recovery,
breaks evidence capture, or introduces an authentication or credential leak.

1. Keep `live_trading_enabled=false` and the micro-live global code gate disabled.
   If an already-authorized live account is involved, stop submissions through the
   operator kill switch before investigating. Do not retry uncertain orders.
2. In Railway, open `giving-purpose` → `trading-bot` → Deployments. Select the last
   verified deployment and use Rollback. Preserve the `/data` volume and Postgres.
   A code rollback must never delete evidence, orders, audit events or snapshots.
3. Database migration 0009 adds a nullable audit ordering column. Old application
   versions can use the expanded schema. Do not run `alembic downgrade` against
   production as part of an ordinary code rollback.
4. Verify `/readyz` returns 200 with both database and scheduler ready. Open the
   authenticated dashboard and inspect job execution, market timestamps, open
   positions, order reconciliation, paper mode and evidence persistence.
5. Run the authenticated `/go_live/report`. Failures remain blockers; do not flip
   flags or grant approvals to make the report pass. Confirm no duplicate orders
   were created across the restart.
6. If a real broker position ever needs flattening, reconcile it directly with the
   venue and use the pre-authorized broker close procedure. This paper-only system
   is not authorized to place a flattening trade. Obtain the operator's instruction.
7. Record the deployment hashes, UTC timeline, readiness results and remediation in
   an incident report. Revoke exposed credentials before restoring affected access.

Verification before any micro-live authorization: rehearse a code rollback in an
isolated environment and have the operator confirm the venue-specific flattening
procedure. The presence of this runbook does not constitute that confirmation.

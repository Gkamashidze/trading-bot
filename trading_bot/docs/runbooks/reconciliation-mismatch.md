# Reconciliation mismatch

Keep live trading disabled while investigating any unresolved mismatch. Do not
clear a block merely to make the readiness gate green.

1. Read the latest reconciliation report and associated startup messages. A failed
   OMS history restore or unavailable portfolio must block submissions.
2. Compare the venue's open order identifiers, fills, balances and positions with
   the durable OMS and portfolio records. Do not repeat an uncertain submission.
3. PaperExchange settles a simulation immediately and queues no remainder.
   Historical `partially_filled` paper records describe an actual simulated fill,
   not an outstanding venue order. Preserve these records and their quantities.
   Real exchange partial fills remain open and must be reconciled with the venue.
4. Repair the underlying state or adapter problem, retaining evidence and audit
   history. Re-run reconciliation and require a recent clean result before review.
5. For live venue uncertainty, use the venue-specific position-close and rollback
   procedure, obtain operator review, and record the incident and resolution.

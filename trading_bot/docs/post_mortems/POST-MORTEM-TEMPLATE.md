# Post-Mortem: [Incident Title]

**Date:** YYYY-MM-DD
**Severity:** P0 | P1 | P2 | P3
**Duration:** HH:MM
**Author:** [name]
**Status:** Draft | In Review | Final

> **Blameless culture:** This post-mortem is about learning, not blame.
> The goal is to improve the system so this class of failure cannot recur.
> Personal criticism is inappropriate and counterproductive.

---

## Summary

One paragraph: what happened, what was the impact, how it was resolved.

---

## Timeline

All times in UTC.

| Time | Event |
|------|-------|
| HH:MM | Alert fired |
| HH:MM | Operator acknowledged |
| HH:MM | Root cause identified |
| HH:MM | Remediation applied |
| HH:MM | Incident resolved |
| HH:MM | Post-mortem created |

---

## Root Cause

What was the fundamental cause of the incident?

_Use the "5 Whys" method: ask "why" until you reach a systemic root cause,
not just a proximate cause (e.g. not "the code had a bug" but "the code had
a bug because our property-based tests don't cover this edge case because
we only run them on PRs to main, not on feature branches")._

---

## Impact

- Capital at risk: $X (paper) | $X (live)
- Positions affected: [describe]
- Duration of trading halt: X minutes
- Data gap: [if any]
- Customer/operator experience: [describe]

---

## Detection

- How was the incident detected? (Alert? Operator? Customer?)
- How long between incident start and detection? (MTTD)
- Could detection have been faster? How?

---

## Contributing Factors

List factors that contributed to the incident (not the root cause, but things
that made the incident more likely or more severe):

1. Factor A (e.g. "reconnect logic had no backoff — caused rate limit exhaustion")
2. Factor B
3. Factor C

---

## What Went Well

Things that worked as designed:

1. Kill switch fired correctly within 2 minutes
2. Audit log captured all events during the incident
3. Runbook was clear and resolved the issue in X minutes

---

## What Went Poorly

Things that failed or were unclear:

1. Alert threshold was too high — detected 15 minutes after start
2. Runbook step 3 was incorrect — had to improvise
3. No monitoring for [X]

---

## Action Items

| Action | Owner | Due Date | Priority |
|--------|-------|----------|----------|
| Fix alert threshold | ops | YYYY-MM-DD | P1 |
| Update runbook step 3 | ops | YYYY-MM-DD | P2 |
| Add chaos test for this scenario | dev | YYYY-MM-DD | P2 |
| Add monitoring for [X] | dev | YYYY-MM-DD | P2 |

---

## Lessons Learned

What would we tell a colleague so they can avoid this class of failure?

---

## References

- Runbook used: [link]
- Logs: [link or grep command]
- Metrics dashboard: [link]
- Relevant ADR: [link]

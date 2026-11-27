---
name: shared-usage-limits
description: >
  Library skill — not user-triggered. Shared Claude usage meter checks for
  scheduled/automated skills. Read this skill whenever another skill instructs
  you to run usage limit checks.
---

# Shared: Usage Limits

Usage limit checks for scheduled and automated skills that run on a Cowork schedule.

---

## Thresholds

| Meter | Skip threshold (don't start) | Stop threshold (abort mid-run) |
|-------|------------------------------|-------------------------------|
| Weekly usage | ≥ 85% | ≥ 90% |
| Session usage | ≥ 75% | ≥ 85% |

These thresholds are the same across all skills and must not be modified per-skill.

---

## Pre-Run Check

Run **before any work begins** in the calling skill.

Check Claude's current usage meters (visible in the Cowork/Claude UI):

- If **weekly usage ≥ 85%** → log the error (see Error Logging below) then stop. Do not proceed.
- If **session usage ≥ 75%** → log the error then stop. Do not proceed.

---

## Mid-Run Check

Run **after completing each logical unit of work** (each site, each post, each listing).

- If **weekly usage hits 90%** → log the error, save any in-progress log file, then stop.
- If **session usage hits 85%** → log the error, save any in-progress log file, then stop.

Checking after each unit (rather than mid-unit) ensures the log is always in a
consistent saved state before stopping.

---

## Error Logging

The calling skill specifies which logging mode to use.

### Mode A — shared error log

Log through [`shared-error-log`](/mnt/skills/user/shared-error-log/SKILL.md). Do **not** write to any per-skill Errors table. Set
`source` = the calling skill's folder name, `item` = `-`, `note` = the usage message:

Pre-run skip:
```bash
log_error "<skill>" "-" "Weekly usage above 85% — run skipped"
log_error "<skill>" "-" "Session usage above 75% — run skipped"
```

Mid-run stop:
```bash
log_error "<skill>" "-" "Weekly usage hit 90% — stopped early"
log_error "<skill>" "-" "Session usage hit 85% — stopped early"
```

`log_error` (defined in `shared-error-log`) handles the date and escaping.

### Mode B — Chat summary (no log file)

If the calling skill has no Obsidian log file, report to the user in chat:

```
⚠️ Usage limit reached — run skipped.
Weekly: X% | Session: Y%
```

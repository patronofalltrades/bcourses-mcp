---
name: bcourses-calendar-sync
description: Reconcile bCourses deadlines into a calendar — preview the changes, confirm, then apply.
---

# Calendar sync

Drags a deadlines calendar back into agreement with Canvas: create what is new, rewrite what moved, delete what was cancelled inside the window, leave the rest alone. Idempotent — run it fifty times and nothing happens after the first.

This skill needs the companion macOS sync script described in `docs/calendar-sync.md`. The MCP server alone reads Canvas; it does not write to Apple Calendar.

## The sequence, always in this order

1. **Preview.** Run the sync in dry-run mode. Nothing is written.
2. **Show the plan** in plain words: how many to create, update, delete, already in sync, filtered out. Name the specific items being created or moved — a count alone is not reviewable.
3. **Wait for a yes.** Then re-run the identical command, applying.
4. **Report what actually happened**, from the second run. Never claim a sync from the strength of a preview.

If nobody is there to answer — a scheduled or unattended run — stop after the preview.

## Rules

- **Never force a rebuild on a schedule, and never without asking.** A full purge-and-recreate re-adds every event, and an alarm whose trigger time has already passed can fire the instant its event is created. It is the repair path for a drifted calendar, not a routine.
- **The window bounds deletion.** An item due beyond the horizon is out of scope, not missing, so a narrow window never deletes what it cannot see. A much wider window with apply can delete more than expected — say what that means before running it.
- **Filtered-out items are deliberate.** Recurring class meetings usually already arrive via a subscribed Canvas `.ics` feed, and past-due items are dropped so their alarms do not fire on creation. Report the count; explain only if asked.
- **A hand-deleted event is invisible to the sync.** State still holds its UID, so it reports as "already in sync" while nothing is on the calendar. That symptom — the user swears an event is gone but the sync says it is fine — is what a forced rebuild fixes.

## Why reconcile rather than append

An append-only calendar sync is easy and wrong. Run it twice and everything is on there twice. Run it after a due date moves and the dead date sits next to the live one with no way to tell which to plan around. That calendar is worse than no calendar, because the user will believe it.

Reconciling is also the only reason the job is safe on a timer. If running it too often could make a mess, you would have to be careful about when it ran — and being careful about when things run is just remembering things with extra steps.

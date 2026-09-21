---
name: bcourses-week
description: What's due across all of the user's bCourses courses over the next week or two, in their timezone, clustered by day with collisions flagged.
---

# Week ahead

One answer to "what do I owe this week" instead of five course tabs.

## The walk

0. **`get_my_profile`** — one cheap call that proves the token still works. Do this first, every time.

   A Canvas token expires on a date the user set when they made it, and the failure is silent: every call returns 401 and a scheduled sync fails into a log nobody reads. Catching it here, in the thing they run weekly, is the difference between noticing in September and noticing during finals.

   If it returns **401**, stop. Do not report an empty week — an empty week and an expired token look identical, and the wrong one is reassuring. Say the token has expired or been revoked, and give them the fix:

   ```sh
   security add-generic-password -U -a "$USER" -s "bcourses-student-mcp" -w
   ```

   They will need a fresh token from bCourses → Account → Settings → Approved Integrations, and the MCP client restarted afterwards.

1. **`list_courses`** — every active course and its ID.
2. **`list_assignments`** for each, with `bucket: "upcoming"`. Run them together rather than one at a time.
3. Optionally **`list_calendar_events`** with a date range, for anything that is not an assignment.

Default to a 10-day horizon. "This week" means 7; "the next couple of weeks" means 14.

## Convert the times

Due dates come back in **UTC**. Convert to the user's timezone before reporting anything. An 06:59:59 UTC deadline is 11:59pm the previous night in US Pacific; report it as the UTC date and you have moved their deadline by a day.

## Report it

Group by day, earliest first. Per item: the time, a short course name (not the full Canvas title, which is often `EW & MBA 236V-LEC-001 - …`), and what it is.

Then say the thing a list does not:

- **Collisions.** Two or more items the same night is the finding, not a footnote. Name them together.
- **Bulk administrivia.** When the same assignment appears in every course — an academic integrity acknowledgement, say — collapse it to one line saying it hits all of them, rather than repeating it six times.
- **The shape of the week.** Which night is heavy, which is clear.

Keep it short. This gets read on a phone.

## Rules

- **Report only what the data says.** Do not estimate how long something will take unless asked.
- **Empty is often correct** — but only once step 0 passed. Canvas returns only published items with due dates, so a genuinely quiet week is normal; an expired token produces the same silence and must never be reported as a quiet week.
- **Mention an expiry that is close.** If the user says their token expires within about two weeks, say so once while they are already thinking about the calendar. Do not nag about it every run.
- **Dropped courses vanish silently.** If a course the user mentions is absent, run `list_courses` and say so rather than reporting a clean week.
- **A 403 on one course is not a failure of the whole run.** Report the others and name the one that refused.
- Do not offer to sync a calendar unprompted.

---
name: bcourses-week
description: What's due across all of the user's bCourses courses over the next week or two, in their timezone, clustered by day with collisions flagged.
---

# Week ahead

One answer to "what do I owe this week" instead of five course tabs.

## The walk

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
- **Empty is often correct.** Canvas returns only published items with due dates.
- **Dropped courses vanish silently.** If a course the user mentions is absent, run `list_courses` and say so rather than reporting a clean week.
- **A 403 on one course is not a failure of the whole run.** Report the others and name the one that refused.
- Do not offer to sync a calendar unprompted.

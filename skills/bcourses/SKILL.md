---
name: bcourses
description: Read the user's UC Berkeley bCourses (Canvas) data — courses, deadlines, assignments, pages, readings, files, syllabus — through the bCourses MCP server.
---

# bCourses

bCourses is UC Berkeley's Canvas instance. The `bcourses` MCP server exposes it as tools. This skill is the map: which tool to reach for, and how Canvas actually behaves here.

## Where to start

Always `list_courses` first, to get numeric course IDs. Never guess an ID.

Then `get_course` for metadata and syllabus, or `list_modules` for the real structure — modules and their items are the reliable way into a course's content.

## Tools

**Orientation** — `get_my_profile`, `list_courses`, `get_course`, `search_course_content`

**Structure** — `list_modules`, `get_module`, `list_module_items`, `list_pages`, `get_page`

**Work** — `list_assignments` (buckets: `past`, `overdue`, `undated`, `ungraded`, `unsubmitted`, `upcoming`, `future`), `get_assignment`, `get_my_submission`

**Communication** — `list_announcements`, `list_discussions`, `get_discussion`, `list_conversations`, `get_conversation`

**Files** — `list_files`, `get_file`

**Writes** — `upload_submission_file` then `submit_assignment`; `post_discussion_entry`, `reply_to_discussion_entry`, `add_submission_comment`, `send_message`, `create_personal_calendar_event`, `edit_own_discussion_entry`, `mark_module_item_complete`, `update_conversation_state`, `update_personal_calendar_event`

## Rules

- **Before any write, say what you are about to do and wait.** Name the assignment, quote the content, then act. A resubmission overwrites the previous one.
- **Never claim a write succeeded unless the tool returned success.** If it errored, say so plainly.
- **Never create or modify instructor-owned content** — assignments, pages, modules, announcements, grades, rosters, course files, course-wide calendar events. No tool does this, and none should be improvised from another.
- **`send_message` is for named individuals only.** Course-wide and group-wide recipients are rejected by design.
- **Check the course's AI policy before drafting anything graded.** Several courses ban generative AI for reflections, discussion posts and exams. The tools do not know the syllabus; the user does. If asked for something a course forbids, say so once and offer to help them think it through instead.

## Reading the results

- **A 403 is ambiguous.** It means either the instructor hid that tab or the enrollment ended, and Canvas gives no way to tell. Run `list_courses` to check the course is still active before concluding content is missing.
- **Empty is often correct.** Canvas returns only published items with due dates. Early in a term, many syllabi are not posted.
- **The Files tab lies.** `list_files` often 403s while the individual files are perfectly readable, because permission is per object, not per tab. Reach content through `list_modules` then `get_page`, collect the `/files/N` references out of the page HTML, and resolve each with `get_file`.
- **The syllabus body is a file source**, not just prose. Instructors attach readings directly to it, and it is not a page, so a modules-only walk misses them.
- **Due dates come back in UTC.** Convert to the user's timezone before reporting. A 06:59:59 UTC deadline is 11:59pm the previous night in US Pacific — getting this wrong moves a deadline by a day.

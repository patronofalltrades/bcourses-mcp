---
name: bcourses-class-prep
description: Prepare for a specific bCourses class session — pull that week's page, find the assigned readings and cases, and write a prep brief.
---

# Class prep

Turn "I have New Venture Finance Thursday" into a brief the user can read on the train.

## The walk

1. **`list_courses`** — map the course name they used to its ID. If two could match, ask.
2. **`list_modules`** with items — find the entry for the session in question. Pages are usually `week-1`, `class-3` or similar; the slug is what step 3 takes.
3. **`get_page`** — the session page. This is where the instructor says what to read and what to be ready for.
4. **`get_course`** — read the syllabus body when the page is thin. Several courses put the entire per-class reading list there and nowhere else, and instructors attach PDFs directly to it.
5. **`list_files`** — only if 3 and 4 came up short. Expect it to 403; if it does, go back to the pages and pull the `/files/N` references out of their HTML, then `get_file` each one.
6. **`list_announcements`** for the last two weeks — **always**. Instructors change assignments here, and the change often contradicts the page.
7. **`list_assignments`** with `bucket: "upcoming"` — what is actually due before the session.

## The brief

Prose the user can act on, not a file dump:

- **What's due before class**, with the real deadline in their timezone.
- **Each reading**: its argument in two or three sentences, and the one idea likely to be cold-called. Name author and title so they can find it.
- **The case, if there is one**: the decision on the table, who makes it, and the two or three numbers that decide it.
- **What changed**, if an announcement moved anything.
- **The gaps** — a reading not posted, a link off Canvas they have to open themselves.

Keep it to what a prepared person carries into the room.

## Rules

- **Read before you summarize.** Never write a brief from a filename. If a document cannot be fetched, say the reading could not be read — do not infer its content from its title.
- **Scanned PDFs have no text layer.** Say which reading they will have to open themselves.
- **Cases are copyrighted.** Summarize the situation and the decision; do not reproduce case text at length.
- **A 403 is ambiguous** — hidden tab or ended enrollment. Check `list_courses` before concluding the material is gone.
- **Check the course's AI policy.** Prep is almost always fine; drafting a graded reflection or discussion post often is not. If the syllabus forbids it, say so once and offer to help them think it through instead.

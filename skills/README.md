# Skills

The MCP server gives Claude the tools. These give it the judgement — which tool to reach for, what a 403 actually means here, and what a useful answer looks like.

| Skill | Ask it for | Needs |
| --- | --- | --- |
| `bcourses` | Anything Canvas. The base map. | The MCP server |
| `bcourses-week` | "What's due this week?" | The MCP server |
| `bcourses-class-prep` | "Prep me for New Venture Finance Thursday" | The MCP server |
| `bcourses-calendar-sync` | "Put my deadlines on my calendar" | The macOS scripts in `../macos` |

Install `bcourses` at minimum. The other three assume its conventions and are worth adding as you find you want them.

## Installing

Each skill is a folder with a `SKILL.md` inside. Copy the folders you want into the skills directory your client reads.

**Claude Code** — per project or for everything:

```sh
mkdir -p ~/.claude/skills
cp -R skills/bcourses ~/.claude/skills/
cp -R skills/bcourses-week ~/.claude/skills/
```

Use `.claude/skills/` inside a project directory instead if you would rather keep them scoped to one repo.

**Claude Desktop and Cowork** — skills are managed in the app rather than on disk. Open the SKILL.md, copy its contents, and create a skill with that body. The name and description in the frontmatter are what decide when a skill fires, so keep them.

Restart the client after adding a skill.

## Checking it worked

Ask something the skill should catch — "what's due this week?" — and watch whether Claude calls `get_my_profile` and `list_courses` before answering. If it asks you for a course ID instead, the skill is not loading; check the file is at `<skills dir>/<name>/SKILL.md` and that the frontmatter survived the copy.

## Changing them

These are starting points, not a framework. The most common edits:

- **Your timezone.** `bcourses-week` says US Pacific in its example. Canvas returns UTC regardless; change the example to wherever you are.
- **Your horizon.** The default is 10 days because that is roughly how far ahead a weekly planning session is useful. Shorten it if you plan in tighter loops.
- **Your courses' AI policies.** Several courses ban generative AI for reflections, discussion posts and exams. The skills say to check the syllabus, which is honest but passive. If you know a specific course forbids it, name that course in the skill — a rule beats a reminder.

A skill is a text file you own. Rewriting one to match how you actually work is the point, not a workaround.

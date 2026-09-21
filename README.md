# bCourses MCP

Your deadlines, readings and course pages, available to Claude. A student-scoped [Model Context Protocol](https://modelcontextprotocol.io) server for UC Berkeley's Canvas instance, bCourses.

bCourses knows every assignment, every due date, every reading. It will not hand any of that to your calendar, your phone, or an assistant in a shape you can use. This closes that gap.

Runs entirely on your own machine. Your token never leaves it.

```
git clone https://github.com/patronofalltrades/bcourses-mcp.git
cd bcourses-mcp
./scripts/setup.sh
```

Requires macOS and Node 20 or newer.

---

## Read this before you make a token

A Canvas personal access token has **no permission scoping**. It is not read-only, it cannot be limited to one course, and it cannot be restricted to safe operations. It acts as you: it can read your grades and submit your coursework.

That single fact drives every design decision here.

- **The token lives in your macOS Keychain.** Never in a `.env`, never in a config file, never in your shell history. `setup.sh` refuses to run if it finds a token in a `.env`, and it passes the token to macOS via a prompt rather than a command argument, so it never appears in `ps`.
- **Set an expiry when you create the token.** Expiry is the only limit Canvas offers. End of term is a sensible default.
- **Never paste the token into a chat window** — including a chat with Claude. If it is exposed, revoke it at bCourses → Account → Settings → Approved Integrations. Revoking is the fix; deleting the message is not.
- **Do not deploy this for other people.** The server has an HTTP mode for local development, but hosting it so classmates can "just log in" would mean holding a pile of unscoped credentials that can submit coursework as them. Everyone runs their own copy. That is the whole security model.

## What it can and cannot do

It reads your courses, and it writes only things that are yours to write.

**Reads** — profile, courses, modules, pages, assignments and due dates, your own submissions, announcements, discussions, calendar events, files, and your Canvas Inbox.

**Writes, on your behalf** — submit or resubmit an assignment, upload a submission file, post or reply in a discussion, comment on your own submission, message named individuals, and manage your personal calendar events.

**Deliberately absent** — there are no tools for creating or changing assignments, pages, modules, announcements, grades, rosters, course files, or course-wide calendar events. Those are the instructor's. The boundary is enforced by the tools not existing, not by asking the model nicely.

Ownership is verified server-side before any write. Submissions always use Canvas's `self` route. Editing a discussion entry checks that the entry is yours. Course-wide and group-wide message recipients are rejected.

### A word about submitting

`submit_assignment` works, and a resubmission overwrites the previous one. Test it against a low-stakes assignment before you rely on it for graded work, and read what Claude is about to submit before you say yes. Check your own course's policy on AI use — several ban it for reflections and exams — and follow it. The tool does not know your syllabus.

## Setup

### 1. Clone and run setup

```sh
git clone https://github.com/patronofalltrades/bcourses-mcp.git
cd bcourses-mcp
./scripts/setup.sh
```

The script checks your Node version, prompts for your token into the Keychain, runs `npm install` and `npm run build` in `server/`, verifies the token against bCourses, and prints your registration command.

To do it by hand instead:

```sh
cd server
npm install
npm run build
security add-generic-password -U -a "$USER" -s "bcourses-student-mcp" -w
```

The last command prompts for the token without echoing it or putting it in your shell history.

### 2. Register with your client

**Claude Code**

```sh
claude mcp add bcourses -- /absolute/path/to/bcourses-mcp/server/bin/start-bcourses-mcp
```

**Claude Desktop** — edit `~/Library/Application Support/Claude/claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "bcourses": {
      "command": "/absolute/path/to/bcourses-mcp/server/bin/start-bcourses-mcp"
    }
  }
}
```

Paths must be absolute. That file is plain JSON, so `~` and `$HOME` are not expanded. Quit with Cmd-Q and reopen; closing the window is not enough.

The launcher reads your token from the Keychain and exports it only into the server process. macOS may ask permission the first time.

### 3. Verify

Ask Claude to check the connection, or run it directly:

```sh
cd server && npm test        # mocked Canvas, no token needed
npm run check                # typecheck
```

## Another Canvas school?

Set `BCOURSES_BASE_URL` to your institution's Canvas origin. The tools are plain Canvas LMS API calls — nothing here is Berkeley-specific except the default URL and the behaviour notes below. The config refuses any non-HTTPS URL that is not localhost.

## Skills

`skills/` holds four skills that turn the raw tools into the things you actually ask for. Installation and how to adapt them: [skills/README.md](skills/README.md).

| Skill | What it does |
| --- | --- |
| `bcourses` | The base layer: which tool to reach for, how Canvas behaves here, what a 403 means. |
| `bcourses-week` | What's due across every course in the next N days, in your timezone, with collisions flagged. |
| `bcourses-class-prep` | For one class session: pull the page, find the readings, extract the PDFs, write a prep brief. |
| `bcourses-calendar-sync` | Reconcile deadlines into a calendar, preview first, apply on your say-so. |

The sync skill assumes the companion macOS scripts described in `docs/calendar-sync.md`; the other three work with the MCP server alone.

## What Canvas actually does here

Six weeks of using this against real Berkeley courses produced a map that the API documentation does not give you. Worth knowing before you conclude something is broken.

| Endpoint | Reality |
| --- | --- |
| `courses/:id/files` | 403 on most courses — instructors hide the Files tab |
| `courses/:id/pages` (index) | 404 frequently — Pages tab off |
| `courses/:id/modules?include[]=items` | Usually works, not guaranteed |
| `courses/:id/pages/:page_url` | Works even where the index 404s |
| `files/:id` | Works even where the course file index 403s |

**Permission is per object, not per tab.** A hidden Files tab does not mean the files are unreachable — walk the modules, pages, announcements and syllabus body, collect the `/files/N` references out of the HTML, and resolve each one. In one course that surfaces 53 files whose index refuses outright.

**The syllabus body is a file source.** Instructors attach readings directly to it. It is not a page, so a modules-only walk misses them silently.

**A 403 is ambiguous.** It means "no longer enrolled" at least as often as "tab hidden", and nothing in the response distinguishes them. Add/drop churn drops courses out of `courses?enrollment_state=active` mid-term, after which even the course object 403s. Check whether the course still appears in your course list before concluding anything.

**Empty is often correct.** Canvas only returns published items with due dates. Early in a term, many syllabi simply are not posted.

## Contributing

Issues and pull requests welcome, especially endpoint behaviour from other Canvas schools — the table above is from one institution and one student's courses.

Never include a token, a course ID, or course material in an issue. `.gitignore` excludes `.env`, `*.token`, and every document extension, but it cannot catch a paste.

## License

MIT. See [LICENSE](LICENSE).

Built by [Hanif Ramadhan](https://github.com/patronofalltrades) during a Fall 2026 Haas exchange semester, mostly out of irritation at retyping the same due dates every week.

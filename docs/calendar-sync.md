# macOS companions

Everything in `macos/` is optional and macOS-only. The MCP server in `server/` reads Canvas; these scripts put deadlines onto your calendar, into Reminders, and readings onto your disk. Standard library Python only, except the text extractor.

They read the token from the Keychain under the service name `bcourses-token` by default — different from the TypeScript server's `bcourses-student-mcp`. Either store the token twice, or set one name for both:

```sh
export CANVAS_KEYCHAIN_SERVICE=bcourses-student-mcp
```

`CANVAS_TOKEN` overrides the Keychain entirely if you need it for a one-off.

## The scripts

| File | Purpose | Python |
| --- | --- | --- |
| `bcourses_api.py` | Canvas REST client. Stdlib only. | 3.9+ |
| `bcourses_cli.py` | JSON CLI over the same functions — one subcommand per tool | 3.9+ |
| `sync_calendar.py` | Reconciles deadlines into an Apple Calendar | 3.9+ |
| `sync_reminders.py` | Creates native Reminders with alerts that reach your phone | 3.9+ |
| `download_materials.py` | Downloads readings into per-class folders | 3.9+ |
| `bcourses_extract.py` | PDF/DOCX/PPTX/XLSX to text | 3.10+, needs a venv |
| `install_calendar_agent.sh` | Installs a weekly launchd agent | — |

`bcourses_extract.py` needs `pypdf`, `python-docx`, `python-pptx` and `openpyxl`. Keep it in a venv and out of the sync scripts: macOS system Python is 3.9.6 and cannot install them, and the scheduled jobs depend on running there.

```sh
uv venv --python 3.12 && .venv/bin/pip install pypdf python-docx python-pptx openpyxl
```

`bcourses_cli.py read` and `search` re-exec themselves under `.venv/bin/python` automatically.

## First run

```sh
cd macos
python3 bcourses_cli.py whoami            # check the token
python3 bcourses_cli.py courses           # your course IDs
python3 bcourses_cli.py upcoming --days 14
```

Then edit the `COURSES` map at the top of `download_materials.py` with your own IDs. It ships empty on purpose: an unmapped course is reported, never downloaded into a guessed folder name.

## Calendar sync

```sh
python3 sync_calendar.py --dry-run        # preview, writes nothing
python3 sync_calendar.py                  # reconcile the next 30 days
python3 sync_calendar.py --days 60
python3 sync_calendar.py --alarm 2880 --alarm 60
python3 sync_calendar.py --if-stale 12    # no-op if it ran recently
python3 sync_calendar.py --force          # purge and rebuild — manual repair only
```

It writes a local calendar you own, `bCourses Deadlines`, and reconciles rather than appends: new deadlines created, moved ones rewritten in place, cancelled ones deleted **within the sync window**. That window guard matters — an item due beyond `--days` is out of scope, not missing, so a narrow window never deletes what it cannot see.

Events are located by the calendar UID recorded in `~/.bcourses-sync/calendar.json`, falling back to a `[bcourses-id:…]` marker stamped into every description. If you delete an event by hand, state still holds its UID, so the sync reports "already in sync" while nothing is on your calendar. `--force` is the fix.

**Do not schedule `--force`.** A rebuild recreates every event, and an alarm whose trigger time has already passed can fire the moment its event is created. The scheduled job runs the incremental reconcile; `--force` stays manual.

By default the sync drops two kinds of noise: `calendar_event` items, which are recurring class meetings the subscribed Canvas `.ics` feed already covers, and items whose due date has passed. `--include-events` and `--include-past` restore them.

## Scheduling

```sh
./install_calendar_agent.sh          # Sundays at 08:00
./install_calendar_agent.sh 9 30     # 09:30 instead
./install_calendar_agent.sh --remove
```

`StartCalendarInterval` fires on next wake if the Mac was asleep, so a closed laptop delays the sync rather than skipping the week.

## Gotchas

**Automation permission is per-context.** A foreground run prompts once and works. A launchd-triggered run can be blocked separately; `osascript` error `-1743` means System Settings → Privacy & Security → Automation, enable Reminders or Calendar for Python.

**AppleScript string literals cannot contain raw newlines** — they must be `\n` escapes.

**Month-end rollover.** Set `day of d to 1` before assigning year and month, or setting the month while the current day is the 31st silently rolls the date forward.

**Scanned PDFs come back empty.** There is no OCR here; the file has no text layer.

**pypdf is noisy.** Course PDFs trip `Ignoring wrong pointing object` constantly and still extract fine. Its logger is pinned to ERROR — worth keeping, since anything on stdout would corrupt the MCP stdio protocol.

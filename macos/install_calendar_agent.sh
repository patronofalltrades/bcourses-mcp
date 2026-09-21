#!/bin/bash
# Install (or reinstall) the weekly bCourses -> Apple Calendar sync.
#
# Runs every Sunday at 08:00 local time. If the Mac is asleep or off at that
# moment launchd fires the job on the next wake, so a closed laptop only delays
# the sync, it does not skip the week.
#
#   ./install_calendar_agent.sh          # install for Sunday 08:00
#   ./install_calendar_agent.sh 9 30     # install for Sunday 09:30
#   ./install_calendar_agent.sh --remove
set -euo pipefail

LABEL="com.bcourses.calendar"
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"
TARGET="gui/$(id -u)/$LABEL"

if [ "${1:-}" = "--remove" ]; then
    launchctl bootout "$TARGET" 2>/dev/null || launchctl unload "$PLIST" 2>/dev/null || true
    rm -f "$PLIST"
    echo "Removed $LABEL."
    exit 0
fi

HOUR="${1:-8}"
MINUTE="${2:-0}"

mkdir -p "$HOME/Library/LaunchAgents" "$HOME/.bcourses-sync"

# /usr/bin/python3 (system 3.9) on purpose: sync_calendar.py has no third-party
# dependencies, and system Python is a steadier target for a background job
# than a venv that might get rebuilt.
cat > "$PLIST" <<PLIST_EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>$LABEL</string>
    <key>ProgramArguments</key>
    <array>
        <string>/usr/bin/python3</string>
        <string>$HOME/bcourses-claude/sync_calendar.py</string>
        <string>--days</string>
        <string>30</string>
    </array>
    <key>WorkingDirectory</key>
    <string>$HOME/bcourses-claude</string>
    <key>StartCalendarInterval</key>
    <dict>
        <key>Weekday</key>
        <integer>0</integer>
        <key>Hour</key>
        <integer>$HOUR</integer>
        <key>Minute</key>
        <integer>$MINUTE</integer>
    </dict>
    <key>StandardOutPath</key>
    <string>$HOME/.bcourses-sync/calendar-sync.log</string>
    <key>StandardErrorPath</key>
    <string>$HOME/.bcourses-sync/calendar-sync.log</string>
    <key>ProcessType</key>
    <string>Background</string>
</dict>
</plist>
PLIST_EOF

plutil -lint "$PLIST" > /dev/null

launchctl bootout "$TARGET" 2>/dev/null || true
launchctl bootstrap "gui/$(id -u)" "$PLIST"
launchctl enable "$TARGET"

printf 'Installed %s - every Sunday at %02d:%02d.\n' "$LABEL" "$HOUR" "$MINUTE"
echo "  run now:  launchctl kickstart -k $TARGET"
echo "  log:      ~/.bcourses-sync/calendar-sync.log"

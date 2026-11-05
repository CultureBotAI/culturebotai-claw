#!/usr/bin/env python3
"""Mutation check for scripts/cron_status.py: each rule's test goes red when the rule is reverted.

Purpose: AGENTS.md requires confirming that a test for a distinction fails
when the distinction is removed. Each mutant is one exact replacement in
scripts/cron_status.py, asserted to match once. tests/test_cron_status.py runs
in a fresh Python process per mutant, and the original bytes are then restored
from a backup, never from git.
Inputs: none; run from the claw checkout root.
Outputs: one line per mutant, killed or SURVIVED; a nonzero exit if any
survives.
Serves: the cron-status skill, PR #820 and its review issues #821-#834 and #836-#838. Written 2026-11-05.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

SOURCE = Path("scripts/cron_status.py")
MUTANTS = [
    ("lateness flagged at 2 h", "LATE = GRACE\n", "LATE = dt.timedelta(hours=2)\n"),
    ("disabled workflow not flagged", '    if status.state != "active":\n', "    if False:\n"),
    ("DOM/DOW combined with AND", "            return in_days or in_weekdays", "            return in_days and in_weekdays"),
    ("repository failure swallowed",
     "            failures[repository] = (str(exc).strip() or type(exc).__name__).splitlines()[0][:200]\n",
     "            pass\n"),
    ("start/step stops at its start", "            end = high if has_step else start", "            end = start"),
    ("silent workflow not flagged", "    if status.expected_due and total == 0:\n", "    if False:\n"),
    # Review of PR #820 (#821-#827).
    ("star-prefixed weekday treated as restricted", 'not fields[4].startswith("*"))', 'fields[4] != "*")'),
    ("next tick not reported", "    status.next_tick = min(upcoming).isoformat() if upcoming else None\n",
     "    status.next_tick = None\n"),
    ("any launchctl failure read as not loaded",
     '            if "could not find service" in (listed.stderr or "").lower():\n', "            if True:\n"),
    ("explicit /1 step collapses", "            end = high if has_step else start", "            end = high if step != 1 else start"),
    ("skipped days summarised as daily", "        daily = (self.days == frozenset(range(1, 32))",
     "        daily = (not self.days_restricted"),
    ("400-day tick horizon", "HORIZON_DAYS = 366 * 9\n", "HORIZON_DAYS = 400\n"),
    ("search cap ignored", "    if total(window) <= RUN_SEARCH_CAP:\n", "    if True:\n"),
    ("schedule timezone ignored", "        if timezones:\n", "        if False:\n"),
    ("crontab assignments listed as jobs", " or ASSIGNMENT.match(stripped):", ":"),
    ("crontab shortcut split as five fields", '            if stripped.startswith("@"):', "            if False:"),
    ("unassessed workflow not named", "        if status.error:\n            lines.append(f\"INCOMPLETE:",
     "        if False:\n            lines.append(f\"INCOMPLETE:"),
    ("missing crontab binary raises", "    except OSError as exc:  # no crontab binary", "    except ValueError as exc:  # no crontab binary"),
    ("launchd interval read as minutes", '            parts.append(f"every {seconds} s")\n',
     '            parts.append(f"every {_duration(seconds // 60)}")\n'),
    ("re-run attempt hidden", '        if (latest.get("run_attempt") or 1) > 1:\n', "        if False:\n"),
    # Second review of PR #820 (#828-#830).
    ("count query paginated", 'int(gh(["api", f"{base}&created={quote(created)}", "--jq", ".total_count"])',
     'int(gh(["api", "--paginate", f"{base}&created={quote(created)}", "--jq", ".total_count"])'),
    ("today omitted from per-day queries", "    while day <= today:\n", "    while day < today:\n"),
    ("per-day runs deduplicated by timestamp", '            runs[run.get("id", run["created_at"])] = run\n',
     '            runs[run["created_at"]] = run\n'),
    ("missing launchctl raises", '        except OSError as exc:\n            errors.append(f"launchctl: {exc}")',
     '        except ValueError as exc:\n            errors.append(f"launchctl: {exc}")'),
    ("shortcut split on a space only", "                parts = stripped.split(None, 1)", '                parts = stripped.split(" ", 1)'),
    ("bare shortcut accepted", "                if len(parts) < 2:\n", "                if False:\n"),
    ("interval seconds dropped", "        elif seconds % 60:", "        elif False:"),
    # Third review of PR #820 (#831, #832).
    ("pipe in a cell not escaped", '.replace("|", "\\\\|")', ""),
    ("long-duration minutes dropped", 'return f"{days} d {hours} h {rest} min" if rest else f"{days} d {hours} h"',
     'return f"{days} d {hours} h"'),
    ("grace period removed from due", "if tick <= now - GRACE)", "if tick <= now)"),
    ("runs counted by start day", '        created = _parse_time(run["created_at"])\n        if created.date() in by_day:',
     '        created = _parse_time(run.get("run_started_at") or run["created_at"])\n        if created.date() in by_day:'),
    ("schedule-event filter dropped", "runs?event=schedule&per_page=100", "runs?per_page=100"),
    ("older failures ignored", "            status.non_success += 1\n", "            pass\n"),
    ("local command hidden", "_row(job.source, Code(job.job),", '_row(job.source, "",'),
    # Fourth review of PR #820 (#833).
    ("local command not a code span", "_row(job.source, Code(job.job),", "_row(job.source, job.job,"),
    ("code fence not longer than inner backticks", "default=0) + 1)", "default=0) * 0 + 1)"),
    ("multiline joined without a space", 'text = " ".join(LINE_ENDING.split(str(value)))',
     'text = "".join(LINE_ENDING.split(str(value)))'),
    ("not-assessed marker unbolded", 'f"**not assessed: {status.error}**"', 'f"not assessed: {status.error}"'),
    # Fifth review of PR #820 (#834).
    ("malformed trigger escapes the per-plist handler",
     "        except Exception as exc:\n", "        except (OSError, plistlib.InvalidFileException) as exc:\n"),
    ("non-dictionary plist not rejected", '                raise ValueError("top level is not a dictionary")\n', "                pass\n"),
    # Sixth review of PR #820 (#836).
    ("truncated XML plist escapes the per-plist handler",
     "        except Exception as exc:\n", "        except (OSError, ValueError, LookupError, RecursionError) as exc:\n"),
    ("unreadable directory read as empty",
     '                plists = sorted(path for path in agents_dir.iterdir() if path.name.endswith(".plist"))',
     '                plists = sorted(agents_dir.glob("*.plist"))'),
    ("missing label invented from the file name",
     "            if schedule and (not isinstance(label, str) or not label.strip()):",
     "            if False:"),
    ("whitespace label accepted", "not isinstance(label, str) or not label.strip()):",
     "not isinstance(label, str) or not label):"),
    ("zero interval accepted", "        if not _is_integer(seconds) or seconds <= 0:",
     "        if not _is_integer(seconds) or seconds < 0:"),
    ("boolean read as an integer", "    return isinstance(value, int) and not isinstance(value, bool)",
     "    return isinstance(value, int)"),
    ("non-dictionary calendar entry not named",
     '                raise ValueError(f"StartCalendarInterval entry is not a dictionary: {entry!r}")',
     "                pass"),
    ("unknown calendar key accepted", "                if key not in CALENDAR_KEYS:", "                if False:"),
    ("calendar range unchecked", "                if not _is_integer(value) or not low <= value <= high:",
     "                if not _is_integer(value):"),
    ("Weekday 7 rejected", '"Weekday": (0, 7)', '"Weekday": (0, 6)'),
    # Seventh review of PR #820 (#837).
    ("unknown encoding escapes the per-plist handler", "        except Exception as exc:\n",
     '        except (OSError, ValueError, RecursionError, __import__("xml.parsers.expat").parsers.expat.ExpatError)'
     " as exc:\n"),
    ("deep nesting escapes the per-plist handler", "        except Exception as exc:\n",
     '        except (OSError, ValueError, LookupError, __import__("xml.parsers.expat").parsers.expat.ExpatError)'
     " as exc:\n"),
    ("empty exception message left blank", "{str(exc) or type(exc).__name__}", "{exc}"),
    ("is_dir outside the directory handler",
     "    if agents_dir is not None:\n        try:\n",
     "    if agents_dir is not None:\n        agents_dir.is_dir()\n        try:\n"),
    # Eighth review of PR #820 (#838).
    ("scheduler output decoded strictly", 'errors="backslashreplace"', 'errors="strict"'),
    ("main bypasses run_local", "collect_local(run_local, args.launch_agents_dir)",
     "collect_local(lambda command: subprocess.run(command, text=True, capture_output=True, check=False), "
     "args.launch_agents_dir)"),
    ("non-mapping workflow file read as unscheduled",
     "            if not isinstance(document, dict):  # a list", "            if False:  # a list"),
    ("crontab split on Unicode separators", 'crontab.stdout.split("\\n"):', "crontab.stdout.splitlines():"),
    ("gh lines split on Unicode separators", 'text.split("\\n") if line.strip()]', "text.splitlines() if line.strip()]"),
    ("cells split on Unicode separators", "LINE_ENDING.split(str(value))", "str(value).splitlines()"),
    ("carriage return not a cell line ending", 'LINE_ENDING = re.compile(r"\\r\\n|\\r|\\n")',
     'LINE_ENDING = re.compile(r"\\n")'),
    ("empty repository failure message indexes nothing",
     "(str(exc).strip() or type(exc).__name__).splitlines()[0]", "str(exc).splitlines()[0]"),
]

original = SOURCE.read_bytes()
survivors = 0
try:
    for name, old, new in MUTANTS:
        text = original.decode("utf-8")
        if text.count(old) != 1:
            print(f"ERROR     {name}: matched {text.count(old)} times")
            survivors += 1
            continue
        SOURCE.write_text(text.replace(old, new), encoding="utf-8")
        completed = subprocess.run([sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider",
                                    "tests/test_cron_status.py"], capture_output=True, text=True)
        killed = completed.returncode != 0
        print(f"{'killed   ' if killed else 'SURVIVED '} {name}")
        survivors += not killed
finally:
    SOURCE.write_bytes(original)
print(f"{len(MUTANTS) - survivors} of {len(MUTANTS)} mutants killed")
sys.exit(1 if survivors else 0)

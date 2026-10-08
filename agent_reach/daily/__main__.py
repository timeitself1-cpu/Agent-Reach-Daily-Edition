"""Agent Reach Daily command line (background refresh, status, export, scheduler).

    python -m agent_reach.daily --refresh-if-due      # scheduler / GUI launch: quick exit unless due
    python -m agent_reach.daily --refresh-now         # manual refresh (skips due check and backoff)
    python -m agent_reach.daily --status              # JSON status, no network
    python -m agent_reach.daily --check               # Ollama + model prerequisites
    python -m agent_reach.daily --export-html out.html [--date 2026-10-01]
    python -m agent_reach.daily --export-sample sample.json [--stories 1,2,3]   # public sample for a website
    python -m agent_reach.daily --publish [--date 2026-10-01]     # publish to the website (one-time setup in the window)
    python -m agent_reach.daily --publish-to-folder SITE        # the same files into a local copy of the website
    python -m agent_reach.daily --withdraw 2026-10-01 | --publish-status
    python -m agent_reach.daily --install-task | --uninstall-task [--dry-run] | --task-status
    python -m agent_reach.daily --gui                 # open the desktop window

Exit codes: 0 published / ok, 2 usage or setup error, 10 not due, 11 another refresh running,
12 waiting for failure backoff, 20 ran but nothing publishable (previous edition kept),
30 failed (previous edition kept), 31 Ollama/model unavailable (nothing fetched),
1 a --check found missing prerequisites, or --podcast could not record.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from pathlib import Path

from agent_reach.daily import __version__
from agent_reach.daily.paths import PROJECT_ROOT, DataPaths

EXIT_USAGE = 2


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(prog="agent_reach.daily", description="Agent Reach Daily: local daily news edition")
    mode = p.add_mutually_exclusive_group()
    mode.add_argument("--refresh-if-due", action="store_true", help="refresh only if the daily refresh is due")
    mode.add_argument("--refresh-now", action="store_true", help="refresh now (manual)")
    mode.add_argument("--status", action="store_true", help="print status JSON (no network)")
    mode.add_argument("--check", action="store_true", help="check Ollama and the configured models")
    mode.add_argument("--export-html", type=Path, metavar="PATH", help="export an edition as standalone HTML")
    mode.add_argument("--export-sample", type=Path, metavar="PATH",
                      help="export a public sample of an edition as JSON (no publisher excerpts)")
    mode.add_argument("--publish", action="store_true", help="publish an edition (latest, or --date) to the website")
    mode.add_argument("--publish-to-folder", type=Path, metavar="SITE",
                      help="write the website files of an edition into a local copy of the website (preview)")
    mode.add_argument("--withdraw", type=date.fromisoformat, metavar="DATE", help="take a date off the website")
    mode.add_argument("--publish-status", action="store_true", help="print the website publishing status")
    mode.add_argument("--install-task", action="store_true", help="install/update the current-user scheduled task")
    mode.add_argument("--uninstall-task", action="store_true", help="remove the scheduled task (cached news is kept)")
    mode.add_argument("--task-status", action="store_true", help="show the scheduled task status")
    mode.add_argument("--init", action="store_true", help="create the data folder and default settings")
    mode.add_argument("--reset-cache", action="store_true", help="delete all cached editions (requires --yes)")
    mode.add_argument("--podcast", action="store_true", help="record the podcast of an edition (latest, or --date)")
    mode.add_argument("--gui", action="store_true", help="open the desktop window")
    p.add_argument("--trigger", default=None, choices=["scheduled", "gui_launch", "manual", "cli"])
    p.add_argument("--allow-extractive", action="store_true",
                   help="publish with extractive summaries if the local model is unavailable")
    p.add_argument("--date", type=date.fromisoformat,
                   help="edition date for --export-html / --export-sample / --podcast / --publish (default: latest)")
    p.add_argument("--stories", type=lambda v: [int(x) for x in v.split(",") if x.strip()], metavar="RANKS",
                   help="story numbers for --export-sample, e.g. 1,2,3,4,9 (default: the first 5 Top Stories)")
    p.add_argument("--data-dir", type=Path, help="data folder (default %%LOCALAPPDATA%%\\AgentReachDaily)")
    p.add_argument("--yes", action="store_true", help="confirm destructive actions")
    p.add_argument("--dry-run", action="store_true",
                   help="with --install-task/--uninstall-task: show what would be done, change nothing")
    p.add_argument("--version", action="version", version=f"Agent Reach Daily {__version__}")
    p.add_argument("--log-level", default="INFO", choices=["DEBUG", "INFO", "WARNING", "ERROR"])
    return p.parse_args(argv)


def _refresh_command(args: argparse.Namespace, paths: DataPaths) -> int:
    import logging

    from agent_reach.daily.logs import move_logging, setup_logging
    from agent_reach.daily.refresh import refresh

    paths.ensure()
    trigger = args.trigger or ("scheduled" if args.refresh_if_due else "cli")
    setup_logging(paths, "scheduler" if args.refresh_if_due else "refresh", args.log_level)
    if args.refresh_if_due:
        # quick due check happens inside refresh(); switch to refresh.log once real work may start
        from agent_reach.daily.prefs import load_prefs
        from agent_reach.daily.state import check_due, load_state
        from agent_reach.daily.timeutil import utcnow

        prefs, _ = load_prefs(paths)
        state, _ = load_state(paths)
        if check_due(state, prefs, utcnow()).due or state.last_attempt_outcome == "running":
            move_logging(paths, "scheduler", "refresh", args.log_level)
    result = refresh(paths, trigger=trigger, force=args.refresh_now, allow_extractive=args.allow_extractive)
    logging.getLogger("agent_reach.daily").info("exit %d %s: %s", result.code, result.outcome, result.message)
    print(f"{result.outcome}: {result.message}")
    return result.code


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    paths = DataPaths.resolve(args.data_dir)

    if args.gui:
        from agent_reach.daily.gui import run_gui

        return run_gui(paths)

    if args.refresh_if_due or args.refresh_now:
        try:
            return _refresh_command(args, paths)
        except Exception:  # noqa: BLE001 - under pythonw.exe there is no console: the log is the only witness
            import logging

            logging.getLogger("agent_reach.daily").exception("refresh command crashed")
            return 30

    if args.status:
        from agent_reach.daily.refresh import dumps, status_payload

        print(dumps(status_payload(paths)))
        return 0

    if args.check:
        from agent_reach.daily.prefs import load_prefs
        from agent_reach.daily.prereqs import check_prefs

        prefs, warn = load_prefs(paths)
        status = check_prefs(prefs)
        print(json.dumps({"ready": status.ready, "reachable": status.reachable, "version": status.version,
                          "missing_models": status.missing, "grouping_model_missing": status.grouping_missing,
                          "grouping_fallback": status.grouping_fallback, "message": status.describe(),
                          "settings_warning": warn, "python": sys.version.split()[0]}, indent=2))
        return 0 if status.ready else 1

    if args.export_html:
        from agent_reach.daily.render_html import render_edition_html
        from agent_reach.daily.store import EditionStore

        store = EditionStore(paths)
        edition = store.load_date(args.date)[0] if args.date else store.load_latest().edition
        if edition is None:
            print("No cached edition found for that date." if args.date else "No cached edition yet.", file=sys.stderr)
            return EXIT_USAGE
        args.export_html.parent.mkdir(parents=True, exist_ok=True)
        args.export_html.write_text(render_edition_html(edition), encoding="utf-8")
        print(f"Exported {edition.edition_date.isoformat()} to {args.export_html}")
        return 0

    if args.export_sample:
        from agent_reach.daily.sample import SampleError, edition_sample
        from agent_reach.daily.store import EditionStore

        store = EditionStore(paths)
        edition = store.load_date(args.date)[0] if args.date else store.load_latest().edition
        if edition is None:
            print("No cached edition found for that date." if args.date else "No cached edition yet.", file=sys.stderr)
            return EXIT_USAGE
        try:
            sample = edition_sample(edition, args.stories)
        except SampleError as exc:
            print(str(exc), file=sys.stderr)
            return EXIT_USAGE
        args.export_sample.parent.mkdir(parents=True, exist_ok=True)
        args.export_sample.write_text(json.dumps(sample, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        print(f"Exported {len(sample['stories'])} stories of {edition.edition_date.isoformat()} to {args.export_sample}")
        return 0

    if args.publish or args.publish_to_folder or args.withdraw or args.publish_status:
        from agent_reach.daily import publish
        from agent_reach.daily.store import EditionStore

        if args.publish_status:
            print(json.dumps(publish.status_lines(paths), indent=2, ensure_ascii=False))
            return 0
        target = publish.FolderTarget(args.publish_to_folder) if args.publish_to_folder else None
        if args.withdraw:
            result = publish.withdraw(paths, args.withdraw.isoformat(), target)
        else:
            store = EditionStore(paths)
            edition = store.load_date(args.date)[0] if args.date else store.load_latest().edition
            if edition is None:
                print("No cached edition found for that date." if args.date else "No cached edition yet.",
                      file=sys.stderr)
                return EXIT_USAGE
            result = publish.publish_edition(paths, edition, target)
        print(result.message)
        return 0 if result.ok else 1

    if args.podcast:
        from agent_reach.daily.podcast import make_podcast
        from agent_reach.daily.prefs import load_prefs
        from agent_reach.daily.store import EditionStore

        paths.ensure()
        store = EditionStore(paths)
        edition = store.load_date(args.date)[0] if args.date else store.load_latest().edition
        if edition is None:
            print("No cached edition found for that date." if args.date else "No cached edition yet.", file=sys.stderr)
            return EXIT_USAGE
        result = make_podcast(paths, edition, load_prefs(paths)[0])
        print(result.message + (f" {result.audio}" if result.audio else ""))
        return 0 if result.ok else 1

    if args.install_task or args.uninstall_task or args.task_status:
        from agent_reach.daily import scheduler

        if args.task_status:
            st = scheduler.task_status()
            print(json.dumps(st.__dict__, indent=2))
            return 0
        if args.uninstall_task:
            ok, msg = scheduler.uninstall_task(dry_run=args.dry_run)
        else:
            data_dir = args.data_dir.resolve() if args.data_dir else None
            ok, msg = scheduler.install_task(sys.executable, PROJECT_ROOT, data_dir=data_dir, dry_run=args.dry_run)
        print(msg)
        return 0 if ok else EXIT_USAGE

    if args.init:
        from agent_reach.daily.prefs import load_prefs, save_prefs

        paths.ensure()
        if not paths.settings.exists():
            prefs, _ = load_prefs(paths)
            save_prefs(paths, prefs)
        print(f"Data folder ready: {paths.root}")
        return 0

    if args.reset_cache:
        if not args.yes:
            print("Refusing to delete cached editions without --yes.", file=sys.stderr)
            return EXIT_USAGE
        from agent_reach.daily.lock import LockBusy, RefreshLock
        from agent_reach.daily.store import EditionStore

        lock = RefreshLock(paths.lock_file, None)
        try:
            lock.acquire()
        except LockBusy:
            print("A refresh is running; try again when it finishes.", file=sys.stderr)
            return 11
        try:
            n = EditionStore(paths).reset()
        finally:
            lock.release()
        print(f"Deleted {n} cached edition(s). Settings and history were kept.")
        return 0

    from agent_reach.daily.gui import run_gui

    return run_gui(paths)


if __name__ == "__main__":
    sys.exit(main())

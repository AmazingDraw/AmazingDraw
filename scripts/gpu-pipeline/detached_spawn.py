#!/usr/bin/env python3
"""Spawn a process fully detached from the current session.

Use this instead of shell `& disown` / `nohup` when the parent runtime may restart.
It creates a new session/process-group, detaches stdio, optionally writes pid/log,
and exits immediately after successful spawn.
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Spawn a detached background process")
    parser.add_argument("--cwd", default="/", help="Working directory for child process")
    parser.add_argument("--log", required=True, help="Combined stdout/stderr log file")
    parser.add_argument("--pid-file", default="", help="Optional pid file to write")
    parser.add_argument("--env", action="append", default=[], help="Extra env KEY=VALUE")
    parser.add_argument("cmd", nargs=argparse.REMAINDER, help="Command to run after --")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    cmd = args.cmd
    if cmd and cmd[0] == "--":
        cmd = cmd[1:]
    if not cmd:
        print("❌ missing command after --", file=sys.stderr)
        return 1

    env = os.environ.copy()
    for item in args.env:
        if "=" not in item:
            print(f"❌ invalid --env value: {item}", file=sys.stderr)
            return 1
        key, value = item.split("=", 1)
        env[key] = value

    log_path = Path(args.log).expanduser()
    log_path.parent.mkdir(parents=True, exist_ok=True)
    cwd = str(Path(args.cwd).expanduser())

    with open(os.devnull, "rb") as devnull, open(log_path, "ab", buffering=0) as logf:
        proc = subprocess.Popen(
            cmd,
            cwd=cwd,
            env=env,
            stdin=devnull,
            stdout=logf,
            stderr=subprocess.STDOUT,
            start_new_session=True,
            close_fds=True,
        )

    if args.pid_file:
        pid_path = Path(args.pid_file).expanduser()
        pid_path.parent.mkdir(parents=True, exist_ok=True)
        pid_path.write_text(str(proc.pid), encoding="utf-8")

    print(proc.pid)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

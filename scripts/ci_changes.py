#!/usr/bin/env python3
"""Decide whether a change touches only ticket files, so CI and the image gate can run light checks."""
from __future__ import annotations

import argparse
from pathlib import Path
import re
import subprocess
import sys

TICKET_PREFIX = 'tickets/'
SHA_RE = re.compile(r'[0-9a-f]{40}(?:[0-9a-f]{24})?')  # SHA-1 or SHA-256 object names


def is_ticket_only(paths: list[str] | None) -> bool:
    """True only for a non-empty list in which every path starts with 'tickets/'."""
    return bool(paths) and all(isinstance(p, str) and p.startswith(TICKET_PREFIX) for p in paths)


def changed_paths(root: Path, base: str, head: str, *, merge_base: bool) -> list[str]:
    """Paths added, modified, renamed or deleted between base and head.

    `--no-renames` lists both sides of a move, so a rename out of tickets/ is never ticket-only.
    """
    span = f'{base}...{head}' if merge_base else None
    args = ['git', '-C', str(root), 'diff', '--no-renames', '--name-only', '-z']
    args += [span] if span else [base, head]
    result = subprocess.run(args, capture_output=True, check=True)
    return [p for p in result.stdout.decode('utf-8').split('\0') if p]


def _git_ok(root: Path, *args: str) -> bool:
    return subprocess.run(['git', '-C', str(root), *args], capture_output=True).returncode == 0


def decide(root: Path, event: str, base: str, head: str, forced: str = '') -> tuple[bool, str]:
    """(ticket_only, reason). Never raises: every error returns (False, reason)."""
    try:
        if event not in ('pull_request', 'push'):
            return False, f'event {event} always runs everything'
        if not (SHA_RE.fullmatch(base or '') and SHA_RE.fullmatch(head or '')):
            return False, 'no usable base or head commit'
        if event == 'push':
            if set(base) == {'0'}:
                return False, 'new branch or tag'
            if forced == 'true':
                return False, 'history was rewritten'
        for sha in (base, head):
            if not _git_ok(root, 'cat-file', '-e', f'{sha}^{{commit}}'):
                return False, 'commit not available'
        if event == 'push' and not _git_ok(root, 'merge-base', '--is-ancestor', base, head):
            return False, 'previous head is not an ancestor'
        paths = changed_paths(root, base, head, merge_base=event == 'pull_request')
    except (OSError, subprocess.SubprocessError, ValueError):
        return False, 'could not determine changed paths'
    if not paths:
        return False, 'no changed paths'
    if not is_ticket_only(paths):
        return False, f'{len(paths)} changed path(s), not all under tickets/'
    return True, f'{len(paths)} changed path(s), all under tickets/'


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--event', required=True)
    parser.add_argument('--base', default='')
    parser.add_argument('--head', default='')
    parser.add_argument('--forced', default='')
    parser.add_argument('--root', type=Path, default=Path.cwd())
    parser.add_argument('--github-output', type=Path)
    args = parser.parse_args(argv)
    only, reason = decide(args.root, args.event, args.base, args.head, args.forced)
    print(f'ticket_only={"true" if only else "false"}: {reason}')
    if args.github_output:
        try:
            with args.github_output.open('a', encoding='utf-8') as out:
                out.write(f'ticket_only={"true" if only else "false"}\n')
        except OSError as exc:
            print(f'could not write the output file: {exc}', file=sys.stderr)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())

"""Ticket-only change detection and the static shape of the CI workflow (ENG-120)."""
from __future__ import annotations

import contextlib
import io
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
import ci_changes  # noqa: E402

ZERO = '0' * 40


class TicketOnlyTest(unittest.TestCase):
    def test_ticket_only_paths_take_the_light_path(self):
        """AC-ENG-120-04: ticket-only lists are light."""
        self.assertTrue(ci_changes.is_ticket_only(['tickets/ENG-001.md']))
        self.assertTrue(ci_changes.is_ticket_only(['tickets/a.md', 'tickets/b.md']))

    def test_anything_else_takes_the_full_path(self):
        """AC-ENG-120-04: other paths, empty and unknown lists are full."""
        for paths in (['tickets/a.md', 'src/kurafolio/x.py'], ['docs/x.md'], ['tickets'],
                      ['ticketsx/a.md'], [], None):
            with self.subTest(paths=paths):
                self.assertFalse(ci_changes.is_ticket_only(paths))


class DecideTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.git('init', '-b', 'main')
        self.git('config', 'user.name', 'Synthetic')
        self.git('config', 'user.email', 'example@users.noreply.github.com')
        self.write('README.md', 'base\n')
        self.write('tickets/A.md', 'ticket\n')
        self.base = self.commit('base')

    def git(self, *args):
        return subprocess.check_output(['git', '-C', str(self.root), *args], text=True).strip()

    def write(self, name, text):
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)

    def commit(self, message):
        self.git('add', '-A')
        self.git('commit', '-m', message)
        return self.git('rev-parse', 'HEAD')

    def test_pull_request_that_edits_only_a_ticket(self):
        """AC-ENG-120-04."""
        self.write('tickets/A.md', 'changed\n')
        head = self.commit('ticket')
        only, reason = ci_changes.decide(self.root, 'pull_request', self.base, head)
        self.assertTrue(only, reason)

    def test_pull_request_that_also_edits_code(self):
        """AC-ENG-120-04."""
        self.write('tickets/A.md', 'changed\n')
        self.write('src/x.py', 'x = 1\n')
        head = self.commit('mixed')
        self.assertFalse(ci_changes.decide(self.root, 'pull_request', self.base, head)[0])

    def test_rename_out_of_tickets_is_not_ticket_only(self):
        """AC-ENG-120-04: both sides of a rename are listed."""
        self.git('mv', 'tickets/A.md', 'docs-A.md')
        head = self.commit('rename')
        self.assertEqual(sorted(ci_changes.changed_paths(self.root, self.base, head, merge_base=True)),
                         ['docs-A.md', 'tickets/A.md'])
        self.assertFalse(ci_changes.decide(self.root, 'pull_request', self.base, head)[0])

    def test_push_that_only_deletes_a_ticket(self):
        """AC-ENG-120-04."""
        self.git('rm', '-q', 'tickets/A.md')
        head = self.commit('delete')
        only, reason = ci_changes.decide(self.root, 'push', self.base, head)
        self.assertTrue(only, reason)

    def test_push_fail_safe_cases(self):
        """AC-ENG-120-04: every uncertain push runs everything."""
        self.write('tickets/A.md', 'changed\n')
        head = self.commit('ticket')
        self.assertEqual(ci_changes.decide(self.root, 'push', ZERO, head), (False, 'new branch or tag'))
        self.assertFalse(ci_changes.decide(self.root, 'push', 'a' * 40, head)[0])
        self.assertEqual(ci_changes.decide(self.root, 'push', self.base, head, 'true'),
                         (False, 'history was rewritten'))
        self.git('checkout', '-q', '-b', 'other', self.base)
        self.write('LICENSE', 'x\n')
        other = self.commit('other')
        self.assertFalse(ci_changes.decide(self.root, 'push', other, head)[0])

    def test_other_events_and_bad_input_run_everything(self):
        """AC-ENG-120-04."""
        self.write('tickets/A.md', 'changed\n')
        head = self.commit('ticket')
        self.assertFalse(ci_changes.decide(self.root, 'workflow_dispatch', self.base, head)[0])
        self.assertFalse(ci_changes.decide(self.root, 'pull_request', '', head)[0])
        self.assertFalse(ci_changes.decide(self.root, 'pull_request', 'not-a-sha', head)[0])

    def test_empty_diff(self):
        """AC-ENG-120-04."""
        self.assertEqual(ci_changes.decide(self.root, 'pull_request', self.base, self.base),
                         (False, 'no changed paths'))

    def test_directory_that_is_not_a_repository(self):
        """AC-ENG-120-04: no exception."""
        with tempfile.TemporaryDirectory() as elsewhere:
            only, reason = ci_changes.decide(Path(elsewhere), 'pull_request', 'a' * 40, 'b' * 40)
        self.assertFalse(only)
        self.assertTrue(reason)

    def test_main_writes_the_github_output(self):
        """AC-ENG-120-04: ticket_only=true then ticket_only=false, both exit 0."""
        self.write('tickets/A.md', 'changed\n')
        head = self.commit('ticket')
        out = Path(self.temp.name) / 'github-output'
        with contextlib.redirect_stdout(io.StringIO()):
            code = ci_changes.main(['--event', 'pull_request', '--base', self.base, '--head', head,
                                    '--root', str(self.root), '--github-output', str(out)])
            self.assertEqual(code, 0)
            self.assertEqual(out.read_text(), 'ticket_only=true\n')
            with tempfile.TemporaryDirectory() as elsewhere:
                code = ci_changes.main(['--event', 'pull_request', '--base', self.base, '--head', head,
                                        '--root', elsewhere, '--github-output', str(out)])
        self.assertEqual(code, 0)
        self.assertEqual(out.read_text(), 'ticket_only=true\nticket_only=false\n')


def workflow_jobs() -> dict[str, list[str]]:
    jobs: dict[str, list[str]] = {}
    name = None
    in_jobs = False
    for line in (ROOT / '.github/workflows/ci.yml').read_text().splitlines():
        if line == 'jobs:':
            in_jobs = True
        elif in_jobs:
            match = re.fullmatch(r'  ([a-z0-9-]+):', line)
            if match:
                name = match.group(1)
                jobs[name] = []
            elif name:
                jobs[name].append(line)
    return jobs


def steps_of(lines: list[str]) -> list[list[str]]:
    steps: list[list[str]] = []
    for line in lines:
        if line.startswith('      - '):
            steps.append([line])
        elif steps and line.startswith('        '):
            steps[-1].append(line)
    return steps


class WorkflowTest(unittest.TestCase):
    GATED = ('docker-foundation', 'browser-workflow', 'parser-sdk-packages', 'postgres-foundation',
             'postgres-ingestion', 'postgres-identity', 'postgres-sources')
    NOT_LIGHT = "needs.changes.outputs.ticket_only != 'true'"

    def test_jobs_have_the_expected_conditions(self):
        """AC-ENG-120-05."""
        jobs = workflow_jobs()
        changes = '\n'.join(jobs['changes'])
        self.assertIn('fetch-depth: 0', changes)
        self.assertIn('ticket_only: ${{ steps.detect.outputs.ticket_only }}', changes)
        for name in self.GATED:
            with self.subTest(job=name):
                body = '\n'.join(jobs[name])
                self.assertIn('    needs: changes', jobs[name])
                self.assertIn("    if: ${{ !cancelled() && needs.changes.outputs.ticket_only != 'true' }}", jobs[name])
                self.assertNotIn('ticket_only == ', body)
        self.assertIn('    needs: changes', jobs['python-312-linux'])
        self.assertIn('    if: ${{ !cancelled() }}', jobs['python-312-linux'])

    def test_light_path_steps_of_the_main_job(self):
        """AC-ENG-120-05: guards never carry a condition; heavy steps skip on the light path."""
        steps = steps_of(workflow_jobs()['python-312-linux'])
        guards = ('check_language.py', 'check_publication.py --worktree', 'check_publication.py --staged',
                  'tickets.py check')
        for guard in guards:
            matching = [s for s in steps if any(guard in line and 'run:' in line for line in s)]
            with self.subTest(guard=guard):
                self.assertEqual(len(matching), 1)
                self.assertFalse(any(line.strip().startswith('if:') for line in matching[0]))
        heavy = [s for s in steps if any(('unittest discover -s tests -v' in line) or 'examples/demo.py' in line
                                         for line in s)]
        self.assertEqual(len(heavy), 5)
        for step in heavy:
            self.assertIn('        if: ' + self.NOT_LIGHT, step)
        tickets_tests = [s for s in steps if any("-p 'test_tickets.py'" in line for line in s)]
        self.assertEqual(len(tickets_tests), 1)
        self.assertIn("        if: needs.changes.outputs.ticket_only == 'true'", tickets_tests[0])
        last = steps[-1]
        self.assertTrue(any('tickets.py pr-check --branch "$HEAD_REF"' in line for line in last))
        self.assertTrue(any('github.event_name == '"'pull_request'" in line for line in last))

    def test_event_values_reach_the_shell_only_through_env(self):
        """AC-ENG-120-05: no expression inside a run script; head_ref only on an env line."""
        text = (ROOT / '.github/workflows/ci.yml').read_text()
        self.assertEqual(text.count('github.head_ref'), 1)
        self.assertRegex(text, r'HEAD_REF: \$\{\{ github\.head_ref \}\}')
        in_run = False
        indent = 0
        for line in text.splitlines():
            stripped = line.lstrip()
            current = len(line) - len(stripped)
            if in_run and stripped and current <= indent:
                in_run = False
            if in_run:
                self.assertNotIn('${{', line)
            if re.match(r'(- )?run: [|>]', stripped):
                in_run, indent = True, current
            elif re.match(r'(- )?run: ', stripped):
                self.assertNotIn('${{', line)


if __name__ == '__main__':
    unittest.main()

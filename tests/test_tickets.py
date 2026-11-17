"""Ticket backlog validation and the parallel-agent claim protocol."""
from __future__ import annotations

import contextlib
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
import tickets  # noqa: E402

TEMPLATE = """---
id: {id}
title: Synthetic ticket {id}
priority: P1
status: {status}
type: chore
parent:
depends_on: [{deps}]
resources: [{res}]
risk: low
size: S
agent_tier: {tier}
gate: none
gate_approval:
review: self
branch:
pr:
spec:
updated: 2026-11-05
---

# {id}

## Goal

Synthetic.

## Acceptance criteria

- [ ] Works.

## Plan

- [ ] Do it.

## Handoff

- State: none.

## Log

- 2026-11-05 test: created.
"""


def run(cwd: Path, *argv: str) -> tuple[int, str, str]:
    out, err = io.StringIO(), io.StringIO()
    old = Path.cwd()
    os.chdir(cwd)
    try:
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = tickets.main(list(argv))
    finally:
        os.chdir(old)
    return code, out.getvalue(), err.getvalue()


class RepositoryTicketsTest(unittest.TestCase):
    def test_repository_tickets_are_valid(self):
        loaded = tickets.load_tickets(ROOT)
        self.assertGreater(len(loaded), 0)
        self.assertEqual(tickets.validate(loaded), [])


class ClaimProtocolTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.repo = Path(self.tmp.name) / 'repo'
        (self.repo / 'tickets').mkdir(parents=True)
        self.write('ENG-001', res='shared-res')
        self.write('ENG-002', res='shared-res')
        self.write('ENG-003', deps='ENG-001')
        self.write('ENG-004', tier='frontier')
        (self.repo / '.gitignore').write_text('work/\n', encoding='utf-8')
        env = {**os.environ, 'GIT_AUTHOR_NAME': 't', 'GIT_AUTHOR_EMAIL': 't@example.invalid',
               'GIT_COMMITTER_NAME': 't', 'GIT_COMMITTER_EMAIL': 't@example.invalid'}
        for cmd in (['init', '-q', '-b', 'main'], ['add', '.'], ['commit', '-q', '-m', 'init']):
            subprocess.run(['git', '-C', str(self.repo), *cmd], check=True, env=env, capture_output=True)

    def tearDown(self):
        self.tmp.cleanup()

    def write(self, tid, status='ready', deps='', res='', tier='any'):
        (self.repo / 'tickets' / f'{tid}.md').write_text(
            TEMPLATE.format(id=tid, status=status, deps=deps, res=res, tier=tier), encoding='utf-8')

    def claim(self, tid, agent='codex/test', *extra):
        return run(self.repo, 'claim', tid, '--agent', agent, *extra)

    def test_second_claim_on_same_ticket_is_refused(self):
        self.assertEqual(self.claim('ENG-001')[0], 0)
        code, _, err = self.claim('ENG-001', 'claude/test')
        self.assertEqual(code, 2)
        self.assertIn('already claimed by codex/test', err)

    def test_shared_resource_blocks_parallel_ticket_and_is_released(self):
        self.assertEqual(self.claim('ENG-001')[0], 0)
        code, _, err = self.claim('ENG-002', 'opencode/test')
        self.assertEqual(code, 2)
        self.assertIn('resource shared-res held by ENG-001', err)
        self.assertEqual(run(self.repo, 'release', 'ENG-001')[0], 0)
        self.assertEqual(self.claim('ENG-002', 'opencode/test')[0], 0)

    def test_unfinished_dependency_and_tier_filter(self):
        code, _, err = self.claim('ENG-003')
        self.assertEqual(code, 2)
        self.assertIn('waiting on ENG-001', err)
        _, out, _ = run(self.repo, 'next', '--tier', 'any')
        self.assertIn('ENG-001', out)
        self.assertNotIn('ENG-004', out)

    def test_heartbeat_requires_the_owning_worktree_token(self):
        self.assertEqual(self.claim('ENG-001')[0], 0)
        self.assertEqual(run(self.repo, 'heartbeat', 'ENG-001')[0], 0)
        (self.repo / 'work' / 'agent-claim.json').unlink()
        code, _, err = run(self.repo, 'heartbeat', 'ENG-001')
        self.assertEqual(code, 2)
        self.assertIn('does not own the claim', err)

    def test_takeover_needs_stale_claim_and_records_previous_owner(self):
        self.assertEqual(self.claim('ENG-001')[0], 0)
        code, _, err = run(self.repo, 'takeover', 'ENG-001', '--agent', 'claude/test')
        self.assertEqual(code, 2)
        self.assertIn('is live', err)
        with mock.patch.object(tickets, 'STALE_MINUTES', -1):
            code, out, _ = run(self.repo, 'takeover', 'ENG-001', '--agent', 'claude/test', '--reason', 'usage limit')
        self.assertEqual(code, 0, out)
        claim = tickets.read_claim(tickets.lock_dir(self.repo), 'ENG-001')
        self.assertEqual(claim['agent'], 'claude/test')
        self.assertEqual(claim['previous_owners'][0]['agent'], 'codex/test')
        self.assertEqual(claim['previous_owners'][0]['reason'], 'usage limit')
        self.assertEqual(run(self.repo, 'heartbeat', 'ENG-001')[0], 0)

    def test_claim_with_worktree_creates_isolated_branch(self):
        code, out, _ = self.claim('ENG-001', 'codex/test', '--worktree', '--base', 'main')
        self.assertEqual(code, 0, out)
        wt = self.repo / 'work' / 'worktrees' / 'eng-001'
        self.assertTrue((wt / 'tickets' / 'ENG-001.md').exists())
        branch = subprocess.run(['git', '-C', str(wt), 'branch', '--show-current'],
                                capture_output=True, text=True, check=True).stdout.strip()
        self.assertTrue(branch.startswith('ticket/eng-001-'))
        local = json.loads((wt / 'work' / 'agent-claim.json').read_text())
        self.assertEqual(local['ticket'], 'ENG-001')
        self.assertEqual(run(wt, 'heartbeat', 'ENG-001')[0], 0)

    def git(self, cwd, *argv):
        env = {**os.environ, 'GIT_AUTHOR_NAME': 't', 'GIT_AUTHOR_EMAIL': 't@example.invalid',
               'GIT_COMMITTER_NAME': 't', 'GIT_COMMITTER_EMAIL': 't@example.invalid'}
        return subprocess.run(['git', '-C', str(cwd), *argv], check=True, env=env,
                              capture_output=True, text=True).stdout.strip()

    def worktree_with_commit(self, tid):
        self.assertEqual(self.claim(tid, 'codex/test', '--worktree', '--base', 'main')[0], 0)
        wt = self.repo / 'work' / 'worktrees' / tid.lower()
        (wt / f'{tid}.txt').write_text('change\n')
        self.git(wt, 'add', f'{tid}.txt')
        self.git(wt, 'commit', '-q', '-m', f'work on {tid}')
        return wt, self.git(wt, 'branch', '--show-current')

    def test_cleanup_removes_only_clean_merged_worktrees(self):
        merged, merged_branch = self.worktree_with_commit('ENG-001')
        pending, _ = self.worktree_with_commit('ENG-004')
        self.git(self.repo, 'merge', '-q', '--no-ff', '-m', 'merge', merged_branch)
        with mock.patch.object(tickets, 'STALE_MINUTES', -1):
            code, out, _ = run(self.repo, 'cleanup', '--base', 'main', '--dry-run')
        self.assertEqual(code, 0, out)
        self.assertIn('would remove eng-001', out)
        self.assertTrue(merged.exists())
        with mock.patch.object(tickets, 'STALE_MINUTES', -1):
            code, out, _ = run(self.repo, 'cleanup', '--base', 'main')
        self.assertEqual(code, 0, out)
        self.assertFalse(merged.exists())
        self.assertEqual(self.git(self.repo, 'branch', '--list', merged_branch), '')
        self.assertIsNone(tickets.read_claim(tickets.lock_dir(self.repo), 'ENG-001'))
        self.assertIsNone(tickets.resource_holder(tickets.lock_dir(self.repo), 'shared-res'))
        self.assertTrue(pending.exists())
        self.assertIn('kept eng-004', out)
        self.assertIn('not merged into main', out)

    def test_cleanup_removes_squash_merged_worktree_only_when_its_changes_landed(self):
        squashed, squashed_branch = self.worktree_with_commit('ENG-001')
        (squashed / 'ENG-001.txt').write_text('change\nmore\n')
        self.git(squashed, 'commit', '-q', '-am', 'second commit')
        partial, _ = self.worktree_with_commit('ENG-004')
        (partial / 'extra.txt').write_text('not on main\n')
        self.git(partial, 'add', 'extra.txt')
        self.git(partial, 'commit', '-q', '-m', 'unlanded follow-up')
        self.git(self.repo, 'merge', '-q', '--squash', squashed_branch)
        self.git(self.repo, 'commit', '-q', '-m', 'squash ENG-001')
        (self.repo / 'ENG-004.txt').write_text('change\n')
        self.git(self.repo, 'add', 'ENG-004.txt')
        self.git(self.repo, 'commit', '-q', '-m', 'squash only the first ENG-004 commit')
        with mock.patch.object(tickets, 'STALE_MINUTES', -1):
            code, out, _ = run(self.repo, 'cleanup', '--base', 'main')
        self.assertEqual(code, 0, out)
        self.assertIn('removed eng-001', out)
        self.assertFalse(squashed.exists())
        self.assertEqual(self.git(self.repo, 'branch', '--list', squashed_branch), '')
        self.assertTrue(partial.exists())
        self.assertIn('kept eng-004', out)
        self.assertIn('not merged into main', out)

    def test_cleanup_keeps_branch_without_net_changes(self):
        wt, _ = self.worktree_with_commit('ENG-001')
        self.git(wt, 'revert', '--no-edit', 'HEAD')
        (self.repo / 'other.txt').write_text('main moved on\n')
        self.git(self.repo, 'add', 'other.txt')
        self.git(self.repo, 'commit', '-q', '-m', 'main moved on')
        with mock.patch.object(tickets, 'STALE_MINUTES', -1):
            code, out, _ = run(self.repo, 'cleanup', '--base', 'main')
        self.assertEqual(code, 0, out)
        self.assertTrue(wt.exists())
        self.assertIn('not merged into main', out)

    def test_cleanup_keeps_live_dirty_and_fresh_worktrees(self):
        live, live_branch = self.worktree_with_commit('ENG-001')
        dirty, dirty_branch = self.worktree_with_commit('ENG-004')
        self.git(self.repo, 'merge', '-q', '--no-ff', '-m', 'merge one', live_branch)
        self.git(self.repo, 'merge', '-q', '--no-ff', '-m', 'merge two', dirty_branch)
        self.assertEqual(run(dirty, 'release', 'ENG-004')[0], 0)
        (dirty / 'scratch.txt').write_text('unsaved\n')
        fresh = self.repo / 'work' / 'worktrees' / 'fresh'
        self.git(self.repo, 'worktree', 'add', '-q', '-b', 'fresh', str(fresh), 'main')
        code, out, _ = run(self.repo, 'cleanup', '--base', 'main')
        self.assertEqual(code, 0, out)
        self.assertIn('live claim on ENG-001', out)
        self.assertIn('uncommitted or untracked changes', out)
        self.assertIn('no commits of its own on main', out)
        self.assertTrue(live.exists() and dirty.exists() and fresh.exists())
        code, out, _ = run(live, 'cleanup', '--base', 'main')
        self.assertIn('kept eng-001 (' + live_branch + '): current worktree', out)

    def test_validation_rejects_cycles_unknown_deps_and_private_paths(self):
        self.write('ENG-001', deps='ENG-003')
        self.write('ENG-002', deps='ENG-099')
        path = self.repo / 'tickets' / 'ENG-004.md'
        path.write_text(path.read_text() + '\nSee /' + 'Users/someone/secret\n')  # split to keep the guard clean
        errors = '\n'.join(tickets.validate(tickets.load_tickets(self.repo)))
        self.assertIn('dependency cycle', errors)
        self.assertIn('unknown dependency ENG-099', errors)
        self.assertIn('machine-specific home path', errors)


SPEC_BODY = """
# SPC-001

## Goal

Show the synthetic total.

## Context

Background that may change freely.

## Requirements

- Unknown values are never zero.

```markdown
## Requirements
This fenced heading is example text, not a section.
```

## Acceptance criteria

- [ ] AC-SPC-001-01: Given 0.010 and 0.020, then 0.030 is shown.
- [ ] AC-SPC-001-02 [review]: No provider name appears in a label.

## Build plan

- frontend/src/v2/total.tsx (new)

## Plan

- [ ] Build it.

## Handoff

- State: none.

## Log

- 2026-11-17 test: created.
"""

# Canonical text written out by hand, independently of tickets.spec_hash.
SPEC_CANONICAL = (
    '## Goal\nShow the synthetic total.\n'
    '## Requirements\n- Unknown values are never zero.\n\n```markdown\n## Requirements\n'
    'This fenced heading is example text, not a section.\n```\n'
    '## Acceptance criteria\n- [ ] AC-SPC-001-01: Given 0.010 and 0.020, then 0.030 is shown.\n'
    '- [ ] AC-SPC-001-02 [review]: No provider name appears in a label.\n'
)
SPEC_EXPECTED = 'sha256:9cc58197f0d55cfb5d77f9175fba01ca4ab758584f96e395c1dc4550abd36973'


class SpecTest(unittest.TestCase):
    def test_fixed_vector(self):
        """AC-ENG-112-06."""
        import hashlib
        self.assertEqual('sha256:' + hashlib.sha256(SPEC_CANONICAL.encode()).hexdigest(), SPEC_EXPECTED)
        self.assertEqual(tickets.spec_hash(SPEC_BODY), SPEC_EXPECTED)

    def test_ticks_whitespace_and_ungated_sections_do_not_change_the_hash(self):
        """AC-ENG-112-04."""
        edited = (SPEC_BODY.replace('- [ ] AC-SPC-001-01', '- [x] AC-SPC-001-01')
                  .replace('- State: none.', '- State: half done.')
                  .replace('- [ ] Build it.', '- [x] Build it.')
                  .replace('total.tsx (new)', 'total.tsx (new); api.ts')
                  .replace('Background that may change freely.', 'Other background.')
                  .replace('Show the synthetic total.', 'Show the synthetic total.   ')
                  .replace('\n', '\r\n')
                  + '- 2026-11-18 test: another log line.\n')
        self.assertEqual(tickets.spec_hash(edited), SPEC_EXPECTED)

    def test_gated_text_changes_the_hash(self):
        """AC-ENG-112-04."""
        for old, new in (('then 0.030 is shown', 'then 0.031 is shown'),
                         ('never zero', 'never shown as zero'),
                         ('Show the synthetic total.', 'Show the total.')):
            self.assertNotEqual(tickets.spec_hash(SPEC_BODY.replace(old, new)), SPEC_EXPECTED, old)

    def test_fenced_heading_is_not_a_section(self):
        """AC-ENG-112-05."""
        sections = tickets.spec_sections(SPEC_BODY)
        self.assertIn('This fenced heading is example text', sections['Requirements'])
        self.assertIn('Acceptance criteria', sections)

    def test_fences_close_only_on_a_matching_marker(self):
        """AC-ENG-112-05: nested and mixed fences keep their headings as content."""
        nested = SPEC_BODY.replace('```markdown\n## Requirements', '````markdown\n```\n## Plan\n```\n## Requirements')
        nested = nested.replace('not a section.\n```\n', 'not a section.\n````\n')
        sections = tickets.spec_sections(nested)
        self.assertIn('## Plan', sections['Requirements'])
        self.assertIn('Build it', sections['Plan'])
        self.assertEqual(tickets.spec_hash(nested), tickets.spec_hash(nested.replace('Build it.', 'Build it now.')))
        tilde = SPEC_BODY.replace('```markdown', '~~~markdown').replace('not a section.\n```', 'not a section.\n```\n~~~')
        sections = tickets.spec_sections(tilde)
        self.assertIn('Acceptance criteria', sections)
        self.assertIn('AC-SPC-001-01', sections['Acceptance criteria'])
        inline = SPEC_BODY.replace('## Context', '```x``` is inline code\n\n## Context')
        self.assertIn('Context', tickets.spec_sections(inline))

    def test_all_checkbox_styles_and_bare_carriage_returns_are_normalised(self):
        """AC-ENG-112-04."""
        for tick in ('* [x]', '+ [X]', '1. [x]', '2) [x]'):
            plain = tick.replace('[x]', '[ ]').replace('[X]', '[ ]')
            body = SPEC_BODY.replace('- [ ] AC-SPC-001-02', plain + ' AC-SPC-001-02')
            self.assertEqual(tickets.spec_hash(body.replace(plain, tick)), tickets.spec_hash(body), tick)
        self.assertEqual(tickets.spec_hash(SPEC_BODY.replace('\n', '\r')), SPEC_EXPECTED)

    def test_duplicate_gated_section_is_reported(self):
        """AC-ENG-112-04: a second gated heading cannot slip text past the approval."""
        body = SPEC_BODY.replace('## Build plan', '## Acceptance criteria\n\n- [ ] AC-SPC-001-03: Extra.\n\n## Build plan')
        self.assertEqual(tickets.duplicate_gated_sections(body), ['Acceptance criteria'])
        self.assertEqual(tickets.duplicate_gated_sections(SPEC_BODY), [])

    def test_acceptance_ids_and_review_flags(self):
        self.assertEqual(tickets.acceptance_ids('SPC-001', SPEC_BODY),
                         [('AC-SPC-001-01', False), ('AC-SPC-001-02', True)])
        self.assertTrue(tickets.has_build_plan(SPEC_BODY))
        self.assertFalse(tickets.has_build_plan(SPEC_BODY.replace('- frontend/src/v2/total.tsx (new)', '')))


class SpecWorkflowTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.repo = Path(self.tmp.name) / 'repo'
        (self.repo / 'tickets').mkdir(parents=True)
        (self.repo / 'tests').mkdir()
        subprocess.run(['git', 'init', '-q', '-b', 'main', str(self.repo)], check=True, capture_output=True)

    def tearDown(self):
        self.tmp.cleanup()

    def write(self, tid, body, tier='standard', approved=''):
        head = TEMPLATE.split('---\n\n')[0].format(id=tid, status='ready', deps='', res='', tier=tier)
        head = head.replace('spec:\n', f'spec:\nspec_approved: {approved}\n')
        (self.repo / 'tickets' / f'{tid}.md').write_text(head + '---\n' + body.replace('SPC-001', tid), encoding='utf-8')

    def test_drifted_spec_is_not_offered_and_spec_reports_it(self):
        """AC-ENG-112-03, AC-ENG-112-04."""
        self.write('SPC-001', SPEC_BODY, approved=SPEC_EXPECTED)
        code, out, _ = run(self.repo, 'next', '--tier', 'standard')
        self.assertIn('SPC-001', out)
        code, out, _ = run(self.repo, 'spec', 'SPC-001')
        self.assertEqual(code, 0, out)
        self.assertIn('MATCHES the approved spec', out)
        self.write('SPC-001', SPEC_BODY.replace('then 0.030', 'then 0.040'), approved=SPEC_EXPECTED)
        code, out, _ = run(self.repo, 'next', '--tier', 'standard')
        self.assertNotIn('SPC-001', out)
        code, out, _ = run(self.repo, 'spec', 'SPC-001')
        self.assertEqual(code, 1)
        self.assertIn('CHANGED since approval', out)
        code, _, err = run(self.repo, 'claim', 'SPC-001', '--agent', 'codex/test')
        self.assertEqual(code, 2)
        self.assertIn('spec changed since approval', err)

    def test_takeover_of_a_drifted_spec_is_refused(self):
        """AC-ENG-112-04: a stale claim cannot be taken over on unapproved text."""
        self.write('SPC-001', SPEC_BODY, approved=SPEC_EXPECTED)
        env = {**os.environ, 'GIT_AUTHOR_NAME': 't', 'GIT_AUTHOR_EMAIL': 't@example.invalid',
               'GIT_COMMITTER_NAME': 't', 'GIT_COMMITTER_EMAIL': 't@example.invalid'}
        for cmd in (['add', '.'], ['commit', '-q', '-m', 'init']):
            subprocess.run(['git', '-C', str(self.repo), *cmd], check=True, env=env, capture_output=True)
        self.assertEqual(run(self.repo, 'claim', 'SPC-001', '--agent', 'codex/test')[0], 0)
        self.write('SPC-001', SPEC_BODY.replace('then 0.030', 'then 0.040'), approved=SPEC_EXPECTED)
        with mock.patch.object(tickets, 'STALE_MINUTES', -1):
            code, _, err = run(self.repo, 'takeover', 'SPC-001', '--agent', 'claude/test', '--reason', 'limit')
        self.assertEqual(code, 2)
        self.assertIn('spec changed since approval', err)

    def test_spec_compares_with_a_base_ref(self):
        """AC-ENG-112-03."""
        self.write('SPC-001', SPEC_BODY)
        env = {**os.environ, 'GIT_AUTHOR_NAME': 't', 'GIT_AUTHOR_EMAIL': 't@example.invalid',
               'GIT_COMMITTER_NAME': 't', 'GIT_COMMITTER_EMAIL': 't@example.invalid'}
        for cmd in (['add', '.'], ['commit', '-q', '-m', 'init']):
            subprocess.run(['git', '-C', str(self.repo), *cmd], check=True, env=env, capture_output=True)
        code, out, _ = run(self.repo, 'spec', 'SPC-001', '--base', 'main')
        self.assertIn('Base main: gated sections unchanged', out)
        self.write('SPC-001', SPEC_BODY.replace('then 0.030', 'then 0.040'))
        code, out, _ = run(self.repo, 'spec', 'SPC-001', '--base', 'main')
        self.assertIn('Base main: gated sections CHANGED', out)
        code, out, _ = run(self.repo, 'spec', 'SPC-001', '--base', 'no-such-ref')
        self.assertIn('no copy there', out)

    def test_spec_counts_test_mentions(self):
        """AC-ENG-112-03."""
        self.write('SPC-001', SPEC_BODY)
        (self.repo / 'tests' / 'test_total.py').write_text('# AC-SPC-001-01\n', encoding='utf-8')
        code, out, _ = run(self.repo, 'spec', 'SPC-001')
        self.assertEqual(code, 0, out)
        self.assertIn('not approved by hash', out)
        self.assertIn('AC-SPC-001-01  1 test file(s)', out)
        self.assertIn('AC-SPC-001-02  review-only', out)
        self.assertIn('Build plan:    present', out)

    def test_plan_queue_and_build_plan_warning(self):
        """AC-ENG-112-07."""
        no_plan = SPEC_BODY.replace('- frontend/src/v2/total.tsx (new)', '')
        self.write('SPC-001', no_plan)
        self.write('SPC-002', SPEC_BODY)
        self.write('SPC-003', no_plan, tier='any')
        code, out, _ = run(self.repo, 'next', '--plan')
        self.assertIn('SPC-001', out)
        self.assertIn('needs a build plan', out)
        self.assertNotIn('SPC-002', out)
        self.assertNotIn('SPC-003', out)
        code, out, _ = run(self.repo, 'next', '--tier', 'standard')
        line = next(l for l in out.splitlines() if l.startswith('SPC-001'))
        self.assertIn('no build plan', line)
        self.assertIn('SPC-002', out)

    def test_malformed_approval_is_a_validation_error(self):
        """AC-ENG-112-08 (the live board is covered by test_repository_tickets_are_valid)."""
        self.write('SPC-001', SPEC_BODY, approved='sha256:not-a-hash')
        self.write('SPC-002', SPEC_BODY, approved=SPEC_EXPECTED)
        errors = tickets.validate(tickets.load_tickets(self.repo))
        self.assertEqual(len(errors), 1, errors)
        self.assertIn('SPC-001.md: spec_approved must be', errors[0])


if __name__ == '__main__':
    unittest.main()

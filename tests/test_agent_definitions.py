"""Static checks of the published role agent files against AGENTS.md (ENG-115).

These tests prove the files say what the role table says. They cannot prove that a
fresh Claude Code or Codex session loads them; that evidence is recorded in the PR.
"""
from __future__ import annotations

from pathlib import Path
import re
import subprocess
import sys
import tempfile
import tomllib
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
import check_publication as guard  # noqa: E402
import docker_context  # noqa: E402

CLAUDE_AGENTS = {
    'planner': '.claude/agents/planner.md',
    'builder': '.claude/agents/builder.md',
    'reviewer': '.claude/agents/reviewer.md',
}
CODEX_BUILDER = '.codex/agents/builder.toml'


def role_table() -> dict[tuple[str, str], dict[str, str]]:
    """Rows of the AGENTS.md "Models and roles" table, keyed by (role, tool)."""
    text = (ROOT / 'AGENTS.md').read_text(encoding='utf-8')
    section = text.split('## Models and roles', 1)[1].split('\n## ', 1)[0]
    rows = {}
    for line in section.splitlines():
        cells = [cell.strip() for cell in line.strip().strip('|').split('|')]
        if len(cells) == 6 and cells[0] in {'Planner', 'Builder', 'Reviewer'}:
            role, tool, model, effort, agent_file, board = cells
            model_id = re.search(r'`([^`]+)`', model)
            rows[(role, tool)] = {
                'model': model_id.group(1) if model_id else '',
                'effort': effort,
                'file': agent_file.strip('`') if agent_file.startswith('`') else '',
                'board': board.strip('`'),
            }
    return rows


def frontmatter(relative: str) -> dict[str, str]:
    text = (ROOT / relative).read_text(encoding='utf-8')
    match = re.match(r'---\n(.*?)\n---\n', text, re.S)
    if not match:
        raise AssertionError('No frontmatter in ' + relative)
    fields = {}
    for line in match.group(1).splitlines():
        key, _, value = line.partition(':')
        fields[key.strip()] = value.strip()
    return fields


class AgentDefinitionTests(unittest.TestCase):
    def test_role_table_names_every_role_and_tool(self):
        """AC-ENG-115-01: the table holds the owner's roles, models and effort."""
        rows = role_table()
        self.assertEqual(set(rows), {('Planner', 'Claude Code'), ('Builder', 'Claude Code'),
                                     ('Builder', 'Codex'), ('Builder', 'OpenCode'),
                                     ('Reviewer', 'Claude Code')})
        self.assertEqual(rows[('Planner', 'Claude Code')]['model'], 'claude-opus-5-5')
        self.assertEqual(rows[('Planner', 'Claude Code')]['effort'], 'high')
        self.assertEqual(rows[('Builder', 'Claude Code')]['model'], 'claude-sonnet-5-5')
        self.assertEqual(rows[('Builder', 'Claude Code')]['effort'], 'medium')
        self.assertEqual(rows[('Builder', 'Codex')]['model'], 'gpt-6.1-sol')
        self.assertEqual(rows[('Builder', 'Codex')]['effort'], 'high')
        self.assertEqual(rows[('Reviewer', 'Claude Code')]['model'], 'claude-opus-5-5')
        self.assertEqual(rows[('Reviewer', 'Claude Code')]['effort'], 'high')
        # OpenCode is rule-only: no file and no provider-specific model ID.
        self.assertEqual(rows[('Builder', 'OpenCode')]['file'], '')
        self.assertEqual(rows[('Builder', 'OpenCode')]['model'], '')

    def test_claude_code_agents_match_the_table(self):
        """AC-ENG-115-04 (static part): each Claude Code agent pins the table's model and effort."""
        rows = role_table()
        for name, relative in CLAUDE_AGENTS.items():
            with self.subTest(agent=name):
                fields = frontmatter(relative)
                row = rows[(name.capitalize(), 'Claude Code')]
                self.assertEqual(row['file'], relative)
                self.assertEqual(fields['name'], name)
                self.assertTrue(fields['description'])
                self.assertEqual(fields['model'], row['model'])
                self.assertEqual(fields['effort'], row['effort'])
                body = (ROOT / relative).read_text(encoding='utf-8')
                # Each agent states its model in its first output and stops on a mismatch.
                self.assertIn('Start your first output with one line', body)
                self.assertIn('configured: {}, effort {}'.format(row['model'], row['effort']), body)
        self.assertIn('Edit', frontmatter(CLAUDE_AGENTS['reviewer'])['disallowedTools'])
        self.assertIn('Write', frontmatter(CLAUDE_AGENTS['reviewer'])['disallowedTools'])

    def test_codex_builder_matches_the_table(self):
        """AC-ENG-115-05 (static part): the Codex builder pins the table's model and effort."""
        row = role_table()[('Builder', 'Codex')]
        self.assertEqual(row['file'], CODEX_BUILDER)
        data = tomllib.loads((ROOT / CODEX_BUILDER).read_text(encoding='utf-8'))
        for key in ('name', 'description', 'developer_instructions'):
            self.assertTrue(data.get(key), key)  # Required by Codex.
        self.assertEqual(data['name'], 'builder')
        self.assertEqual(data['model'], row['model'])
        self.assertEqual(data['model_reasoning_effort'], row['effort'])
        # Codex ignores these in an agent file; setting them would mislead a reader.
        self.assertFalse({'sandbox_mode', 'approval_policy', 'model_provider'} & set(data))
        self.assertIn('--agent ' + row['board'], data['developer_instructions'])

    def test_builders_use_their_board_name_and_refuse_unplanned_tickets(self):
        """AC-ENG-115-01: builders record their model and never build without a merged plan."""
        rows = role_table()
        claude = (ROOT / CLAUDE_AGENTS['builder']).read_text(encoding='utf-8')
        self.assertIn('--agent ' + rows[('Builder', 'Claude Code')]['board'], claude)
        codex = tomllib.loads((ROOT / CODEX_BUILDER).read_text(encoding='utf-8'))['developer_instructions']
        for text in (claude, codex):
            self.assertIn('git show origin/main:tickets/<ID>.md', text)
            self.assertIn('needs planning', text)
            self.assertIn('You never plan', text)
        planner = (ROOT / CLAUDE_AGENTS['planner']).read_text(encoding='utf-8')
        self.assertIn('You never build', planner)

    def test_agent_files_are_exactly_the_published_set(self):
        """AC-ENG-115-06: the guard's allowlist is the four files the table names."""
        rows = role_table()
        named = {row['file'] for row in rows.values() if row['file']}
        self.assertEqual(named, set(guard.PUBLIC_AGENT_DEFINITIONS))
        for relative in named:
            self.assertTrue((ROOT / relative).is_file(), relative)

    def test_no_personal_provider_ids_or_paths(self):
        """AC-ENG-115-09 (automated part): tracked files hold no provider-prefixed DeepSeek ID."""
        listed = subprocess.run(['git', '-C', str(ROOT), 'ls-files', '-z'], capture_output=True)
        if listed.returncode:
            self.skipTest('not a Git checkout')
        # A provider-qualified ID: a provider prefix before the DeepSeek model name, or
        # any OpenRouter route. Built from parts so this file does not match itself.
        provider_id = re.compile(r'[A-Za-z0-9_.-]+/(?:[A-Za-z0-9_.-]+/)*deepseek[A-Za-z0-9_.:-]*'
                                 r'|\bopen' + r'router/[A-Za-z0-9_./:-]+', re.I)
        suffixes = {'.md', '.toml', '.py', '.json', '.yml', '.yaml', '.txt', '.ts', '.tsx'}
        for relative in listed.stdout.decode().split('\0'):
            path = ROOT / relative
            if not relative or not path.is_file() or path.suffix not in suffixes:
                continue
            text = path.read_text(encoding='utf-8', errors='replace')
            for match in provider_id.finditer(text):
                # The board name is a tool/model label, not a provider model ID.
                self.assertEqual(match.group(0).lower(), 'opencode/deepseek-flash', relative)
        for relative in guard.PUBLIC_AGENT_DEFINITIONS:
            text = (ROOT / relative).read_text(encoding='utf-8')
            self.assertNotRegex(text, r'/(?:Users|home)/')
            self.assertEqual(guard.content_issues(text.encode(), relative), [], relative)

    def test_agent_files_stay_out_of_the_image_context(self):
        """AC-ENG-115-06: publishing the files does not add them to the source-only image."""
        with tempfile.TemporaryDirectory() as directory:
            manifest = docker_context.prepare_context(ROOT, Path(directory) / 'context')
        self.assertFalse(set(manifest['files']) & guard.PUBLIC_AGENT_DEFINITIONS)
        self.assertFalse(any(name.startswith(('.claude/', '.codex/')) for name in manifest['files']))


if __name__ == '__main__':
    unittest.main()

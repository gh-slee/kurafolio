"""AC-ANL-012A-01: resolve display metadata for source-pinned positions."""
from datetime import datetime, timezone
import unittest

from kurafolio.projection.accepted import ProjectionUnavailable
from kurafolio.projection.entities import resolve_current_entities


def mapping(id_, revision, entity, version, plan, kind='account'):
    return {'id': id_, 'revision': revision, 'entity_kind': kind, 'entity_id': entity,
            'entity_version': version, 'plan_id': plan}


def account(id_, version, label):
    return {'id': id_, 'version': version, 'role': 'investment',
            'category': 'brokerage', 'label': label}


PLANS = tuple({'id': id_, 'created_at': datetime(2026, 1, day, tzinfo=timezone.utc)}
              for id_, day in (('p1', 1), ('p2', 2), ('p3', 2), ('p4', 3)))
ACCOUNTS = (account('a', 'v1', 'Original'), account('a', 'v2', 'Renamed'),
            account('a', 'v3', ''), account('b', 'v1', 'Other'),
            account('unmapped', 'v1', 'Unmapped'))
INSTRUMENTS = ({'id': 'instrument', 'version': 'v1', 'kind': 'CRYPTO',
                'currency': None, 'ticker': None, 'mic': None, 'symbol': 'BTC',
                'network': 'bitcoin', 'settlement_identity': None},)


class ProjectionEntitiesTests(unittest.TestCase):
    def resolve(self, mappings):
        return resolve_current_entities(mappings, PLANS, ACCOUNTS, INSTRUMENTS)

    def test_ac_01_current_revision_wins_even_if_its_plan_is_older(self):
        """AC-ANL-012A-01: a mapping's greatest revision defines its current target."""
        result = self.resolve((mapping('m1', 1, 'a', 'v1', 'p4'),
                               mapping('m1', 2, 'a', 'v2', 'p1')))
        self.assertEqual(result.accounts['a'].label, 'Renamed')

    def test_ac_01_current_target_wins_over_newer_historical_target(self):
        """AC-ANL-012A-01: a repointed mapping cannot outrank a current target."""
        result = self.resolve((mapping('m1', 1, 'a', 'v1', 'p1'),
                               mapping('m2', 1, 'a', 'v2', 'p3'),
                               mapping('m2', 2, 'b', 'v1', 'p4')))
        self.assertEqual(result.accounts['a'].label, 'Original')
        self.assertEqual(result.accounts['b'].label, 'Other')

    def test_ac_01_order_current_targets_by_plan_then_revision_then_mapping(self):
        """AC-ANL-012A-01: each ordering level breaks a distinct tie."""
        candidates = (mapping('m1', 5, 'a', 'v1', 'p2'),
                      mapping('m2', 1, 'a', 'v2', 'p3'),
                      mapping('m3', 2, 'a', 'v1', 'p3'),
                      mapping('m4', 2, 'a', 'v3', 'p3'),
                      mapping('m0', 1, 'a', 'v2', 'p4'))
        for count, version in enumerate(('v1', 'v2', 'v1', 'v3', 'v2'), start=1):
            with self.subTest(count=count):
                rows = tuple(reversed(candidates[:count]))
                self.assertEqual(self.resolve(rows).accounts['a'].version, version)

    def test_ac_01_repointed_target_uses_latest_historical_version(self):
        """AC-ANL-012A-01: a repointed entity keeps its own last label, even empty."""
        result = self.resolve((mapping('m1', 1, 'a', 'v1', 'p1'),
                               mapping('m1', 2, 'a', 'v3', 'p3'),
                               mapping('m1', 3, 'b', 'v1', 'p4'),
                               mapping('mi', 1, 'instrument', 'v1', 'p1', 'instrument')))
        self.assertEqual(result.accounts['a'].label, '')
        self.assertNotIn('unmapped', result.accounts)
        self.assertIsNone(result.instruments['instrument'].ticker)

    def test_ac_01_missing_plan_or_chosen_entity_is_refused(self):
        """AC-ANL-012A-01: foreign key inconsistencies give one stable failure."""
        for row in (mapping('m1', 1, 'a', 'v1', 'missing'),
                    mapping('m1', 1, 'a', 'missing', 'p1')):
            with self.subTest(row=row):
                with self.assertRaises(ProjectionUnavailable) as caught:
                    self.resolve((row,))
                self.assertEqual(caught.exception.code, 'projection_reference_missing')

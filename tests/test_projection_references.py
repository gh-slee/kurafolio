"""Synthetic reference-source and cache checks for AC-ANL-012A-03."""
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from io import StringIO
import json
import logging
import os
from pathlib import Path
import tempfile
from threading import Event
import unittest
from urllib.error import HTTPError
from urllib.parse import parse_qs, urlparse
from unittest.mock import patch

from kurafolio.projection.references import FixedReferences, LiveReferences, NoReferences


NOW = datetime(2026, 1, 15, 12, tzinfo=timezone.utc)
BTC = 'api.exchange.coinbase.com'
CAD = 'www.bankofcanada.ca'
TWD = 'www.cbc.gov.tw'


class ReferenceTests(unittest.TestCase):
    def setUp(self):
        self.now = NOW
        self.calls = []
        self.changes = {}
        self.reader = LiveReferences(fetch=self.fetch, clock=lambda: self.now)

    def fetch(self, url, timeout):
        parsed = urlparse(url)
        self.calls.append((parsed, timeout))
        fallback = {BTC: self.candle(), CAD: self.cad(), TWD: self.twd()}
        value = self.changes.get(parsed.hostname, fallback[parsed.hostname])
        if isinstance(value, Exception):
            raise value
        return value

    def candle(self, age=300):
        start = self.now - timedelta(seconds=age + 60)
        return f'[[{int(start.timestamp())}, 1, 2, 3, 60000.123456789123456789, 4]]'.encode()

    def cad(self, age=2):
        day = self.now.date() - timedelta(days=age)
        return json.dumps({'observations': [{'d': str(day), 'FXUSDCAD': {'v': '1.4'}}]}).encode()

    def twd(self, age=3):
        day = self.now.date() - timedelta(days=age)
        return f'var chartDate = [["{day:%Y/%m/%d}"]]; var chartNum = [[32.01]];'.encode()

    def test_ac_anl_012a_03_sources_and_inputs(self):
        snapshot = self.reader.snapshot()
        self.assertEqual(snapshot.valuation_time, NOW)
        self.assertEqual(snapshot.btc.price, Decimal('60000.123456789123456789'))
        self.assertEqual(snapshot.btc.as_of, NOW - timedelta(minutes=5))
        self.assertEqual(snapshot.btc.source, 'Coinbase Exchange')
        inputs = snapshot.inputs('TWD')
        self.assertEqual(inputs.report_currencies, ('TWD',))
        self.assertEqual(inputs.crypto_quotes, {'BTC': snapshot.btc})
        self.assertEqual(inputs.security_quotes, {})
        self.assertEqual(inputs.fx.pivot, 'USD')
        self.assertEqual(inputs.fx.per_pivot, {'USD': Decimal(1), 'CAD': Decimal('1.4'),
                                            'TWD': Decimal('32.01')})
        self.assertEqual(inputs.fx.as_of, datetime(2026, 1, 12, tzinfo=timezone.utc))
        self.assertEqual(inputs.fx.source, 'Bank of Canada; Central Bank of the Republic of China (Taiwan)')
        self.assertEqual([(url.hostname, timeout) for url, timeout in self.calls],
                         [(BTC, 4), (CAD, 4), (TWD, 4)])
        self.assertEqual(parse_qs(self.calls[0][0].query), {
            'start': [(NOW - timedelta(minutes=10)).isoformat()], 'end': [NOW.isoformat()],
            'granularity': ['60'],
        })
        self.assertEqual(parse_qs(self.calls[1][0].query), {
            'start_date': ['2026-01-05'], 'end_date': ['2026-01-15'],
        })
        self.assertEqual([rate.effective_date for rate in snapshot.fx],
                         [date(2026, 1, 13), date(2026, 1, 12)])
        self.assertIs(FixedReferences(snapshot).snapshot(), snapshot)

    def test_ac_anl_012a_03_old_data_is_omitted_independently(self):
        self.changes.update({BTC: self.candle(age=301), TWD: self.twd(age=11)})
        snapshot = self.reader.snapshot()
        self.assertIsNone(snapshot.btc)
        self.assertEqual([rate.currency for rate in snapshot.fx], ['CAD'])

    def test_ac_anl_012a_03_failures_are_isolated(self):
        errors = {
            BTC: [b'{not json', OSError(), TimeoutError(), b"[[1]]",
                  HTTPError('https://example.invalid', 500, '', {}, None)],
            CAD: [b'{"observations": 42}', b'{"observations": [{"d":"2026-01-15","FXUSDCAD":{"v":"0"}}]}'],
            TWD: [b'unknown page', b'var chartDate = [["2026/01/14"]]; var chartNum = [[NaN]];'],
        }
        omitted_currency = {CAD: 'CAD', TWD: 'TWD'}
        for host, cases in errors.items():
            for error in cases:
                with self.subTest(host=host, error=error):
                    self.changes = {host: error}
                    snapshot = LiveReferences(fetch=self.fetch, clock=lambda: self.now).snapshot()
                    self.assertEqual(snapshot.btc is None, host == BTC)
                    self.assertEqual({r.currency for r in snapshot.fx},
                                     {'CAD', 'TWD'} - {omitted_currency.get(host)})

    def test_ac_anl_012a_03_snapshot_and_pair_expiry(self):
        first = self.reader.snapshot()
        self.now += timedelta(seconds=59)
        self.assertIs(self.reader.snapshot(), first)
        self.now += timedelta(seconds=2)
        self.assertEqual(self.reader.snapshot().valuation_time, self.now)
        self.assertEqual(Counter(url.hostname for url, _ in self.calls), {BTC: 2, CAD: 1, TWD: 1})
        self.now += timedelta(hours=1)
        self.reader.snapshot()
        self.assertEqual(Counter(url.hostname for url, _ in self.calls), {BTC: 3, CAD: 2, TWD: 2})

    def test_ac_anl_012a_03_failed_source_waits_to_retry(self):
        self.changes[TWD] = OSError()
        reader = LiveReferences(fetch=self.fetch, clock=lambda: self.now, snapshot_seconds=10)
        self.assertEqual([r.currency for r in reader.snapshot().fx], ['CAD'])
        del self.changes[TWD]
        self.now += timedelta(seconds=11)
        self.assertEqual([r.currency for r in reader.snapshot().fx], ['CAD'])
        self.now += timedelta(seconds=51)
        self.assertEqual([r.currency for r in reader.snapshot().fx], ['CAD', 'TWD'])
        self.assertEqual(sum(url.hostname == TWD for url, _ in self.calls), 2)

    def test_ac_anl_012a_03_old_snapshot_served_during_refresh(self):
        entered = Event()
        release = Event()

        def fetch(url, timeout):
            if self.now != NOW and urlparse(url).hostname == BTC:
                entered.set()
                if not release.wait(5):
                    raise TimeoutError()
            return self.fetch(url, timeout)

        reader = LiveReferences(fetch=fetch, clock=lambda: self.now)
        first = reader.snapshot()
        self.now += timedelta(seconds=61)
        with ThreadPoolExecutor(2) as pool:
            refreshing = pool.submit(reader.snapshot)
            try:
                self.assertTrue(entered.wait(3))
                self.assertIs(pool.submit(reader.snapshot).result(timeout=2), first)
            finally:
                release.set()
            self.assertEqual(refreshing.result(timeout=2).valuation_time, self.now)

    def test_ac_anl_012a_03_no_writes_or_logs(self):
        stream = StringIO()
        handler = logging.StreamHandler(stream)
        logger = logging.getLogger()
        logger.addHandler(handler)
        self.addCleanup(logger.removeHandler, handler)
        with tempfile.TemporaryDirectory() as directory:
            original = Path.cwd()
            try:
                os.chdir(directory)
                self.reader.snapshot()
                self.now += timedelta(seconds=61)
                self.changes[BTC] = TimeoutError('hidden payload')
                self.reader.snapshot()
                self.assertEqual(list(Path(directory).iterdir()), [])
            finally:
                os.chdir(original)
        self.assertEqual(stream.getvalue(), '')

    def test_ac_anl_012a_03_no_fetch_provider_reuses_empty_snapshot(self):
        reader = NoReferences(clock=lambda: self.now)
        with patch('kurafolio.projection.references._download', side_effect=AssertionError):
            first = reader.snapshot()
            self.assertEqual((first.btc, first.fx), (None, ()))
            self.assertIsNone(first.inputs('USD').fx)
            self.now += timedelta(seconds=59)
            self.assertIs(reader.snapshot(), first)
            self.now += timedelta(seconds=2)
            self.assertEqual(reader.snapshot().valuation_time, self.now)

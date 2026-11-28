"""Read public valuation references without accessing portfolio data or files."""
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal, DecimalException
from http.client import HTTPException
import json
from threading import Lock
from typing import Protocol
from urllib.parse import urlencode
from urllib.request import HTTPRedirectHandler, HTTPSHandler, Request, build_opener

from kurafolio import fx, prices

from .model import CryptoQuote, FxTable, ValuationInputs


BTC_URL = 'https://api.exchange.coinbase.com/products/BTC-USD/candles'


@dataclass(frozen=True, slots=True)
class FxRate:
    currency: str
    per_usd: Decimal
    effective_date: date
    source: str


@dataclass(frozen=True, slots=True)
class ReferenceSnapshot:
    valuation_time: datetime
    btc: CryptoQuote | None
    fx: tuple[FxRate, ...]

    def inputs(self, currency: str) -> ValuationInputs:
        table = None
        if self.fx:
            table = FxTable(
                'USD',
                {'USD': Decimal(1)} | {rate.currency: rate.per_usd for rate in self.fx},
                datetime.combine(min(rate.effective_date for rate in self.fx), time.min, timezone.utc),
                '; '.join(rate.source for rate in self.fx),
            )
        return ValuationInputs(self.valuation_time, (currency,), table, {},
                               {'BTC': self.btc} if self.btc is not None else {})


class References(Protocol):
    def snapshot(self) -> ReferenceSnapshot: ...


class FixedReferences:
    def __init__(self, snapshot: ReferenceSnapshot):
        self._snapshot = snapshot

    def snapshot(self) -> ReferenceSnapshot:
        return self._snapshot


def utc_now():
    return datetime.now(timezone.utc)


class _SnapshotCache:
    def __init__(self, clock, snapshot_seconds):
        self._clock = clock
        self._snapshot_window = timedelta(seconds=snapshot_seconds)
        self._snapshot = None
        self._lock = Lock()

    def snapshot(self) -> ReferenceSnapshot:
        now = self._clock().astimezone(timezone.utc).replace(microsecond=0)
        previous = self._snapshot
        if previous is not None and now < previous.valuation_time + self._snapshot_window:
            return previous
        if not self._lock.acquire(blocking=previous is None):
            return previous
        try:
            current = self._snapshot
            if current is None or now >= current.valuation_time + self._snapshot_window:
                current = self._refresh(now)
                self._snapshot = current
            return current
        finally:
            self._lock.release()


class NoReferences(_SnapshotCache):
    def __init__(self, *, clock=utc_now, snapshot_seconds=60):
        super().__init__(clock, snapshot_seconds)

    def _refresh(self, time):
        return ReferenceSnapshot(time, None, ())


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        # Accept only HTTP 200 from the requested reference URL.
        return None


def _download(url, timeout):
    request = Request(url, headers={'User-Agent': 'Kurafolio/1.0'})
    opener = build_opener(HTTPSHandler(context=prices.tls_context()), _NoRedirect())
    with opener.open(request, timeout=timeout) as response:
        if response.status != 200:
            raise OSError('Reference request failed')
        return response.read()


class LiveReferences(_SnapshotCache):
    def __init__(self, *, fetch=None, clock=utc_now, snapshot_seconds=60,
                 fx_seconds=3600, retry_seconds=60, timeout=4):
        super().__init__(clock, snapshot_seconds)
        self._fetch = fetch if fetch is not None else _download
        self._fx_window = timedelta(seconds=fx_seconds)
        self._retry_window = timedelta(seconds=retry_seconds)
        self._timeout = timeout
        self._sources = {}

    def _reference(self, key, provider, now, window):
        cached = self._sources.get(key)
        if cached is not None and now < cached[1]:
            return cached[0]
        try:
            result = provider(now)
        except (OSError, HTTPException, ValueError, TypeError, KeyError, IndexError,
                DecimalException, OverflowError):
            result = None
        self._sources[key] = (result, now + (window if result is not None else self._retry_window))
        return result

    def _refresh(self, now):
        btc = self._reference('BTC', self._btc, now, timedelta(0))
        cad = self._reference('CAD', self._cad, now, self._fx_window)
        twd = self._reference('TWD', self._twd, now, self._fx_window)
        return ReferenceSnapshot(now, btc, tuple(rate for rate in (cad, twd) if rate is not None))

    def _btc(self, now):
        query = urlencode({'granularity': 60, 'start': (now - timedelta(minutes=10)).isoformat(),
                           'end': now.isoformat()})
        rows = json.loads(self._fetch(f'{BTC_URL}?{query}', self._timeout), parse_float=Decimal)
        candle = prices.select_candle(rows, now.isoformat())
        return CryptoQuote('BTC', Decimal(candle['close']), 'USD',
                           datetime.fromisoformat(candle['candle_end']), 'Coinbase Exchange')

    def _cad(self, now):
        day = now.date()
        start = day - timedelta(days=10)
        raw = self._fetch(f'{fx.BOC_URL}?start_date={start}&end_date={day}', self._timeout)
        rows = [(date.fromisoformat(item['d']), item['FXUSDCAD']['v'])
                for item in json.loads(raw, parse_float=Decimal)['observations'] if 'FXUSDCAD' in item]
        return self._rate('CAD', day, rows, 'Bank of Canada')

    def _twd(self, now):
        html = self._fetch(fx.CBC_URL, self._timeout).decode('utf-8-sig')
        return self._rate('TWD', now.date(), fx.parse_cbc_html(html),
                          'Central Bank of the Republic of China (Taiwan)')

    @staticmethod
    def _rate(currency, day, rows, source):
        effective_date, amount = fx._select(rows, day)
        rate = Decimal(amount)
        if not rate.is_finite() or rate <= 0:
            raise ValueError('Reference rate must be finite and positive')
        return FxRate(currency, rate, date.fromisoformat(effective_date), source)

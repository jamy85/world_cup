"""Price / FX providers for the P&L monitor.

Two backends implement the same interface:

* ``BloombergProvider`` — talks to a **local Bloomberg Terminal** via the Desktop
  API (``blpapi``), connecting to ``localhost:8194``. Only works on a machine
  where the Terminal is installed and logged in.
* ``MockProvider`` — deterministic synthetic clean prices, accrued interest and
  FX so the whole app and attribution engine run anywhere (no Terminal needed).

``get_provider()`` returns whichever is usable so the app degrades gracefully.

Interface (dates are ``datetime.date``):

* ``price_series(fields_by_ticker, start, end)``
    ``fields_by_ticker``: ``{ticker: [field, ...]}`` (e.g. bonds need
    ``["PX_LAST", "INT_ACC"]``, futures ``["PX_LAST"]``).
    Returns ``{ticker: {field: {date: value}}}`` — daily, trading days only.
* ``fx_to_usd_series(currencies, start, end)``
    Returns ``{ccy: {date: rate_to_usd}}`` where value × local = USD. USD -> 1.0.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import math
from typing import Dict, List, Mapping, Tuple


class PriceProvider:
    name = "abstract"
    is_live = False

    def price_series(self, fields_by_ticker, start, end):
        raise NotImplementedError

    def fx_to_usd_series(self, currencies, start, end):
        raise NotImplementedError

    # -- shared helper -----------------------------------------------------
    @staticmethod
    def value_on_or_before(series: Mapping[dt.date, float], target: dt.date):
        """Last observation on or before ``target`` (handles weekends/holidays)."""
        candidates = [d for d in series if d <= target]
        if not candidates:
            return None
        return series[max(candidates)]


# ---------------------------------------------------------------------------
# Mock backend
# ---------------------------------------------------------------------------
# Rough FX levels (units of USD per 1 unit of currency), drifting by date.
_FX_BASE = {
    "USD": 1.0,
    "EUR": 1.07,
    "GBP": 1.27,
    "JPY": 0.0066,
    "AUD": 0.66,
    "CAD": 0.73,
    "CHF": 1.12,
}


class MockProvider(PriceProvider):
    """Deterministic pseudo-market-data seeded by ticker, drifting by date."""

    name = "Mock (synthetic prices — NOT market data)"
    is_live = False

    @staticmethod
    def _seed(key: str) -> int:
        return int(hashlib.md5(key.encode()).hexdigest(), 16)

    def _clean_price(self, ticker: str, date: dt.date) -> float:
        seed = self._seed(ticker)
        upper = ticker.upper()
        if "COMDTY" in upper or "INDEX" in upper:
            base = 105.0 + (seed % 4000) / 100.0        # futures ~105 .. 145
        else:
            base = 95.0 + (seed % 1200) / 100.0         # bonds ~95 .. 107
        n = date.toordinal()
        phase = (seed % 360) * math.pi / 180.0
        drift = 1.3 * math.sin(n / 23.0 + phase) + 0.8 * math.sin(n / 6.0 + phase)
        return round(base + drift, 4)

    def _accrued(self, ticker: str, date: dt.date) -> float:
        """Accrued interest per 100, ramping over a semiannual period then resetting."""
        seed = self._seed(ticker + "|cpn")
        coupon = 0.5 + (seed % 400) / 100.0             # 0.5% .. 4.5%
        period = 182
        offset = seed % period
        day_in_period = (date.toordinal() - offset) % period
        return round((coupon / 2.0) * (day_in_period / period), 6)

    def price_series(self, fields_by_ticker, start, end):
        out: Dict[str, Dict[str, Dict[dt.date, float]]] = {}
        for ticker, fields in fields_by_ticker.items():
            by_field: Dict[str, Dict[dt.date, float]] = {f: {} for f in fields}
            d = start
            while d <= end:
                if d.weekday() < 5:
                    for f in fields:
                        if f == "INT_ACC":
                            by_field[f][d] = self._accrued(ticker, d)
                        else:
                            by_field[f][d] = self._clean_price(ticker, d)
                d += dt.timedelta(days=1)
            out[ticker] = by_field
        return out

    def _fx(self, ccy: str, date: dt.date) -> float:
        base = _FX_BASE.get(ccy.upper(), 1.0)
        if ccy.upper() == "USD":
            return 1.0
        seed = self._seed("FX|" + ccy.upper())
        n = date.toordinal()
        drift = 1.0 + 0.02 * math.sin(n / 40.0 + (seed % 100) / 100.0)
        return round(base * drift, 6)

    def fx_to_usd_series(self, currencies, start, end):
        out: Dict[str, Dict[dt.date, float]] = {}
        for ccy in currencies:
            series: Dict[dt.date, float] = {}
            d = start
            while d <= end:
                if d.weekday() < 5:
                    series[d] = self._fx(ccy, d)
                d += dt.timedelta(days=1)
            out[ccy.upper()] = series
        return out


# ---------------------------------------------------------------------------
# Bloomberg backend (Desktop API)
# ---------------------------------------------------------------------------
class BloombergProvider(PriceProvider):
    """Live data from a local Bloomberg Terminal via ``blpapi`` (localhost:8194)."""

    name = "Bloomberg Terminal (Desktop API)"
    is_live = True

    def __init__(self, host: str = "localhost", port: int = 8194):
        import blpapi

        self._blpapi = blpapi
        opts = blpapi.SessionOptions()
        opts.setServerHost(host)
        opts.setServerPort(port)
        self._session = blpapi.Session(opts)
        if not self._session.start():
            raise ConnectionError(
                "Could not start blpapi session — is the Bloomberg Terminal "
                "running and logged in on this machine?"
            )
        if not self._session.openService("//blp/refdata"):
            raise ConnectionError("Could not open //blp/refdata service.")
        self._svc = self._session.getService("//blp/refdata")

    def _drain(self):
        blpapi = self._blpapi
        while True:
            ev = self._session.nextEvent(500)
            if ev.eventType() in (
                blpapi.Event.PARTIAL_RESPONSE,
                blpapi.Event.RESPONSE,
            ):
                for msg in ev:
                    yield msg
                if ev.eventType() == blpapi.Event.RESPONSE:
                    break

    def _historical(self, tickers: List[str], fields: List[str], start, end):
        """One HistoricalDataRequest for a set of tickers sharing the same fields."""
        req = self._svc.createRequest("HistoricalDataRequest")
        for t in tickers:
            req.append("securities", t)
        for f in fields:
            req.append("fields", f)
        req.set("startDate", start.strftime("%Y%m%d"))
        req.set("endDate", end.strftime("%Y%m%d"))
        req.set("periodicitySelection", "DAILY")
        req.set("nonTradingDayFillOption", "ACTIVE_DAYS_ONLY")
        self._session.sendRequest(req)

        result: Dict[str, Dict[str, Dict[dt.date, float]]] = {}
        for msg in self._drain():
            sec = msg.getElement("securityData")
            ticker = sec.getElementAsString("security")
            per_field = result.setdefault(ticker, {f: {} for f in fields})
            fdarr = sec.getElement("fieldData")
            for i in range(fdarr.numValues()):
                row = fdarr.getValueAsElement(i)
                d = row.getElementAsDatetime("date")
                day = dt.date(d.year, d.month, d.day)
                for f in fields:
                    if row.hasElement(f):
                        per_field[f][day] = row.getElementAsFloat(f)
        return result

    def price_series(self, fields_by_ticker, start, end):
        # Group tickers by identical field sets to minimise requests.
        groups: Dict[Tuple[str, ...], List[str]] = {}
        for ticker, fields in fields_by_ticker.items():
            groups.setdefault(tuple(fields), []).append(ticker)
        out: Dict[str, Dict[str, Dict[dt.date, float]]] = {}
        for fields, tickers in groups.items():
            out.update(self._historical(tickers, list(fields), start, end))
        return out

    def fx_to_usd_series(self, currencies, start, end):
        out: Dict[str, Dict[dt.date, float]] = {}
        pairs = {}
        for ccy in currencies:
            u = ccy.upper()
            if u == "USD":
                continue
            pairs[f"{u}USD Curncy"] = u
        if pairs:
            hist = self._historical(list(pairs), ["PX_LAST"], start, end)
            for tick, u in pairs.items():
                out[u] = hist.get(tick, {}).get("PX_LAST", {})
        # USD is identity across the whole window.
        if any(c.upper() == "USD" for c in currencies):
            d = start
            usd = {}
            while d <= end:
                if d.weekday() < 5:
                    usd[d] = 1.0
                d += dt.timedelta(days=1)
            out["USD"] = usd
        return out


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------
def get_provider(prefer_bloomberg: bool = True):
    """Return ``(provider, warning_or_None)``."""
    if prefer_bloomberg:
        try:
            return BloombergProvider(), None
        except ImportError:
            warning = (
                "`blpapi` is not installed, so Bloomberg data is unavailable. "
                "Showing synthetic mock prices. See README for install steps."
            )
        except Exception as exc:  # pragma: no cover - connection issues
            warning = (
                f"Could not connect to a Bloomberg Terminal ({exc}). "
                "Showing synthetic mock prices instead."
            )
        return MockProvider(), warning
    return MockProvider(), "Bloomberg disabled by user — showing mock prices."

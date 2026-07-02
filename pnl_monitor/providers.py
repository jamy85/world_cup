"""Price providers for the P&L monitor.

Two backends implement the same interface:

* ``BloombergProvider`` — talks to a **local Bloomberg Terminal** via the Desktop
  API (``blpapi``). It connects to ``localhost:8194`` and therefore only works on
  a machine where the Terminal is installed and logged in.
* ``MockProvider`` — deterministic synthetic prices so the app (and the P&L
  engine) can run anywhere, including CI or a cloud dev box with no Terminal.

``get_provider()`` returns whichever one is usable, so the app degrades
gracefully instead of crashing when Bloomberg is absent.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import math
from typing import Dict, Iterable, Mapping, Tuple


class PriceProvider:
    """Interface shared by the real and mock backends."""

    #: Human-readable name shown in the UI.
    name = "abstract"
    #: Whether this is a live market-data connection.
    is_live = False

    def spot(self, fields: Mapping[str, str]) -> Dict[str, float]:
        """Return the latest price for each ``{ticker: field}`` entry."""
        raise NotImplementedError

    def historical(
        self,
        fields: Mapping[str, str],
        start: dt.date,
        end: dt.date,
    ) -> Dict[str, Dict[dt.date, float]]:
        """Return a daily price series per ticker over ``[start, end]``.

        Missing days (weekends/holidays) simply do not appear in the series;
        callers pick the last observation on or before the date they want.
        """
        raise NotImplementedError

    # -- shared helper -----------------------------------------------------
    def price_on_or_before(
        self,
        series: Mapping[dt.date, float],
        target: dt.date,
    ) -> Tuple[dt.date, float] | Tuple[None, None]:
        """Last available observation on or before ``target``."""
        candidates = [d for d in series if d <= target]
        if not candidates:
            return None, None
        d = max(candidates)
        return d, series[d]


# ---------------------------------------------------------------------------
# Mock backend
# ---------------------------------------------------------------------------
class MockProvider(PriceProvider):
    """Deterministic pseudo-prices, seeded by ticker, drifting smoothly by date.

    The same (ticker, date) always yields the same price, so P&L numbers are
    stable across runs and reviewable in tests. Bonds land roughly in the
    95-108 range and futures in the 105-135 range based on a rough guess from
    the ticker's yellow key.
    """

    name = "Mock (synthetic prices — NOT market data)"
    is_live = False

    @staticmethod
    def _seed(ticker: str) -> int:
        return int(hashlib.md5(ticker.encode()).hexdigest(), 16)

    def _price(self, ticker: str, date: dt.date) -> float:
        seed = self._seed(ticker)
        # Rough base level by instrument type.
        upper = ticker.upper()
        if "COMDTY" in upper or "INDEX" in upper or "CURNCY" in upper:
            base = 105.0 + (seed % 3000) / 100.0          # ~105 .. 135
        else:
            base = 95.0 + (seed % 1300) / 100.0           # ~95 .. 108 (bonds)
        # Smooth, deterministic drift so historical != spot.
        n = date.toordinal()
        phase = (seed % 360) * math.pi / 180.0
        drift = 1.4 * math.sin(n / 23.0 + phase) + 0.9 * math.sin(n / 7.0 + phase)
        wiggle = ((seed >> 8) % 17 - 8) * 0.01 * ((n % 11) - 5)
        return round(base + drift + wiggle, 4)

    def spot(self, fields: Mapping[str, str]) -> Dict[str, float]:
        today = _today()
        return {t: self._price(t, today) for t in fields}

    def historical(
        self,
        fields: Mapping[str, str],
        start: dt.date,
        end: dt.date,
    ) -> Dict[str, Dict[dt.date, float]]:
        out: Dict[str, Dict[dt.date, float]] = {}
        for ticker in fields:
            series: Dict[dt.date, float] = {}
            d = start
            while d <= end:
                if d.weekday() < 5:  # weekdays only, like a real price series
                    series[d] = self._price(ticker, d)
                d += dt.timedelta(days=1)
            out[ticker] = series
        return out


# ---------------------------------------------------------------------------
# Bloomberg backend (Desktop API)
# ---------------------------------------------------------------------------
class BloombergProvider(PriceProvider):
    """Live prices from a local Bloomberg Terminal via ``blpapi``.

    Requires:
      * a logged-in Bloomberg Terminal on this machine, and
      * ``pip install blpapi`` (from the Bloomberg-hosted index — see README).

    Connects to the Desktop API service ``//blp/refdata`` on localhost:8194.
    """

    name = "Bloomberg Terminal (Desktop API)"
    is_live = True

    def __init__(self, host: str = "localhost", port: int = 8194):
        import blpapi  # imported lazily so the module loads without it

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

    # -- request plumbing --------------------------------------------------
    def _drain(self):
        """Yield final RESPONSE messages for the pending request."""
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

    def spot(self, fields: Mapping[str, str]) -> Dict[str, float]:
        # Group tickers by the field they need so we send one request per field.
        by_field: Dict[str, list] = {}
        for ticker, field in fields.items():
            by_field.setdefault(field, []).append(ticker)

        out: Dict[str, float] = {}
        for field, tickers in by_field.items():
            req = self._svc.createRequest("ReferenceDataRequest")
            for t in tickers:
                req.append("securities", t)
            req.append("fields", field)
            self._session.sendRequest(req)
            for msg in self._drain():
                data = msg.getElement("securityData")
                for i in range(data.numValues()):
                    sec = data.getValueAsElement(i)
                    ticker = sec.getElementAsString("security")
                    fd = sec.getElement("fieldData")
                    if fd.hasElement(field):
                        out[ticker] = fd.getElementAsFloat(field)
        return out

    def historical(
        self,
        fields: Mapping[str, str],
        start: dt.date,
        end: dt.date,
    ) -> Dict[str, Dict[dt.date, float]]:
        by_field: Dict[str, list] = {}
        for ticker, field in fields.items():
            by_field.setdefault(field, []).append(ticker)

        out: Dict[str, Dict[dt.date, float]] = {}
        for field, tickers in by_field.items():
            req = self._svc.createRequest("HistoricalDataRequest")
            for t in tickers:
                req.append("securities", t)
            req.append("fields", field)
            req.set("startDate", start.strftime("%Y%m%d"))
            req.set("endDate", end.strftime("%Y%m%d"))
            req.set("periodicitySelection", "DAILY")
            req.set("nonTradingDayFillOption", "ACTIVE_DAYS_ONLY")
            self._session.sendRequest(req)
            for msg in self._drain():
                sec = msg.getElement("securityData")
                ticker = sec.getElementAsString("security")
                series = out.setdefault(ticker, {})
                fdarr = sec.getElement("fieldData")
                for i in range(fdarr.numValues()):
                    row = fdarr.getValueAsElement(i)
                    d = row.getElementAsDatetime("date")
                    if row.hasElement(field):
                        series[dt.date(d.year, d.month, d.day)] = (
                            row.getElementAsFloat(field)
                        )
        return out


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------
def _today() -> dt.date:
    return dt.date.today()


def get_provider(prefer_bloomberg: bool = True) -> Tuple[PriceProvider, str | None]:
    """Return ``(provider, warning)``.

    Tries Bloomberg first when ``prefer_bloomberg`` is set; falls back to the
    mock provider with a warning string explaining why.
    """
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

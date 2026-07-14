"""
Tests for data_pipeline.weather_service.get_season_window().

Regression test for a real bug: the live weather fetch used a fixed
'120 days back from today' window. For roughly 6 months of the year
(April-September, Zimbabwe's dry season), that trailing window always
landed entirely within the dry season, so live rainfall was compared
against a full wet-season province norm and *every* province showed an
identical severe 'rainfall deficit' / High risk, regardless of actual
conditions — which is exactly what showed up as identical text for all
10 provinces in the Ministry dashboard's Early Warning Feed.
"""
import datetime
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from data_pipeline.weather_service import get_season_window


def _window_for(monkeypatch, fake_today):
    class _FakeDate(datetime.date):
        @classmethod
        def today(cls):
            return fake_today
    monkeypatch.setattr(datetime, "date", _FakeDate)
    return get_season_window()


def test_dry_season_uses_completed_prior_season_full_prorate(monkeypatch):
    # 14 July -> dry season -> should use the most recently COMPLETED
    # season (prior Oct 1 - Mar 31), with prorate_fraction=1.0 (full,
    # like-for-like comparison against the full-season norm).
    start, end, prorate, label = _window_for(monkeypatch, datetime.date(2026, 7, 14))
    assert start == datetime.date(2025, 10, 1)
    assert end == datetime.date(2026, 3, 31)
    assert prorate == 1.0
    assert "completed" in label


def test_wet_season_uses_partial_season_to_date(monkeypatch):
    # Mid-December -> an active growing season -> should use Oct 1 through
    # today, with prorate_fraction < 1.0 (season is still in progress).
    start, end, prorate, label = _window_for(monkeypatch, datetime.date(2026, 12, 15))
    assert start == datetime.date(2026, 10, 1)
    assert end == datetime.date(2026, 12, 15)
    assert 0 < prorate < 1.0
    assert "to date" in label


def test_january_still_counts_as_the_season_that_started_the_prior_october(monkeypatch):
    start, end, prorate, label = _window_for(monkeypatch, datetime.date(2027, 2, 1))
    assert start == datetime.date(2026, 10, 1)
    assert 0 < prorate < 1.0


def test_prorate_fraction_never_exceeds_one(monkeypatch):
    # Even right at the end of the season window, prorate shouldn't exceed 1.0.
    start, end, prorate, label = _window_for(monkeypatch, datetime.date(2027, 3, 31))
    assert prorate <= 1.0

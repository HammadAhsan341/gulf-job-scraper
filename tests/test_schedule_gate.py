from datetime import datetime, timezone

from scripts.schedule_gate import half_hour_bucket, should_scrape

NOW = datetime(2026, 10, 19, 10, 37, tzinfo=timezone.utc)


def test_half_hour_bucket_floors_to_thirty_minute_windows():
    assert half_hour_bucket(datetime(2026, 10, 19, 10, 7, tzinfo=timezone.utc)) == "2026-10-19T10:00"
    assert half_hour_bucket(datetime(2026, 10, 19, 10, 29, tzinfo=timezone.utc)) == "2026-10-19T10:00"
    assert half_hour_bucket(datetime(2026, 10, 19, 10, 30, tzinfo=timezone.utc)) == "2026-10-19T10:30"
    assert half_hour_bucket(datetime(2026, 10, 19, 10, 59, tzinfo=timezone.utc)) == "2026-10-19T10:30"


def test_scrapes_when_this_half_hour_has_no_success():
    runs = [
        {
            "id": 1,
            "status": "completed",
            "conclusion": "success",
            "run_started_at": "2026-10-19T10:13:00Z",
        }
    ]
    scrape, reason = should_scrape(runs, NOW, "99")
    assert scrape is True
    assert "30-minute" in reason


def test_skips_when_this_half_hour_already_succeeded():
    runs = [
        {
            "id": 2,
            "status": "completed",
            "conclusion": "success",
            "run_started_at": "2026-10-19T10:33:00Z",
        }
    ]
    scrape, reason = should_scrape(runs, NOW, "99")
    assert scrape is False
    assert "30-minute" in reason


def test_scrapes_when_only_previous_half_hour_succeeded():
    runs = [
        {
            "id": 2,
            "status": "completed",
            "conclusion": "success",
            "run_started_at": "2026-10-19T10:13:00Z",
        }
    ]
    scrape, _reason = should_scrape(runs, NOW, "99")
    assert scrape is True


def test_retries_when_this_half_hour_failed():
    runs = [
        {
            "id": 3,
            "status": "completed",
            "conclusion": "failure",
            "run_started_at": "2026-10-19T10:33:00Z",
        }
    ]
    scrape, _reason = should_scrape(runs, NOW, "99")
    assert scrape is True


def test_still_scrapes_when_another_run_is_in_progress():
    runs = [{"id": 4, "status": "in_progress", "conclusion": None}]
    scrape, reason = should_scrape(runs, NOW, "99")
    assert scrape is True
    assert "30-minute" in reason


def test_ignores_the_current_run():
    runs = [
        {
            "id": 99,
            "status": "in_progress",
            "conclusion": None,
            "run_started_at": "2026-10-19T10:37:00Z",
        }
    ]
    scrape, _reason = should_scrape(runs, NOW, "99")
    assert scrape is True

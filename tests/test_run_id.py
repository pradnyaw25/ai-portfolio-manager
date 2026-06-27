from datetime import UTC, datetime

from src.utils.run_id import create_run_id, utc_now_iso


def test_create_run_id_includes_utc_timestamp():
    run_id = create_run_id(datetime(2024, 6, 1, 12, 30, 45, tzinfo=UTC))

    assert run_id.startswith("run_20240601T123045Z_")
    assert len(run_id.rsplit("_", 1)[1]) == 8


def test_utc_now_iso_uses_z_suffix():
    assert utc_now_iso().endswith("Z")

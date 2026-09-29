from __future__ import annotations

from pathlib import Path

import pytest

from scripts.ci_test_shard import (
    REPO_ROOT,
    discover_test_files,
    load_durations,
    partition_test_files,
)


def test_real_ci_shards_are_complete_disjoint_and_balanced() -> None:
    test_files = discover_test_files()
    durations = load_durations()
    groups, totals = partition_test_files(test_files, durations, 3)

    flattened = [test_file for group in groups for test_file in group]
    assert sorted(flattened) == test_files
    assert len(flattened) == len(set(flattened))
    assert all(group == sorted(group) for group in groups)
    assert max(totals) - min(totals) < 1.0


def test_new_test_file_uses_fallback_without_being_dropped() -> None:
    groups, totals = partition_test_files(
        ["tests/test_a.py", "tests/test_b.py", "tests/test_new.py"],
        {"tests/test_a.py": 3.0, "tests/test_b.py": 1.0},
        2,
    )

    assert sorted(test_file for group in groups for test_file in group) == [
        "tests/test_a.py",
        "tests/test_b.py",
        "tests/test_new.py",
    ]
    assert totals == pytest.approx([3.0, 3.0])


def test_partition_accounts_for_first_shard_preflight_cost() -> None:
    groups, totals = partition_test_files(
        ["tests/test_a.py", "tests/test_b.py", "tests/test_c.py", "tests/test_d.py"],
        {
            "tests/test_a.py": 4.0,
            "tests/test_b.py": 4.0,
            "tests/test_c.py": 2.0,
            "tests/test_d.py": 2.0,
        },
        2,
        initial_totals=[4.0, 0.0],
    )

    assert groups == [
        ["tests/test_b.py"],
        ["tests/test_a.py", "tests/test_c.py", "tests/test_d.py"],
    ]
    assert totals == pytest.approx([8.0, 8.0])


@pytest.mark.parametrize("splits", [0, -1])
def test_invalid_split_count_is_rejected(splits: int) -> None:
    with pytest.raises(ValueError, match="splits must be positive"):
        partition_test_files(["tests/test_a.py"], {}, splits)


def test_invalid_initial_totals_are_rejected() -> None:
    with pytest.raises(ValueError, match="initial_totals"):
        partition_test_files(["tests/test_a.py"], {}, 2, initial_totals=[0.0])


def test_duration_file_tracks_current_baseline_and_valid_paths() -> None:
    duration_path = REPO_ROOT / ".github" / "ci-test-durations.json"
    assert duration_path.is_file()
    durations = load_durations(duration_path)

    assert len(durations) >= 250
    assert all((REPO_ROOT / Path(test_file)).is_file() for test_file in durations)
    assert max(durations.values()) >= 30

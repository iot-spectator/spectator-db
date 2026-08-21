"""Tests for benchmarks/benchmark.py.

These guard the harness against rot rather than asserting on performance:
timings are machine-dependent and must never gate CI. What is checked is that
every phase still runs against the current API and that the reported figures
are self-consistent.
"""

import argparse
import importlib.util
import json
import pathlib
import random
import sys

import pytest


def _load_benchmark():
    """Import benchmarks/benchmark.py, which lives outside the package tree."""
    module_path = pathlib.Path(__file__).parent.parent / "benchmarks" / "benchmark.py"
    spec = importlib.util.spec_from_file_location("benchmark_harness", module_path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["benchmark_harness"] = module
    spec.loader.exec_module(module)
    return module


benchmark = _load_benchmark()


def test_percentile_uses_nearest_rank():
    samples = [1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0, 9.0, 10.0]
    assert benchmark._percentile(samples, 0.5) == 5.0
    assert benchmark._percentile(samples, 0.95) == 10.0
    assert benchmark._percentile([], 0.95) == 0.0


def test_summarize_reports_consistent_statistics():
    timings = benchmark._summarize([0.001, 0.002, 0.003])

    assert timings.count == 3
    assert timings.min_ms == 1.0
    assert timings.max_ms == 3.0
    assert timings.median_ms == 2.0
    assert timings.total_s == pytest.approx(0.006)
    assert timings.ops_per_s == pytest.approx(500.0)


def test_summarize_handles_no_samples():
    timings = benchmark._summarize([])

    assert timings.count == 0
    assert timings.ops_per_s == 0.0


def test_unit_vector_is_normalized():
    vector = benchmark._unit_vector(64, random.Random(0))

    assert len(vector) == 64
    assert sum(value * value for value in vector) == pytest.approx(1.0)


def test_parse_scales_accepts_a_list():
    assert benchmark._parse_scales("1000,10000") == (1000, 10000)


@pytest.mark.parametrize("raw", ["", "0", "-5", "abc", "10,0"])
def test_parse_scales_rejects_bad_input(raw):
    with pytest.raises(argparse.ArgumentTypeError):
        benchmark._parse_scales(raw)


def test_human_bytes_picks_a_unit():
    assert benchmark._human_bytes(512) == "512 B"
    assert benchmark._human_bytes(8192) == "8.0 KiB"
    assert benchmark._human_bytes(2 * 1024 * 1024) == "2.0 MiB"


def test_run_scale_measures_every_phase(tmp_path):
    """A tiny end-to-end run: every phase executes and the totals line up."""
    result = benchmark._run_scale(
        tmp_path / "scale",
        records=12,
        file_size=256,
        dim=8,
        repeats=2,
        seed=7,
    )

    assert result.records == 12
    assert result.insert.count == 12
    assert result.enrich.count == 12
    assert result.search.count == 2
    assert result.query_range.count == result.query_filtered.count

    # Twelve 256-byte files were copied into storage.
    assert result.media_bytes == 12 * 256

    # Attaching vectors can only grow the catalog.
    assert result.catalog_bytes_with_vectors >= result.catalog_bytes_no_vectors

    # The scratch directory holding the source file is cleaned up.
    assert not (tmp_path / "scale" / "scratch").exists()


def test_main_runs_and_writes_json(tmp_path, capsys):
    """The CLI completes a small run and emits both a report and raw JSON."""
    json_path = tmp_path / "out" / "results.json"
    exit_code = benchmark.main(
        [
            "--scales",
            "8",
            "--dim",
            "8",
            "--file-size",
            "128",
            "--repeats",
            "2",
            "--workdir",
            str(tmp_path / "work"),
        ]
        + ["--json", str(json_path)]
    )

    assert exit_code == 0

    payload = json.loads(json_path.read_text())
    assert payload["environment"]["python"]
    assert len(payload["scales"]) == 1
    assert payload["scales"][0]["records"] == 8
    assert payload["file_size_sweep"] == []

    report = capsys.readouterr().out
    assert "## Environment" in report
    assert "## Insert" in report
    assert "## Similarity search" in report
    assert "## On-disk size" in report


def test_main_rejects_invalid_dimensions(tmp_path):
    exit_code = benchmark.main(["--scales", "4", "--dim", "0"])
    assert exit_code == 2

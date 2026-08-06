"""Tests for the examples/photos.py command-line tool.

These guard the example against rot: it is the quick-start users copy from, so
its commands must keep working as the library evolves. The embedding path needs
an image decoder and is skipped where Pillow is absent.
"""

import importlib.util
import os
import pathlib
import sys

from datetime import datetime, timezone

import pytest

from tests.test_exif import _build_exif_jpeg


def _load_photos():
    """Import examples/photos.py, which lives outside the package tree."""
    module_path = pathlib.Path(__file__).parent.parent / "examples" / "photos.py"
    spec = importlib.util.spec_from_file_location("photos_example", module_path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["photos_example"] = module
    spec.loader.exec_module(module)
    return module


photos = _load_photos()


@pytest.fixture
def library(tmp_path):
    return tmp_path / "library"


@pytest.fixture
def pictures(tmp_path):
    """A small folder: two images, one video, one duplicate, one ignored file."""
    source = tmp_path / "pics"
    (source / "nested").mkdir(parents=True)

    (source / "a.jpg").write_bytes(_build_exif_jpeg("2021:01:02 03:04:05"))
    (source / "b.jpg").write_bytes(_build_exif_jpeg("2022:06:07 08:09:10"))
    # Byte-identical to a.jpg, so content-hash dedup should skip it.
    (source / "nested" / "a_copy.jpg").write_bytes((source / "a.jpg").read_bytes())

    video = source / "clip.mp4"
    video.write_bytes(b"\x00" * 32)
    stamp = datetime(2023, 5, 6, tzinfo=timezone.utc).timestamp()
    os.utime(video, (stamp, stamp))

    (source / "notes.txt").write_bytes(b"not media")
    return source


def _run(*argv):
    """Run the CLI, returning its exit status."""
    return photos.main([str(arg) for arg in argv])


def _first_id(library, capsys, *filters):
    """Return the abbreviated id of the first record matching ``filters``."""
    capsys.readouterr()  # drop output buffered by earlier commands
    _run("--library", library, "list", "--limit", "1", *filters)
    return capsys.readouterr().out.split()[0].rstrip("*")


class TestImport:
    def test_imports_media_and_skips_duplicates(self, library, pictures, capsys):
        assert _run("--library", library, "import", pictures) == 0
        out = capsys.readouterr().out
        # 2 images + 1 video; the copy is deduped and notes.txt is not media.
        assert "imported 3 file(s)" in out
        assert "library now holds 3 record(s)" in out

    def test_allow_duplicates_keeps_the_copy(self, library, pictures, capsys):
        _run("--library", library, "import", pictures, "--allow-duplicates")
        assert "imported 4 file(s)" in capsys.readouterr().out

    def test_no_recursive_skips_subfolders(self, library, pictures, capsys):
        _run("--library", library, "import", pictures, "--no-recursive")
        assert "imported 3 file(s)" in capsys.readouterr().out

    def test_rejects_a_missing_directory(self, library, tmp_path):
        with pytest.raises(SystemExit):
            _run("--library", library, "import", tmp_path / "nope")


class TestQuerying:
    @pytest.fixture(autouse=True)
    def imported(self, library, pictures):
        _run("--library", library, "import", pictures)

    def test_list_shows_every_record(self, library, capsys):
        assert _run("--library", library, "list") == 0
        assert "3 record(s)" in capsys.readouterr().out

    def test_filter_by_type(self, library, capsys):
        _run("--library", library, "list", "--type", "video")
        assert "1 record(s)" in capsys.readouterr().out

    def test_filter_by_date_range(self, library, capsys):
        _run("--library", library, "list", "--since", "2022-01-01")
        out = capsys.readouterr().out
        # b.jpg (2022) and clip.mp4 (2023), but not a.jpg (2021).
        assert "2 record(s)" in out

    def test_limit_reports_the_full_total(self, library, capsys):
        _run("--library", library, "list", "--limit", "1")
        assert "1 record(s) (of 3)" in capsys.readouterr().out

    def test_stats_summarizes_the_library(self, library, capsys):
        assert _run("--library", library, "stats") == 0
        assert "3 (2 image, 1 video)" in capsys.readouterr().out


class TestTagging:
    @pytest.fixture
    def record_id(self, library, pictures, capsys):
        _run("--library", library, "import", pictures)
        return _first_id(library, capsys, "--type", "video")

    def test_add_and_remove_labels(self, library, record_id, capsys):
        _run("--library", library, "tag", record_id, "--add", "x", "--add", "y")
        assert "labels: x, y" in capsys.readouterr().out

        _run("--library", library, "tag", record_id, "--remove", "x")
        assert "labels: y" in capsys.readouterr().out

    def test_adding_a_label_twice_does_not_duplicate_it(
        self, library, record_id, capsys
    ):
        _run("--library", library, "tag", record_id, "--add", "x")
        capsys.readouterr()
        _run("--library", library, "tag", record_id, "--add", "x")
        assert "labels: x\n" in capsys.readouterr().out

    def test_description_survives_a_later_label_edit(self, library, record_id, capsys):
        _run("--library", library, "tag", record_id, "--describe", "a clip")
        _run("--library", library, "tag", record_id, "--add", "x")
        capsys.readouterr()
        _run("--library", library, "show", record_id)
        assert "a clip" in capsys.readouterr().out

    def test_filter_by_label(self, library, record_id, capsys):
        _run("--library", library, "tag", record_id, "--add", "keep")
        capsys.readouterr()
        _run("--library", library, "list", "--label", "keep")
        assert "1 record(s)" in capsys.readouterr().out


class TestRecordOperations:
    @pytest.fixture
    def record_id(self, library, pictures, capsys):
        _run("--library", library, "import", pictures)
        return _first_id(library, capsys, "--type", "video")

    def test_show_prints_the_full_record(self, library, record_id, capsys):
        assert _run("--library", library, "show", record_id) == 0
        out = capsys.readouterr().out
        assert "type  video" in out
        assert "hash" in out

    def test_export_writes_the_file(self, library, record_id, tmp_path, capsys):
        destination = tmp_path / "out.mp4"
        assert _run("--library", library, "export", record_id, destination) == 0
        assert destination.read_bytes() == b"\x00" * 32

    def test_export_into_a_directory_names_the_file(self, library, record_id, tmp_path):
        destination = tmp_path / "outdir"
        destination.mkdir()
        _run("--library", library, "export", record_id, destination)
        assert len(list(destination.iterdir())) == 1

    def test_delete_removes_the_record(self, library, record_id, capsys):
        assert _run("--library", library, "delete", record_id) == 0
        capsys.readouterr()
        _run("--library", library, "list")
        assert "2 record(s)" in capsys.readouterr().out

    def test_reconcile_reports_a_clean_library(self, library, capsys):
        assert _run("--library", library, "reconcile") == 0
        out = capsys.readouterr().out
        assert "deleted 0 orphaned file(s)" in out
        assert "deleted 0 dangling row(s)" in out


class TestIdResolution:
    @pytest.fixture(autouse=True)
    def imported(self, library, pictures):
        _run("--library", library, "import", pictures)

    def test_accepts_an_abbreviated_id(self, library, capsys):
        short = _first_id(library, capsys, "--type", "video")
        assert len(short) == 8
        assert _run("--library", library, "show", short) == 0

    def test_rejects_an_unknown_id(self, library):
        with pytest.raises(SystemExit, match="no record matches"):
            _run("--library", library, "show", "ffffffffff")

    def test_rejects_an_ambiguous_prefix(self, library):
        # The empty prefix matches every record.
        with pytest.raises(SystemExit, match="ambiguous"):
            _run("--library", library, "show", "")


class TestDateParsing:
    def test_bare_date_becomes_utc_midnight(self):
        assert photos._parse_when("2024-03-04") == datetime(
            2024, 3, 4, tzinfo=timezone.utc
        )

    def test_naive_timestamp_is_treated_as_utc(self):
        assert photos._parse_when("2024-03-04T05:06:07") == datetime(
            2024, 3, 4, 5, 6, 7, tzinfo=timezone.utc
        )

    def test_aware_timestamp_is_converted_to_utc(self):
        assert photos._parse_when("2024-03-04T05:06:07+02:00") == datetime(
            2024, 3, 4, 3, 6, 7, tzinfo=timezone.utc
        )

    def test_rejects_nonsense(self):
        with pytest.raises(Exception):
            photos._parse_when("not-a-date")


class TestEmbedding:
    """The embedding path; needs a decoder, so it is skipped without Pillow."""

    @pytest.fixture(autouse=True)
    def require_pillow(self):
        pytest.importorskip("PIL", reason="embed requires Pillow")

    @pytest.fixture
    def colored(self, tmp_path):
        """Two reddish images and one blue one, so ranking is checkable."""
        from PIL import Image

        source = tmp_path / "colored"
        source.mkdir()
        for name, color in (
            ("red_a.png", (200, 30, 30)),
            ("red_b.png", (210, 45, 40)),
            ("blue.png", (30, 60, 200)),
        ):
            Image.new("RGB", (48, 48), color).save(source / name)
        return source

    def test_embed_then_search_ranks_by_color(self, library, colored, capsys):
        _run("--library", library, "import", colored)
        assert _run("--library", library, "embed") == 0
        assert "embedded 3 image(s), 0 skipped" in capsys.readouterr().out

        db = photos.open_library(library)
        try:
            by_hash = {
                path.name: photos._color_layout_embedding(path)
                for path in sorted(colored.iterdir())
            }
            assert all(len(vector) == 64 for vector in by_hash.values())

            records = db.query()
            red = min(
                records,
                key=lambda record: sum(
                    (a - b) ** 2 for a, b in zip(record.embedding, by_hash["red_a.png"])
                ),
            )
            neighbors = db.search_similar(
                red.embedding, model=photos.EMBEDDING_MODEL, limit=3
            )
            ranked = [n for n in neighbors if n.id != red.id]
            closest = ranked[0]
            assert sum(
                (a - b) ** 2 for a, b in zip(closest.embedding, by_hash["red_b.png"])
            ) < sum(
                (a - b) ** 2 for a, b in zip(closest.embedding, by_hash["blue.png"])
            )
        finally:
            db.close()

    def test_embed_is_idempotent(self, library, colored, capsys):
        _run("--library", library, "import", colored)
        _run("--library", library, "embed")
        capsys.readouterr()
        assert _run("--library", library, "embed") == 0
        assert "nothing to do" in capsys.readouterr().out

    def test_force_recomputes(self, library, colored, capsys):
        _run("--library", library, "import", colored)
        _run("--library", library, "embed")
        capsys.readouterr()
        _run("--library", library, "embed", "--force")
        assert "embedded 3 image(s)" in capsys.readouterr().out

    def test_similar_needs_an_embedding(self, library, colored, capsys):
        _run("--library", library, "import", colored)
        short = _first_id(library, capsys)
        with pytest.raises(SystemExit, match="has no embedding"):
            _run("--library", library, "similar", short)

    def test_embedding_is_unit_length(self, colored):
        vector = photos._color_layout_embedding(colored / "red_a.png")
        norm = sum(value * value for value in vector) ** 0.5
        assert norm == pytest.approx(1.0)


def test_l2_normalize_leaves_a_zero_vector_alone():
    assert photos._l2_normalize([0.0, 0.0]) == [0.0, 0.0]


def test_format_size_scales_units():
    assert photos._format_size(512) == "512 B"
    assert photos._format_size(2048) == "2.0 KB"
    assert photos._format_size(5 * 1024 * 1024) == "5.0 MB"

import sys
from pathlib import Path
import pytest

# Add root folder to sys.path so we can import script.build_doc
ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from script.build_doc import get_guide_names, temp_guides_setup


def test_get_guide_names(tmp_path: Path) -> None:
    """Test discovering guide names, ignoring index.md and filtering correctly."""
    guides_dir = tmp_path / "guides"
    guides_dir.mkdir()

    # Empty directory
    assert get_guide_names(guides_dir) == []

    # Non-existent directory
    assert get_guide_names(tmp_path / "does_not_exist") == []

    # Populate directory
    (guides_dir / "index.md").touch()
    (guides_dir / "recurrence.md").touch()
    (guides_dir / "timezone.md").touch()
    (guides_dir / "another-guide.md").touch()

    # Stems should be sorted alphabetically, excluding index.md
    assert get_guide_names(guides_dir) == [
        "another-guide",
        "recurrence",
        "timezone",
    ]


def test_temp_guides_setup(tmp_path: Path) -> None:
    """Test context manager setup and automatic clean up/restoration."""
    guides_src_dir = tmp_path / "guides"
    guides_src_dir.mkdir()
    (guides_src_dir / "index.md").touch()
    (guides_src_dir / "recurrence.md").touch()
    (guides_src_dir / "timezone.md").touch()

    temp_guides_dir = tmp_path / "ical" / "guides"
    temp_guides_dir.parent.mkdir()
    init_file = tmp_path / "ical" / "__init__.py"

    original_init_content = '__all__ = [\n    "alarm",\n    "calendar",\n]\n'
    init_file.write_text(original_init_content, encoding="utf-8")

    # Before entering context manager, temp guides folder does not exist
    assert not temp_guides_dir.exists()

    with temp_guides_setup(guides_src_dir, temp_guides_dir, init_file):
        # Temp folder exists
        assert temp_guides_dir.exists()

        # Wrapper files created
        assert (temp_guides_dir / "__init__.py").exists()
        assert (temp_guides_dir / "recurrence.py").exists()
        assert (temp_guides_dir / "timezone.py").exists()

        # Content of wrappers includes correct files
        wrapper_content = (temp_guides_dir / "recurrence.py").read_text()
        assert ".. include:: ../../guides/recurrence.md" in wrapper_content

        # ical/__init__.py is modified to include "guides"
        modified_init = init_file.read_text()
        assert '"guides"' in modified_init
        assert '__all__ = [\n    "guides",\n    "alarm",\n' in modified_init

    # After exiting context manager, temp folder is removed and init restored
    assert not temp_guides_dir.exists()
    assert init_file.read_text() == original_init_content


def test_temp_guides_setup_no_guides(tmp_path: Path) -> None:
    """Test context manager raises ValueError if no guides are present."""
    guides_src_dir = tmp_path / "guides"
    guides_src_dir.mkdir()
    temp_guides_dir = tmp_path / "ical" / "guides"
    init_file = tmp_path / "ical" / "__init__.py"

    with pytest.raises(ValueError, match="No guide markdown files found"):
        with temp_guides_setup(guides_src_dir, temp_guides_dir, init_file):
            pass

#!/usr/bin/env python3
"""Build script for generating ical documentation with embedded markdown guides."""

import shutil
import sys
from contextlib import contextmanager
from pathlib import Path
from typing import Generator
import pdoc

# Constants for project paths
ROOT_DIR = Path(__file__).resolve().parent.parent
ICAL_DIR = ROOT_DIR / "ical"
GUIDES_SRC_DIR = ROOT_DIR / "guides"
TEMP_GUIDES_DIR = ICAL_DIR / "guides"
OUTPUT_DIR = ROOT_DIR / "docs"
INIT_FILE = ICAL_DIR / "__init__.py"

# String templates for python wrappers
INIT_TEMPLATE = """\
\"\"\"
.. include:: ../../guides/index.md
\"\"\"

__all__ = {guide_names}
"""

WRAPPER_TEMPLATE = """\
\"\"\"
.. include:: ../../guides/{name}.md
\"\"\"
"""


def get_guide_names(guides_src_dir: Path) -> list[str]:
    """Find all guide markdown files (excluding the index page) and return their stems."""
    if not guides_src_dir.exists():
        return []
    md_files = sorted(guides_src_dir.glob("*.md"))
    return [f.stem for f in md_files if f.name != "index.md"]


@contextmanager
def temp_guides_setup(
    guides_src_dir: Path,
    temp_guides_dir: Path,
    init_file: Path,
) -> Generator[None, None, None]:
    """Context manager to temporarily set up python wrapper modules for guides.

    Note: We must place the temporary directories inside ical/ (rather than a system
    tempdir like /tmp/) so that pdoc's python import resolution parses them natively
    under the ical package hierarchy (e.g. ical.guides). We run this in a context
    manager to ensure the directory is safely cleaned up and original files restored.
    """
    guide_names = get_guide_names(guides_src_dir)
    if not guide_names:
        raise ValueError(f"No guide markdown files found in {guides_src_dir}")

    # Read original __init__.py content to restore it later
    original_init_content = ""
    if init_file.exists():
        original_init_content = init_file.read_text(encoding="utf-8")

    try:
        # Create temporary guides package directory inside ical/
        temp_guides_dir.mkdir(exist_ok=True)

        # Write __init__.py including guides/index.md and exposing the submodules
        init_content = INIT_TEMPLATE.format(guide_names=repr(guide_names))
        (temp_guides_dir / "__init__.py").write_text(init_content, encoding="utf-8")

        # Write wrapper modules for each markdown file
        for name in guide_names:
            wrapper_content = WRAPPER_TEMPLATE.format(name=name)
            (temp_guides_dir / f"{name}.py").write_text(
                wrapper_content, encoding="utf-8"
            )

        # Modify ical/__init__.py to temporarily include "guides" in __all__
        if original_init_content:
            modified_init_content = original_init_content.replace(
                "__all__ = [", '__all__ = [\n    "guides",'
            )
            init_file.write_text(modified_init_content, encoding="utf-8")

        yield

    finally:
        # Always clean up the temporary directory and restore __init__.py
        if temp_guides_dir.exists():
            shutil.rmtree(temp_guides_dir)
        if original_init_content and init_file.exists():
            init_file.write_text(original_init_content, encoding="utf-8")


def build_docs() -> None:
    """Build the documentation using the pdoc library."""
    pdoc.render.configure(docformat="restructuredtext")
    pdoc.pdoc(ICAL_DIR, output_directory=OUTPUT_DIR)


def main() -> None:
    if not GUIDES_SRC_DIR.exists() or not (GUIDES_SRC_DIR / "index.md").exists():
        print("Error: guides/ directory or index.md not found.", file=sys.stderr)
        sys.exit(1)

    try:
        with temp_guides_setup(GUIDES_SRC_DIR, TEMP_GUIDES_DIR, INIT_FILE):
            print("Building documentation using pdoc library...")
            build_docs()
            print(f"Documentation generated successfully at: {OUTPUT_DIR}")
    except Exception as e:
        print(f"Error building documentation: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()

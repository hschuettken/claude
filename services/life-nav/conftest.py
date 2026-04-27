"""Test configuration — creates the `life_nav` module alias.

The service directory is named `life-nav` (hyphenated) which is not importable
as a Python module name. This conftest patches sys.modules so that
`import life_nav` resolves to the service directory.
"""
from __future__ import annotations

import importlib.util
import pathlib
import sys

SVC_DIR = pathlib.Path(__file__).parent  # services/life-nav/

if str(SVC_DIR) not in sys.path:
    sys.path.insert(0, str(SVC_DIR))

if "life_nav" not in sys.modules:
    init_file = SVC_DIR / "__init__.py"
    spec = importlib.util.spec_from_file_location(
        "life_nav",
        str(init_file),
        submodule_search_locations=[str(SVC_DIR)],
    )
    pkg = importlib.util.module_from_spec(spec)
    pkg.__file__ = str(init_file)
    pkg.__path__ = [str(SVC_DIR)]
    pkg.__package__ = "life_nav"
    pkg.__name__ = "life_nav"
    sys.modules["life_nav"] = pkg

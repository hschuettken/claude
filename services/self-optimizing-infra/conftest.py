"""Test configuration — creates the `self_optimizing_infra` module alias.

The service directory is named `self-optimizing-infra` (hyphenated) which
is not importable as a Python module name. This conftest patches sys.modules
so that `import self_optimizing_infra` resolves to the service directory.
"""
from __future__ import annotations

import importlib.util
import pathlib
import sys

SVC_DIR = pathlib.Path(__file__).parent  # services/self-optimizing-infra/

if str(SVC_DIR) not in sys.path:
    sys.path.insert(0, str(SVC_DIR))

if "self_optimizing_infra" not in sys.modules:
    init_file = SVC_DIR / "__init__.py"
    spec = importlib.util.spec_from_file_location(
        "self_optimizing_infra",
        str(init_file),
        submodule_search_locations=[str(SVC_DIR)],
    )
    pkg = importlib.util.module_from_spec(spec)
    pkg.__file__ = str(init_file)
    pkg.__path__ = [str(SVC_DIR)]
    pkg.__package__ = "self_optimizing_infra"
    pkg.__name__ = "self_optimizing_infra"
    sys.modules["self_optimizing_infra"] = pkg

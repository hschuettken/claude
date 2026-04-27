"""Test configuration — creates the `cognitive_layer` module alias.

The service directory is named `cognitive-layer` (hyphen) which is not
importable as a Python module name.  This conftest patches sys.modules so
that `import cognitive_layer` resolves to the service directory.
"""
from __future__ import annotations

import importlib.util
import pathlib
import sys
import types

SVC_DIR = pathlib.Path(__file__).parent  # services/cognitive-layer/

# Make sure the service directory itself is on the path so that
# the importlib machinery can find sub-modules by filename.
if str(SVC_DIR) not in sys.path:
    sys.path.insert(0, str(SVC_DIR))

# Bootstrap `cognitive_layer` package in sys.modules so that
# `from cognitive_layer.models import ...` works in tests.
if "cognitive_layer" not in sys.modules:
    init_file = SVC_DIR / "__init__.py"
    spec = importlib.util.spec_from_file_location(
        "cognitive_layer",
        str(init_file),
        submodule_search_locations=[str(SVC_DIR)],
    )
    pkg = importlib.util.module_from_spec(spec)
    pkg.__file__ = str(init_file)
    pkg.__path__ = [str(SVC_DIR)]
    pkg.__package__ = "cognitive_layer"
    pkg.__name__ = "cognitive_layer"
    sys.modules["cognitive_layer"] = pkg
    if spec.loader:
        spec.loader.exec_module(pkg)

"""Test configuration — creates the `digital_twin` module alias.

The service directory is named `digital-twin` (hyphen) which is not
importable as a Python module name. This conftest patches sys.modules so
that `import digital_twin` resolves to the service directory.
"""
from __future__ import annotations

import importlib.util
import pathlib
import sys

SVC_DIR = pathlib.Path(__file__).parent  # services/digital-twin/

if str(SVC_DIR) not in sys.path:
    sys.path.insert(0, str(SVC_DIR))

if "digital_twin" not in sys.modules:
    init_file = SVC_DIR / "__init__.py"
    spec = importlib.util.spec_from_file_location(
        "digital_twin",
        str(init_file),
        submodule_search_locations=[str(SVC_DIR)],
    )
    pkg = importlib.util.module_from_spec(spec)
    pkg.__file__ = str(init_file)
    pkg.__path__ = [str(SVC_DIR)]
    pkg.__package__ = "digital_twin"
    pkg.__name__ = "digital_twin"
    sys.modules["digital_twin"] = pkg
    if spec.loader:
        spec.loader.exec_module(pkg)

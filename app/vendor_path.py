"""
Puts vendor/wealth_core on sys.path so its internal absolute imports
(`from facts_layer import ...`, `from tax_engine import ...`, etc.) resolve
exactly as they do inside wealth-core's own test suite. We do this instead of
nesting wealth-core under a package name, because its modules import each
other as top-level packages, not as a sub-package — renaming them would mean
editing wealth-core, which is out of scope.
"""
import os
import sys

VENDOR_ROOT = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "vendor",
    "wealth_core",
)


def ensure_on_path() -> None:
    if VENDOR_ROOT not in sys.path:
        sys.path.insert(0, VENDOR_ROOT)


ensure_on_path()

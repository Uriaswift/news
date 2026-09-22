"""Run the suite and expose failures as GitHub annotations."""
import sys
import unittest
from pathlib import Path

suite = unittest.defaultTestLoader.discover(str(Path(__file__).parent))
result = unittest.TextTestRunner(verbosity=2).run(suite)
for test, traceback in result.failures + result.errors:
    message = traceback.replace('%', '%25').replace('\r', '%0D').replace('\n', '%0A')
    print(f'::error title={test.id()}::{message}', flush=True)
raise SystemExit(0 if result.wasSuccessful() else 1)

"""Smoke test used by the one-click installer."""

import openpyxl  # noqa: F401 - verifies the required package is installed

from runner import run_code


for attempt in range(3):
    result = run_code("print(1 + 2)", "")
    if result["status"] == "OK" and result["stdout"] == "3\n":
        print("Docker code execution OK")
        break
    if result["status"] != "TIME_LIMIT" or attempt == 2:
        raise SystemExit(f"Docker code execution failed: {result}")
    print("Docker startup was slow; retrying...")

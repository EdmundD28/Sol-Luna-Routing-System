from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
from collections.abc import Mapping


ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(ROOT))


def plain(value):
    if isinstance(value, Mapping):
        return {key: plain(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [plain(item) for item in value]
    return value


def run_cli(*args: str, stdin: bytes = b"") -> subprocess.CompletedProcess[bytes]:
    environment = os.environ.copy()
    environment["PYTHONPATH"] = str(ROOT) + os.pathsep + environment.get("PYTHONPATH", "")
    return subprocess.run(
        [sys.executable, "-B", "-m", "opsworkbench.cli", *args],
        cwd=ROOT,
        input=stdin,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=environment,
        check=False,
    )

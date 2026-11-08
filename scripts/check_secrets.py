"""Fail on new credentials without printing their values or modifying the baseline."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

from detect_secrets import SecretsCollection
from detect_secrets.settings import transient_settings


def main() -> int:
    baseline = json.loads(Path(".secrets.baseline").read_text())
    approved = {
        (filename, finding["hashed_secret"], finding["type"])
        for filename, findings in baseline.get("results", {}).items()
        for finding in findings
    }
    paths = subprocess.check_output(
        ["git", "ls-files", "--cached", "--others", "--exclude-standard", "-z"], text=True
    ).split("\0")
    secrets = SecretsCollection()
    with transient_settings(baseline):
        for filename in sorted(set(paths)):
            path = Path(filename)
            if path.is_file() and path.suffix not in {".lock", ".parquet", ".ipynb"}:
                secrets.scan_file(filename)
    findings = [
        f"{filename}:{finding['line_number']}: {finding['type']}"
        for filename, items in secrets.json().items()
        for finding in items
        if (filename, finding["hashed_secret"], finding["type"]) not in approved
    ]
    for finding in findings:
        print(finding)
    print(f"Secret scan: {len(findings)} new finding(s)")
    return int(bool(findings))


if __name__ == "__main__":
    raise SystemExit(main())

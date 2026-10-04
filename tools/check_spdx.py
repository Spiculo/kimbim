# SPDX-License-Identifier: GPL-3.0-or-later
"""Fail if a source file lacks the SPDX header in its first 5 lines."""
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
DIRS = ["python", "crates", "tests", "tools", "app"]
EXTS = {".py", ".rs", ".cpp", ".h"}
TAG = "SPDX-License-Identifier: GPL-3.0-or-later"
SKIP_PARTS = {"target", "__pycache__", "files", "build"}


def main() -> int:
    missing = []
    for d in DIRS:
        for p in (ROOT / d).rglob("*"):
            if p.suffix in EXTS and not SKIP_PARTS & set(p.parts):
                head = p.read_text(encoding="utf-8", errors="replace").splitlines()[:5]
                if not any(TAG in line for line in head):
                    missing.append(p.relative_to(ROOT))
    for m in missing:
        print(f"missing SPDX header: {m}")
    print("SPDX OK" if not missing else f"{len(missing)} file(s) missing SPDX header")
    return 1 if missing else 0


if __name__ == "__main__":
    sys.exit(main())

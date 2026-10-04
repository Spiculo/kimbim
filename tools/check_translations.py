# SPDX-License-Identifier: GPL-3.0-or-later
"""Fail if the Spanish UI translation has unfinished or empty entries (D29: English + Spanish)."""
import pathlib
import sys
import xml.etree.ElementTree as ET

ROOT = pathlib.Path(__file__).resolve().parent.parent
TS = ROOT / "app" / "translations" / "kimcad_es.ts"


def main() -> int:
    problems = []
    for ctx in ET.parse(TS).getroot().iter("context"):
        name = ctx.findtext("name")
        for msg in ctx.iter("message"):
            src = msg.findtext("source")
            tr = msg.find("translation")
            forms = [f.text for f in tr.findall("numerusform")] if tr is not None else []
            empty = not any((f or "").strip() for f in forms) if msg.get("numerus") == "yes" else not (tr is not None and (tr.text or "").strip())
            if tr is None or tr.get("type") in ("unfinished", "obsolete", "vanished") or empty:
                if tr is not None and tr.get("type") in ("obsolete", "vanished"):
                    continue  # strings no longer in the code are ignored
                problems.append(f"{name}: {src!r}")
    for p in problems:
        print(f"untranslated (es): {p}")
    print("translations OK" if not problems else f"{len(problems)} untranslated Spanish string(s)")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())

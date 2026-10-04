# SPDX-License-Identifier: GPL-3.0-or-later
"""Download the test corpus (buildingSMART sample files) into tests/corpus/files/.

Files are not committed (see .gitignore). Re-running skips files already present.
Usage: python spikes/corpus/fetch.py
"""
import json
import pathlib
import urllib.parse
import urllib.request

HERE = pathlib.Path(__file__).parent
OUT = HERE / "files"

SOURCES = [
    {
        # Official buildingSMART certification/sample files: IFC2X3, IFC4, IFC4X3
        "name": "bsi",
        "repo": "buildingSMART/Sample-Test-Files",
        "raw": "https://raw.githubusercontent.com/buildingSMART/Sample-Test-Files/main/",
        "include": lambda p: True,
    },
    {
        # Community files (Git LFS, served from media.githubusercontent.com)
        "name": "community",
        "repo": "buildingsmart-community/Community-Sample-Test-Files",
        "raw": "https://media.githubusercontent.com/media/buildingsmart-community/Community-Sample-Test-Files/main/",
        "include": lambda p: (
            "ISO Spec archive" in p
            or p.endswith("Duplex_A_20110907.ifc")
            or p.endswith("Clinic_Architectural.ifc")
            or p.endswith("Design model IFC/IFC Schependomlaan.ifc")
            or p.endswith("1807_EP_AR_v18.ifc")
        ),
    },
]


def tree(repo):
    url = f"https://api.github.com/repos/{repo}/git/trees/main?recursive=1"
    with urllib.request.urlopen(url) as r:
        return json.load(r)["tree"]


def main():
    for src in SOURCES:
        paths = [
            t["path"]
            for t in tree(src["repo"])
            if t["type"] == "blob" and t["path"].lower().endswith(".ifc") and src["include"](t["path"])
        ]
        for p in paths:
            dest = OUT / src["name"] / p
            if dest.exists() and dest.stat().st_size > 1000:
                continue
            dest.parent.mkdir(parents=True, exist_ok=True)
            url = src["raw"] + urllib.parse.quote(p)
            print("GET", src["name"], p)
            urllib.request.urlretrieve(url, dest)
    files = sorted(OUT.rglob("*.[iI][fF][cC]"))
    print(f"{len(files)} files, {sum(f.stat().st_size for f in files) / 1e6:.1f} MB")


if __name__ == "__main__":
    main()

<!-- SPDX-License-Identifier: GPL-3.0-or-later -->
# ifcmerge test fixtures

These IFC files are copied unchanged from [ifcmerge](https://github.com/brunopostle/ifcmerge) (`t/fixtures/`),
Copyright (C) Bruno Postle, licensed GPL-3.0-or-later, the same license as KIMCAD. They were made with
Bonsai (a Native IFC editor) from `base_simple_room.ifc`; each file is one fork (a window added, a wall
deleted, a name changed...). `tests/python/test_merge.py` ports ifcmerge's merge cases (`t/003.ifc.t`,
`t/005.float_normalisation.t`) to KIMCAD's record merge (Slice 21, R4).

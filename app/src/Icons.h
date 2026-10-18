// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once

#include <QIcon>
#include <QString>

namespace kimcad {

// A small line icon for an IFC class (walls, slabs, doors... a generic one for anything else).
QIcon iconFor(const QString& ifcClass);

// D90: a line icon from :/icons/<name>.svg drawn in the palette's text colour (its "currentColor"),
// so it reads on a light or a dark theme and follows a theme change; greyed when disabled.
QIcon themedIcon(const QString& name);

// D90: a stand-in for an action without an icon: its first letter in a rounded box, themed the same way.
QIcon letterIcon(const QString& label);

} // namespace kimcad

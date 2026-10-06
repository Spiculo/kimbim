// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once

#include <QIcon>
#include <QString>

namespace kimcad {

// A small line icon for an IFC class (walls, slabs, doors... a generic one for anything else).
QIcon iconFor(const QString& ifcClass);

} // namespace kimcad

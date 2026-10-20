// SPDX-License-Identifier: GPL-3.0-or-later
// D88: stairs, ramps and railings in the main window (doc 14 §6). The Stair tool (T) draws a stair or
// a ramp: straight, L or U by its start and direction (two clicks), or by sketch (the walking line as
// a polyline, Enter to finish); the Railing tool puts railings on both sides of a clicked stair or ramp,
// or along a clicked path. The shapes are python/kimbim/stairs.py's, one undo step each. Plan views get
// the stairs' symbols (walking line, break line, the part above the cut dashed, UP) as plan-only
// annotations named after the stair, and a click on a flight, a landing or the symbol selects the stair.
#include <QComboBox>
#include <QDoubleSpinBox>
#include <QJsonArray>
#include <QJsonDocument>
#include <QLocale>

#include <cmath>

#include "DraftTool.h"
#include "LevelsBar.h"
#include "MainWindow.h"
#include "StatusStrip.h"
#include "ToolOptionsBar.h"
#include "TwoPointTool.h"
#include "Viewport.h"

namespace kimbim {

namespace {

QString compactJson(const QJsonValue& v)
{
    return QString::fromUtf8(v.isArray() ? QJsonDocument(v.toArray()).toJson(QJsonDocument::Compact)
                                         : QJsonDocument(v.toObject()).toJson(QJsonDocument::Compact));
}

QString num(double v)
{
    return QString::number(v, 'g', 17);
}

QPointF point(const QJsonValue& v)
{
    const QJsonArray a = v.toArray();
    return QPointF(a.at(0).toDouble(), a.at(1).toDouble());
}

QJsonArray points(const QVector<QPointF>& pts)
{
    QJsonArray out;
    for (const QPointF& p : pts)
        out.append(QJsonArray{p.x(), p.y()});
    return out;
}

QDoubleSpinBox* metres(QWidget* parent, const char* name, double lo, double hi, double value, const QString& prefix,
    const QString& tip, const QString& suffix = QStringLiteral(" m"), int decimals = 3)
{
    auto* box = new QDoubleSpinBox(parent);
    box->setObjectName(QLatin1String(name));
    box->setRange(lo, hi);
    box->setDecimals(decimals);
    box->setSingleStep(decimals > 2 ? 0.01 : 0.5);
    box->setValue(value);
    box->setPrefix(prefix);
    box->setSuffix(suffix);
    box->setToolTip(tip);
    return box;
}

} // namespace

// The stair_symbols listing as plan-only annotations: the solid lines (with UP / the slope at the
// label point) and the dashed lines above the cut, each named "<stair>~symbol" / "<stair>~above".
void readStairSymbols(const QJsonObject& data, QVector<Viewport::Annotation>* list)
{
    for (const auto& v : data.value("symbols").toArray()) {
        const QJsonObject o = v.toObject();
        const QString guid = o.value("guid").toString();
        for (const char* part : {"solid", "dashed"}) {
            Viewport::Annotation a;
            a.guid = guid + (part[0] == 's' ? QStringLiteral("~symbol") : QStringLiteral("~above"));
            a.kind = QStringLiteral("polyline");
            for (const auto& c : o.value(QLatin1String(part)).toArray()) {
                QVector<QPointF> curve;
                for (const auto& p : c.toArray())
                    curve << point(p);
                a.curves << curve;
            }
            if (a.curves.isEmpty())
                continue;
            a.points << a.curves.first().first();
            if (part[0] == 'd')
                a.dash = {1.2, 0.8}; // mm on paper
            else if (const QJsonArray labels = o.value("labels").toArray(); !labels.isEmpty()) {
                a.labelAt = point(labels.first().toObject().value("at"));
                a.text = labels.first().toObject().value("text").toString();
            }
            *list << a;
        }
    }
}

void MainWindow::setupStairTools(ToolOptionsBar* bar)
{
    m_pathTool = new DraftTool(this);
    m_pathTool->setMode(DraftTool::Mode::Polyline);
    m_stairKind = new QComboBox(bar);
    m_stairKind->setObjectName(QStringLiteral("stairKind"));
    m_stairKind->addItem(tr("Stair"), QStringLiteral("stair"));
    m_stairKind->addItem(tr("Ramp"), QStringLiteral("ramp"));
    m_stairKind->setToolTip(tr("Draw a stair or a ramp"));
    m_stairShape = new QComboBox(bar);
    m_stairShape->setObjectName(QStringLiteral("stairShape"));
    m_stairShape->setToolTip(tr("Shape: straight, L (quarter landing), U (half landing) or by sketch (click the walking line)"));
    m_stairTurn = new QComboBox(bar);
    m_stairTurn->setObjectName(QStringLiteral("stairTurn"));
    m_stairTurn->addItem(tr("Turns left"), QStringLiteral("left"));
    m_stairTurn->addItem(tr("Turns right"), QStringLiteral("right"));
    m_stairTurn->setToolTip(tr("Which way an L or U stair turns"));
    m_stairWidth = metres(bar, "stairWidth", 0.4, 10.0, 1.0, tr("Width "), tr("Stair or ramp width"));
    m_stairTread = metres(bar, "stairTread", 0.15, 0.6, 0.28, tr("Tread "), tr("Tread depth (going)"));
    m_stairRiser = metres(bar, "stairRiser", 0.1, 0.25, 0.175, tr("Riser "),
        tr("Target riser height: the riser count comes from the height to the next level"));
    m_stairLanding = metres(bar, "stairLanding", 0.0, 10.0, 0.0, tr("Landing "), tr("Landing depth (0: the stair's width)"));
    m_stairLanding->setSpecialValueText(tr("Landing: as wide"));
    m_rampSlope = metres(bar, "rampSlope", 0.5, 50.0, 8.0, tr("Slope "), tr("Ramp slope (warning above the project's limit, 1:12)"),
        QStringLiteral(" %"), 1);
    m_rampRise = metres(bar, "rampRise", 0.05, 20.0, 0.5, tr("Rise "), tr("How high the ramp goes"));
    m_railingMode = new QComboBox(bar);
    m_railingMode->setObjectName(QStringLiteral("railingMode"));
    m_railingMode->addItem(tr("On a stair or ramp"), QStringLiteral("stair"));
    m_railingMode->addItem(tr("By path"), QStringLiteral("path"));
    m_railingMode->setToolTip(tr("Click a stair or ramp for railings on both its sides, or click a path"));
    m_railingHeight = metres(bar, "railingHeight", 0.3, 3.0, 0.9, tr("Height "), tr("Railing height"));
    for (QWidget* w : std::initializer_list<QWidget*>{m_stairKind, m_stairShape, m_stairTurn, m_stairWidth, m_stairTread,
             m_stairRiser, m_stairLanding, m_rampSlope, m_rampRise, m_railingMode, m_railingHeight}) {
        w->setVisible(false);
        bar->addField(w);
    }
    auto changed = [this] {
        if (m_tool == Tool::Stair || m_tool == Tool::Railing) {
            startStairTool(m_tool);
            updateToolPreview();
        }
    };
    connect(m_stairKind, &QComboBox::currentIndexChanged, this, changed);
    connect(m_stairShape, &QComboBox::currentIndexChanged, this, changed);
    connect(m_railingMode, &QComboBox::currentIndexChanged, this, [this] {
        m_railingHeight->setValue(m_railingMode->currentData().toString() == QLatin1String("path") ? 1.1 : 0.9);
        if (m_tool == Tool::Railing)
            startStairTool(m_tool);
    });
    for (QDoubleSpinBox* b : {m_stairWidth, m_stairTread, m_stairRiser, m_stairLanding, m_rampSlope, m_rampRise})
        connect(b, &QDoubleSpinBox::valueChanged, this, [this] { updateToolPreview(); });
    connect(m_stairTurn, &QComboBox::currentIndexChanged, this, [this] { updateToolPreview(); });
    connect(m_pathTool, &DraftTool::previewChanged, this, &MainWindow::updateToolPreview);
    connect(m_pathTool, &DraftTool::shapeFinished, this, [this](const QString&, const QVector<QPointF>& pts, bool) {
        if (m_tool == Tool::Railing)
            createRailing(pts);
        else
            createStairSketch(pts);
    });
}

void MainWindow::setStairShape(const QString& kind, const QString& shape, const QString& turn)
{
    m_stairKind->setCurrentIndex(std::max(0, m_stairKind->findData(kind)));
    startStairTool(m_tool);
    m_stairShape->setCurrentIndex(std::max(0, m_stairShape->findData(shape)));
    m_stairTurn->setCurrentIndex(std::max(0, m_stairTurn->findData(turn)));
}

void MainWindow::startStairTool(Tool tool)
{
    const bool stair = tool == Tool::Stair;
    const bool ramp = stair && m_stairKind->currentData().toString() == QLatin1String("ramp");
    if (stair) { // ramps are straight or L
        const QString current = m_stairShape->currentData().toString();
        const QSignalBlocker block(m_stairShape);
        m_stairShape->clear();
        m_stairShape->addItem(tr("Straight"), QStringLiteral("straight"));
        m_stairShape->addItem(tr("L-shaped"), QStringLiteral("L"));
        if (!ramp) {
            m_stairShape->addItem(tr("U-shaped"), QStringLiteral("U"));
            m_stairShape->addItem(tr("By sketch"), QStringLiteral("sketch"));
        }
        m_stairShape->setCurrentIndex(std::max(0, m_stairShape->findData(current)));
    }
    const QString shape = m_stairShape->currentData().toString();
    m_stairKind->setVisible(stair);
    m_stairShape->setVisible(stair);
    m_stairTurn->setVisible(stair && (shape == QLatin1String("L") || shape == QLatin1String("U")));
    m_stairWidth->setVisible(stair);
    m_stairTread->setVisible(stair && !ramp);
    m_stairRiser->setVisible(stair && !ramp);
    m_stairLanding->setVisible(stair && shape != QLatin1String("straight") && shape != QLatin1String("sketch"));
    m_rampSlope->setVisible(ramp);
    m_rampRise->setVisible(ramp);
    m_railingMode->setVisible(tool == Tool::Railing);
    m_railingHeight->setVisible(tool == Tool::Railing);
    m_pathTool->cancel();
    if (tool == Tool::Railing)
        m_status->showMessage(m_railingMode->currentData().toString() == QLatin1String("path")
                ? tr("Railing: click the path's points; Enter or double click to finish")
                : tr("Railing: click a stair or ramp to put railings on its sides"));
    else if (stair)
        m_status->showMessage(shape == QLatin1String("sketch")
                ? tr("Stair by sketch: click the walking line's points (landings at the corners); Enter to finish")
                : ramp ? tr("Ramp: click where it starts, then the direction it goes up")
                       : tr("Stair: click where it starts, then the direction it climbs"));
}

QJsonObject MainWindow::stairOptions() const
{
    QJsonObject o{{"shape", m_stairShape->currentData().toString()}, {"turn", m_stairTurn->currentData().toString()},
        {"landing", m_stairLanding->value()}};
    if (m_stairKind->currentData().toString() == QLatin1String("ramp"))
        o.insert("slope", m_rampSlope->value());
    else {
        o.insert("tread", m_stairTread->value());
        o.insert("riser", m_stairRiser->value());
    }
    return o;
}

bool MainWindow::stairPointer(QPointF p, double tolerance, Qt::KeyboardModifiers mods, bool click)
{
    // The polyline cases (a stair by sketch, a railing by path); the rest is the two-point tool's.
    const bool path = m_tool == Tool::Railing ? m_railingMode->currentData().toString() == QLatin1String("path")
                                              : m_stairShape->currentData().toString() == QLatin1String("sketch");
    if (m_tool == Tool::Railing && !path) {
        if (click)
            railStairAt(p);
        return true;
    }
    if (!path)
        return false;
    m_pathTool->setTolerance(tolerance);
    m_pathTool->setOrtho(mods & Qt::ShiftModifier);
    if (click)
        m_pathTool->click(p);
    else
        m_pathTool->move(p);
    return true;
}

void MainWindow::updateStairPreview()
{
    const double z = m_levels ? m_levels->activeElevation() : 0.0;
    QVector<Viewport::PreviewBox> boxes;
    if (m_tool == Tool::Railing) {
        QVector<QPointF> pts = m_pathTool->points();
        if (const auto h = m_pathTool->hover(); h && !pts.isEmpty())
            pts << *h;
        for (int i = 0; i + 1 < pts.size(); ++i)
            boxes.push_back({pts[i], pts[i + 1], 0.05, z, z + m_railingHeight->value()});
        m_viewport->setPreviewBoxes(boxes);
        return;
    }
    const bool ramp = m_stairKind->currentData().toString() == QLatin1String("ramp");
    QJsonObject o = stairOptions();
    QPointF start, towards;
    if (o.value("shape").toString() == QLatin1String("sketch")) {
        QVector<QPointF> pts = m_pathTool->points();
        if (const auto h = m_pathTool->hover(); h && !pts.isEmpty())
            pts << *h;
        if (pts.size() < 2) {
            m_viewport->setPreviewBoxes(boxes);
            return;
        }
        o.insert("points", points(pts));
    } else if (const auto seg = m_twoPointTool->preview()) {
        start = seg->first;
        towards = seg->second;
    } else {
        m_viewport->setPreviewBoxes(boxes);
        return;
    }
    const QPointF d = towards - start;
    const double height = ramp ? m_rampRise->value() : heightToNextLevel();
    const QJsonObject r = bridge("stair_preview", {ramp ? QStringLiteral("ramp") : QStringLiteral("stair"), num(start.x()),
        num(start.y()), num(std::atan2(d.y(), d.x())), num(m_stairWidth->value()), num(height), compactJson(o)});
    for (const auto& v : r.value("flights").toArray()) {
        const QJsonObject f = v.toObject();
        boxes.push_back({point(f.value("a")), point(f.value("b")), m_stairWidth->value(), z + f.value("z0").toDouble(),
            z + f.value("z1").toDouble()});
    }
    for (const auto& v : r.value("landings").toArray()) {
        const QJsonObject l = v.toObject();
        QVector<QPointF> poly;
        for (const auto& p : l.value("points").toArray())
            poly << point(p);
        const double top = z + l.value("z").toDouble();
        for (int i = 0; i < poly.size(); ++i)
            boxes.push_back({poly[i], poly[(i + 1) % poly.size()], 0.04, top - 0.2, top});
    }
    m_viewport->setPreviewBoxes(boxes);
    if (r.value("ok").toBool()) {
        QString text = ramp ? tr("Ramp: %1 long").arg(formatLength(r.value("run").toDouble()))
                            : tr("Stair: %1 risers of %2, tread %3").arg(r.value("risers").toInt())
                                  .arg(formatLength(r.value("riser").toDouble()), formatLength(r.value("tread").toDouble()));
        const QJsonArray warnings = r.value("warnings").toArray();
        if (!warnings.isEmpty())
            text += QStringLiteral("  ·  ") + tr("Warning: %1").arg(warnings.first().toString());
        m_status->showMessage(text);
    } else {
        m_status->showMessage(r.value("error").toString());
    }
}

bool MainWindow::createStair(QPointF start, QPointF towards)
{
    const QPointF d = towards - start;
    if (std::hypot(d.x(), d.y()) < 1e-6)
        return false;
    const bool ramp = m_stairKind && m_stairKind->currentData().toString() == QLatin1String("ramp");
    const QJsonObject o = m_stairShape ? stairOptions() : QJsonObject();
    const QJsonObject r = bridge(ramp ? "create_ramp" : "create_stair", {m_levels->activeStorey(), num(start.x()), num(start.y()),
        num(std::atan2(d.y(), d.x())), num(m_stairWidth ? m_stairWidth->value() : 1.0),
        num(ramp ? m_rampRise->value() : heightToNextLevel()), compactJson(o)});
    if (!r.value("ok").toBool()) {
        m_status->showMessage((ramp ? tr("Could not create the ramp: %1") : tr("Could not create the stair: %1"))
                                  .arg(r.value("error").toString()));
        return false;
    }
    afterEdit(r);
    QString text = ramp ? tr("Ramp: %1 long").arg(formatLength(r.value("run").toDouble()))
                        : tr("Stair: %1 risers of %2 m").arg(r.value("risers").toInt())
                              .arg(QLocale().toString(r.value("riser").toDouble(), 'f', 3));
    const QJsonArray warnings = r.value("warnings").toArray();
    if (!warnings.isEmpty())
        text += QStringLiteral("  ·  ") + tr("Warning: %1").arg(warnings.first().toString());
    m_status->showMessage(text);
    return true;
}

bool MainWindow::createStairSketch(const QVector<QPointF>& walkingLine)
{
    QJsonObject o = stairOptions();
    o.insert("shape", QStringLiteral("sketch"));
    o.insert("points", points(walkingLine));
    const QJsonObject r = bridge("create_stair", {m_levels->activeStorey(), num(0), num(0), num(0),
        num(m_stairWidth->value()), num(heightToNextLevel()), compactJson(o)});
    if (!r.value("ok").toBool()) {
        m_status->showMessage(tr("Could not create the stair: %1").arg(r.value("error").toString()));
        return false;
    }
    afterEdit(r);
    m_status->showMessage(tr("Stair: %1 risers of %2 m").arg(r.value("risers").toInt())
                              .arg(QLocale().toString(r.value("riser").toDouble(), 'f', 3)));
    return true;
}

bool MainWindow::railStairAt(QPointF p)
{
    const QString stair = bridge("stair_at", {m_levels->activeStorey(), num(p.x()), num(p.y())}).value("guid").toString();
    if (stair.isEmpty()) {
        m_status->showMessage(tr("Railing: there is no stair or ramp there"));
        return false;
    }
    const QJsonObject r = bridge("add_stair_railings", {stair, num(m_railingHeight->value()), QStringLiteral("both")});
    if (!r.value("ok").toBool()) {
        m_status->showMessage(tr("Could not add railings: %1").arg(r.value("error").toString()));
        return false;
    }
    afterEdit(r);
    m_status->showMessage(tr("%n railing(s) added; they follow the stair", nullptr, int(r.value("guids").toArray().size())));
    return true;
}

bool MainWindow::createRailing(const QVector<QPointF>& path)
{
    const QJsonObject r = bridge("create_railing", {m_levels->activeStorey(), compactJson(points(path)), num(m_railingHeight->value())});
    if (!r.value("ok").toBool()) {
        m_status->showMessage(tr("Could not create the railing: %1").arg(r.value("error").toString()));
        return false;
    }
    afterEdit(r);
    m_status->showMessage(tr("Railing: %n post(s)", nullptr, r.value("posts").toInt()));
    return true;
}

QJsonObject MainWindow::stairSymbolData()
{
    m_assemblyOf.clear();
    m_assemblyMembers.clear();
    m_assemblyType.clear();
    const QJsonObject assemblies = bridge("assembly_members").value("assemblies").toObject();
    for (auto it = assemblies.constBegin(); it != assemblies.constEnd(); ++it) {
        const QJsonObject o = it.value().toObject();
        QStringList members;
        for (const auto& g : o.value("parts").toArray())
            members << g.toString();
        for (const QString& m : std::as_const(members))
            m_assemblyOf.insert(m, it.key());
        m_assemblyOf.insert(it.key() + QStringLiteral("~symbol"), it.key());
        m_assemblyOf.insert(it.key() + QStringLiteral("~above"), it.key());
        m_assemblyMembers.insert(it.key(), members);
        m_assemblyType.insert(it.key(), o.value("type").toString());
    }
    if (m_assemblyType.isEmpty())
        return {};
    const double cut = planCutHeight();
    return bridge("stair_symbols", {m_levels->activeStorey(), num(cut)});
}

void MainWindow::expandAssemblies(QStringList& guids) const
{
    // A flight, a landing or the plan symbol stands for its stair: the stair and all its parts.
    QStringList out;
    for (const QString& g : std::as_const(guids)) {
        const QString whole = m_assemblyOf.value(g, m_assemblyMembers.contains(g) ? g : QString());
        if (whole.isEmpty()) {
            if (!out.contains(g))
                out << g;
            continue;
        }
        for (const QString& m : QStringList{whole} + m_assemblyMembers.value(whole))
            if (!out.contains(m))
                out << m;
    }
    guids = out;
}

} // namespace kimbim

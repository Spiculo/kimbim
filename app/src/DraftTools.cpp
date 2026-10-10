// SPDX-License-Identifier: GPL-3.0-or-later
// D84: the 2D drafting tools of the main window (doc 14 §12): Line, Polyline, Arc/circle, Rectangle
// and Fill in the Plane group. The clicking is DraftTool's; the shapes are python/kimcad/drafting.py's
// (IfcAnnotation on the level), one undo step each.
#include <QComboBox>
#include <QJsonArray>
#include <QJsonDocument>
#include <QSpinBox>
#include <QToolButton>

#include <cmath>

#include "DraftTool.h"
#include "LevelsBar.h"
#include "MainWindow.h"
#include "StatusStrip.h"
#include "ToolOptionsBar.h"
#include "Viewport.h"

namespace kimcad {

namespace {

QString compact(const QJsonValue& v)
{
    return QString::fromUtf8(v.isArray() ? QJsonDocument(v.toArray()).toJson(QJsonDocument::Compact)
                                         : QJsonDocument(v.toObject()).toJson(QJsonDocument::Compact));
}

QPointF point(const QJsonValue& v)
{
    const QJsonArray a = v.toArray();
    return QPointF(a.at(0).toDouble(), a.at(1).toDouble());
}

} // namespace

// The annotations listing's drafting fields (annotations.annotations, drafting.shape_data).
void readDrafting(const QJsonObject& o, Viewport::Annotation* a)
{
    for (const auto& c : o.value("curves").toArray()) {
        QVector<QPointF> curve;
        for (const auto& p : c.toArray())
            curve << point(p);
        a->curves << curve;
    }
    for (const auto& d : o.value("dash").toArray())
        a->dash << d.toDouble();
    for (const auto& p : o.value("area").toArray())
        a->area << point(p);
    for (const auto& h : o.value("hatch").toArray()) {
        const QJsonArray s = h.toArray();
        a->hatch << QLineF(s.at(0).toDouble(), s.at(1).toDouble(), s.at(2).toDouble(), s.at(3).toDouble());
    }
    a->solid = o.value("solid").toBool();
    a->backgroundPen = o.value("background_pen").toInt(0);
    if (o.contains("label_at")) {
        a->labelAt = point(o.value("label_at"));
        a->text = o.value("area_text").toString();
    }
}

bool MainWindow::isDraftTool(Tool tool)
{
    return tool == Tool::Line || tool == Tool::Polyline || tool == Tool::ArcCircle || tool == Tool::Rectangle
        || tool == Tool::Fill;
}

void MainWindow::setupDraftTools(ToolOptionsBar* bar)
{
    m_draftTool = new DraftTool(this);
    m_draftArcMode = new QComboBox(bar);
    m_draftArcMode->setObjectName(QStringLiteral("draftArcMode"));
    m_draftArcMode->setToolTip(tr("How the arc or circle is drawn"));
    m_draftArcMode->addItem(tr("Circle: centre and radius"), int(DraftTool::Mode::Circle));
    m_draftArcMode->addItem(tr("Arc: three points"), int(DraftTool::Mode::Arc3));
    m_draftArcMode->addItem(tr("Arc: centre, start and end"), int(DraftTool::Mode::ArcCentre));
    m_draftLineType = new QComboBox(bar);
    m_draftLineType->setObjectName(QStringLiteral("draftLineType"));
    m_draftLineType->setToolTip(tr("Line type"));
    m_draftPattern = new QComboBox(bar);
    m_draftPattern->setObjectName(QStringLiteral("draftPattern"));
    m_draftPattern->setToolTip(tr("Fill pattern (Graphics > fill patterns are project settings)"));
    m_draftBackground = new QSpinBox(bar);
    m_draftBackground->setObjectName(QStringLiteral("draftBackground"));
    m_draftBackground->setRange(0, 255);
    m_draftBackground->setSpecialValueText(tr("No background"));
    m_draftBackground->setPrefix(tr("Background pen "));
    m_draftBackground->setToolTip(tr("The fill's background pen (0: none, the model shows through)"));
    m_draftShowArea = new QToolButton(bar);
    m_draftShowArea->setObjectName(QStringLiteral("draftShowArea"));
    m_draftShowArea->setText(tr("Area"));
    m_draftShowArea->setCheckable(true);
    m_draftShowArea->setToolTip(tr("Show the fill's area in its middle"));
    for (QWidget* w : std::initializer_list<QWidget*>{m_draftArcMode, m_draftLineType, m_draftPattern, m_draftBackground, m_draftShowArea}) {
        w->setVisible(false);
        bar->addField(w);
    }
    connect(m_draftArcMode, &QComboBox::currentIndexChanged, this, [this] {
        if (m_tool == Tool::ArcCircle && m_draftArcMode->currentIndex() >= 0) {
            m_draftTool->setMode(DraftTool::Mode(m_draftArcMode->currentData().toInt()));
            m_status->showMessage(m_draftTool->hint());
        }
    });
    connect(m_draftTool, &DraftTool::previewChanged, this, &MainWindow::updateToolPreview);
    connect(m_draftTool, &DraftTool::rejected, this, [this](const QString& why) { m_status->showMessage(why); });
    connect(m_draftTool, &DraftTool::shapeFinished, this,
        [this](const QString& kind, const QVector<QPointF>& points, bool closed) { addDrafting(kind, points, closed); });
}

void MainWindow::startDraftTool(Tool tool)
{
    const bool draft = isDraftTool(tool);
    m_draftArcMode->setVisible(tool == Tool::ArcCircle);
    m_draftLineType->setVisible(draft && tool != Tool::Fill);
    for (QWidget* w : std::initializer_list<QWidget*>{m_draftPattern, m_draftBackground, m_draftShowArea})
        w->setVisible(tool == Tool::Fill);
    if (!draft) {
        m_draftTool->cancel();
        return;
    }
    // The project's line types and fill patterns (settings tables, D73 / D84), keeping the choice.
    const QJsonObject tables = bridge("graphics_tables").value("tables").toObject();
    auto fillCombo = [](QComboBox* combo, const QStringList& names, const QString& fallback) {
        const QString current = combo->currentText().isEmpty() ? fallback : combo->currentText();
        const QSignalBlocker block(combo);
        combo->clear();
        combo->addItems(names);
        combo->setCurrentIndex(std::max<int>(0, int(names.indexOf(current))));
    };
    fillCombo(m_draftLineType, tables.value("line_types").toObject().keys(), QStringLiteral("Solid"));
    QStringList patterns;
    for (const auto& v : bridge("fill_patterns").value("names").toArray())
        patterns << v.toString();
    fillCombo(m_draftPattern, patterns, QStringLiteral("Diagonal"));
    DraftTool::Mode mode = DraftTool::Mode::Line;
    if (tool == Tool::Polyline)
        mode = DraftTool::Mode::Polyline;
    else if (tool == Tool::Rectangle)
        mode = DraftTool::Mode::Rectangle;
    else if (tool == Tool::Fill)
        mode = DraftTool::Mode::Fill;
    else if (tool == Tool::ArcCircle)
        mode = DraftTool::Mode(m_draftArcMode->currentData().toInt());
    m_draftTool->setMode(mode);
}

void MainWindow::draftPointer(QPointF p, double tolerance, Qt::KeyboardModifiers mods, bool click)
{
    m_draftTool->setTolerance(tolerance);
    m_draftTool->setOrtho(mods & Qt::ShiftModifier);
    if (!click) {
        const Snap s = m_draftTool->move(p);
        QString text = m_draftTool->hint();
        static const char* const names[] = {"", QT_TR_NOOP("endpoint"), QT_TR_NOOP("midpoint"), QT_TR_NOOP("perpendicular"),
            QT_TR_NOOP("on wall"), QT_TR_NOOP("angle"), QT_TR_NOOP("grid"), QT_TR_NOOP("grid crossing"),
            QT_TR_NOOP("on grid line"), QT_TR_NOOP("wall face end"), QT_TR_NOOP("on wall face"), QT_TR_NOOP("centre")};
        if (m_draftTool->isDrawing() && m_draftTool->hover()) {
            const QPointF d = *m_draftTool->hover() - m_draftTool->points().last();
            text = tr("Length %1").arg(formatLength(std::hypot(d.x(), d.y())));
        }
        if (s.kind != Snap::None && s.kind < int(std::size(names)))
            text += QStringLiteral("  ·  ") + tr(names[s.kind]);
        m_status->showMessage(text);
        return;
    }
    if (m_tool == Tool::Fill && (mods & Qt::AltModifier) && !m_draftTool->isDrawing()) {
        fillAt(p); // Archicad's magic wand: the closed shape around the click
        return;
    }
    m_draftTool->click(p);
    m_status->showMessage(m_draftTool->hint());
}

QJsonObject MainWindow::draftOptions(const QString& kind) const
{
    QJsonObject o;
    if (kind == QLatin1String("fill")) {
        o.insert("pattern", m_draftPattern->currentText().isEmpty() ? QStringLiteral("Solid") : m_draftPattern->currentText());
        o.insert("background_pen", m_draftBackground->value());
        o.insert("show_area", m_draftShowArea->isChecked());
    } else if (!m_draftLineType->currentText().isEmpty()) {
        o.insert("line_type", m_draftLineType->currentText());
    }
    return o;
}

bool MainWindow::addDrafting(const QString& kind, const QVector<QPointF>& points, bool closed)
{
    QJsonArray pts;
    for (const QPointF& p : points)
        pts.append(QJsonArray{p.x(), p.y()});
    QJsonObject o = draftOptions(kind);
    if (kind == QLatin1String("polyline"))
        o.insert("closed", closed);
    const QJsonObject r = bridge("add_drafting", {m_levels->activeStorey(), kind, compact(pts), compact(o)});
    if (!r.value("ok").toBool()) {
        m_status->showMessage(tr("Could not draw it: %1").arg(r.value("error").toString()));
        return false;
    }
    afterEdit(r);
    refreshSnapData(); // its ends and middles snap from now on
    m_status->showMessage(m_draftTool->hint());
    return true;
}

bool MainWindow::fillAt(QPointF p)
{
    const QJsonObject r = bridge("fill_at", {m_levels->activeStorey(), QString::number(p.x(), 'g', 17),
                                                QString::number(p.y(), 'g', 17), compact(draftOptions(QStringLiteral("fill")))});
    if (!r.value("ok").toBool()) {
        m_status->showMessage(tr("Could not fill: %1").arg(r.value("error").toString()));
        return false;
    }
    afterEdit(r);
    refreshSnapData();
    return true;
}

bool MainWindow::draftGripClick(QPointF p, double tolerance, bool ortho)
{
    if (m_gripIndex >= 0) { // put the point down, snapped
        QVector<QPointF> pts = m_gripPoints;
        const QPointF from = pts[(m_gripIndex + 1) % pts.size()];
        pts[m_gripIndex] = m_draftTool->snapper().snap(p, tolerance, &from, ortho).point;
        m_gripIndex = -1;
        m_viewport->setPreviewBoxes({});
        QJsonArray arr;
        for (const QPointF& q : pts)
            arr.append(QJsonArray{q.x(), q.y()});
        const QJsonObject r = bridge("set_annotation_points", {m_gripGuid, compact(arr)});
        if (!r.value("ok").toBool()) {
            m_status->showMessage(tr("Could not move the point: %1").arg(r.value("error").toString()));
            return true;
        }
        afterEdit(r);
        refreshSnapData();
        return true;
    }
    // Pick up the nearest point of a drafting shape on the level (selected shapes first).
    double best = tolerance;
    for (const auto& v : bridge("annotations", {m_levels->activeStorey()}).value("annotations").toArray()) {
        const QJsonObject o = v.toObject();
        Viewport::Annotation a;
        a.kind = o.value("kind").toString();
        if (!a.isDrafting() || m_viewport->isLocked(o.value("guid").toString()))
            continue;
        QVector<QPointF> pts;
        for (const auto& q : o.value("points").toArray())
            pts << point(q);
        for (int i = 0; i < pts.size(); ++i) {
            const double d = std::hypot(pts[i].x() - p.x(), pts[i].y() - p.y());
            if (d <= best) {
                best = d;
                m_gripGuid = o.value("guid").toString();
                m_gripIndex = i;
                m_gripPoints = pts;
            }
        }
    }
    if (m_gripIndex >= 0)
        m_status->showMessage(tr("Click the point's new position (Esc: leave it)"));
    return m_gripIndex >= 0;
}

void MainWindow::updateDraftPreview()
{
    // The shape so far as thin strips on the level (the previews are boxes).
    const double z = m_levels ? m_levels->activeElevation() : 0.0;
    QVector<Viewport::PreviewBox> boxes;
    for (const auto& curve : m_draftTool->preview())
        for (int i = 0; i + 1 < curve.size(); ++i)
            boxes.push_back({curve[i], curve[i + 1], 0.02, z, z + 0.02});
    m_viewport->setPreviewBoxes(boxes);
}

} // namespace kimcad

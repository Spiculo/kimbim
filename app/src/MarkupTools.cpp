// SPDX-License-Identifier: GPL-3.0-or-later
// D87: the annotation pack of the main window (doc 14 §13): Tag, North arrow, Scale bar, Revision
// cloud, Angle, Radius/diameter and Level/spot dimensions in the Plane group, and Tag all. The tags
// and symbols are python/kimbim/tags.py's and symbols.py's (IfcAnnotation on the level), one undo
// step each.
#include <QComboBox>
#include <QInputDialog>
#include <QJsonArray>
#include <QJsonDocument>
#include <QLineEdit>
#include <QToolButton>

#include "DraftTool.h"
#include "LevelsBar.h"
#include "MainWindow.h"
#include "StatusStrip.h"
#include "ToolOptionsBar.h"
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

} // namespace

bool MainWindow::isMarkupTool(Tool tool)
{
    return tool == Tool::Tag || tool == Tool::NorthArrow || tool == Tool::ScaleBar || tool == Tool::AngleDimension
        || tool == Tool::RadialDimension || tool == Tool::LevelDimension;
}

void MainWindow::setupMarkupTools(ToolOptionsBar* bar)
{
    m_tagStyle = new QComboBox(bar);
    m_tagStyle->setObjectName(QStringLiteral("tagStyle"));
    m_tagStyle->setToolTip(tr("Tag style (project settings): Automatic takes the element's kind's"));
    m_tagShape = new QComboBox(bar);
    m_tagShape->setObjectName(QStringLiteral("tagShape"));
    m_tagShape->setToolTip(tr("The tag's frame"));
    m_tagShape->addItem(tr("Style's frame"), QString());
    m_tagShape->addItem(tr("No frame"), QStringLiteral("none"));
    m_tagShape->addItem(tr("Circle"), QStringLiteral("circle"));
    m_tagShape->addItem(tr("Box"), QStringLiteral("box"));
    m_tagShape->addItem(tr("Hexagon"), QStringLiteral("hexagon"));
    m_tagLeader = new QToolButton(bar);
    m_tagLeader->setObjectName(QStringLiteral("tagLeader"));
    m_tagLeader->setText(tr("Leader"));
    m_tagLeader->setCheckable(true);
    m_tagLeader->setToolTip(tr("With a leader: click the element, then where the tag goes"));
    m_markupMode = new QComboBox(bar);
    m_markupMode->setObjectName(QStringLiteral("markupMode"));
    m_markupText = new QLineEdit(bar);
    m_markupText->setObjectName(QStringLiteral("markupText"));
    m_markupText->setPlaceholderText(tr("Revision"));
    m_markupText->setMaximumWidth(80);
    m_markupText->setToolTip(tr("The revision the cloud marks (shown in a triangle)"));
    for (QWidget* w : std::initializer_list<QWidget*>{m_tagStyle, m_tagShape, m_tagLeader, m_markupMode, m_markupText}) {
        w->setVisible(false);
        bar->addField(w);
    }
    connect(m_markupMode, &QComboBox::currentIndexChanged, this, [this] {
        m_annotationPoints.clear();
        updateMarkupPreview();
    });
}

void MainWindow::startMarkupTool(Tool tool)
{
    m_tagStyle->setVisible(tool == Tool::Tag);
    m_tagShape->setVisible(tool == Tool::Tag);
    m_tagLeader->setVisible(tool == Tool::Tag);
    m_markupMode->setVisible(tool == Tool::RadialDimension || tool == Tool::LevelDimension);
    m_markupText->setVisible(tool == Tool::Cloud);
    m_tagElement.clear();
    m_markupHover.reset();
    if (tool == Tool::Tag) { // the project's tag styles, keeping the choice
        const QString current = m_tagStyle->currentData().toString();
        const QSignalBlocker block(m_tagStyle);
        m_tagStyle->clear();
        m_tagStyle->addItem(tr("Automatic"), QString());
        const QJsonObject styles = bridge("tag_styles").value("styles").toObject();
        for (auto it = styles.begin(); it != styles.end(); ++it)
            m_tagStyle->addItem(it.value().toObject().value("name").toString(it.key()), it.key());
        m_tagStyle->setCurrentIndex(std::max(0, m_tagStyle->findData(current)));
    } else if (tool == Tool::RadialDimension || tool == Tool::LevelDimension) {
        const QSignalBlocker block(m_markupMode);
        m_markupMode->clear();
        if (tool == Tool::RadialDimension) {
            m_markupMode->addItem(tr("Radius"), QStringLiteral("radius"));
            m_markupMode->addItem(tr("Diameter"), QStringLiteral("diameter"));
        } else {
            m_markupMode->addItem(tr("Level dimension"), QStringLiteral("level"));
            m_markupMode->addItem(tr("Spot elevation"), QStringLiteral("spot"));
        }
    }
    switch (tool) {
    case Tool::Tag:
        m_status->showMessage(tr("Tag: click a door, window, wall, room or other element"));
        break;
    case Tool::NorthArrow:
        m_status->showMessage(tr("North arrow: click where it goes (it points to the project's true north)"));
        break;
    case Tool::ScaleBar:
        m_status->showMessage(tr("Scale bar: click where its left end goes"));
        break;
    case Tool::Cloud:
        m_status->showMessage(tr("Revision cloud: click its outline; click the first point or press Enter to close"));
        break;
    case Tool::AngleDimension:
        m_status->showMessage(tr("Angle: click the vertex"));
        break;
    case Tool::RadialDimension:
        m_status->showMessage(tr("Radius: click the centre (circle and arc centres snap)"));
        break;
    case Tool::LevelDimension:
        m_status->showMessage(tr("Level: click the point to measure"));
        break;
    default:
        break;
    }
}

void MainWindow::markupPointer(QPointF p, double tolerance, bool click)
{
    const QPointF* from = m_annotationPoints.isEmpty() ? nullptr : &m_annotationPoints.last();
    const QPointF at = m_draftTool->snapper().snap(p, tolerance, from).point; // drafting points snap too
    if (!click) {
        m_markupHover = at;
        updateMarkupPreview();
        return;
    }
    const QString mode = m_markupMode->currentData().toString();
    switch (m_tool) {
    case Tool::Tag: {
        if (!m_tagElement.isEmpty()) { // the leader's tag: where its text goes
            const QString element = m_tagElement;
            m_tagElement.clear();
            addTag(element, at);
            m_status->showMessage(tr("Tag: click a door, window, wall, room or other element"));
            break;
        }
        const QJsonObject t = bridge("tag_target", {m_levels->activeStorey(), num(p.x()), num(p.y()), num(tolerance)});
        if (!t.value("ok").toBool()) {
            m_status->showMessage(tr("Nothing to tag there"));
            break;
        }
        if (m_tagLeader->isChecked()) {
            m_tagElement = t.value("guid").toString();
            m_status->showMessage(tr("Tag: click where the tag goes"));
        } else {
            addTag(t.value("guid").toString());
        }
        break;
    }
    case Tool::NorthArrow:
        addSymbol(QStringLiteral("north"), {at});
        break;
    case Tool::ScaleBar:
        addSymbol(QStringLiteral("scalebar"), {at});
        break;
    case Tool::AngleDimension:
    case Tool::RadialDimension:
    case Tool::LevelDimension: {
        m_annotationPoints << at;
        const int needed = m_tool == Tool::AngleDimension ? 4 : m_tool == Tool::RadialDimension ? 3 : mode == QLatin1String("spot") ? 2 : 1;
        if (m_annotationPoints.size() < needed) {
            static const char* const angleSteps[] = {"", QT_TR_NOOP("Angle: click a point on the first side"),
                QT_TR_NOOP("Angle: click a point on the second side"), QT_TR_NOOP("Angle: click where the arc goes")};
            const int n = int(m_annotationPoints.size());
            if (m_tool == Tool::AngleDimension)
                m_status->showMessage(tr(angleSteps[n]));
            else if (m_tool == Tool::RadialDimension)
                m_status->showMessage(n == 1 ? tr("Click a point on the circle") : tr("Click where the text goes"));
            else
                m_status->showMessage(tr("Spot elevation: click where the text goes"));
            break;
        }
        const QVector<QPointF> pts = m_annotationPoints;
        m_annotationPoints.clear();
        const QString kind = m_tool == Tool::AngleDimension ? QStringLiteral("angle") : mode;
        addSymbol(kind, pts);
        startMarkupTool(m_tool); // the first step's hint again
        break;
    }
    default:
        break;
    }
    updateMarkupPreview();
}

void MainWindow::updateMarkupPreview()
{
    const double z = m_levels ? m_levels->activeElevation() : 0.0;
    QVector<Viewport::PreviewBox> boxes;
    QVector<QPointF> pts = m_annotationPoints;
    if (m_markupHover && !pts.isEmpty())
        pts << *m_markupHover;
    for (int i = 0; i + 1 < pts.size(); ++i)
        boxes.push_back({pts[i], pts[i + 1], 0.02, z, z + 0.02});
    m_viewport->setPreviewBoxes(boxes);
}

bool MainWindow::addTag(const QString& elementGuid, std::optional<QPointF> at)
{
    QJsonObject o;
    if (m_tagStyle && !m_tagStyle->currentData().toString().isEmpty())
        o.insert("style", m_tagStyle->currentData().toString());
    if (m_tagShape && !m_tagShape->currentData().toString().isEmpty())
        o.insert("shape", m_tagShape->currentData().toString());
    if (m_tagLeader && m_tagLeader->isChecked())
        o.insert("leader", true);
    if (at)
        o.insert("at", QJsonArray{at->x(), at->y()});
    const QJsonObject r = bridge("add_tag", {elementGuid, compactJson(o)});
    if (!r.value("ok").toBool()) {
        m_status->showMessage(tr("Could not tag it: %1").arg(r.value("error").toString()));
        return false;
    }
    afterEdit(r);
    return true;
}

bool MainWindow::addSymbol(const QString& kind, const QVector<QPointF>& points, const QString& text)
{
    QJsonArray pts;
    for (const QPointF& p : points)
        pts.append(QJsonArray{p.x(), p.y()});
    QJsonObject o;
    if (!text.isEmpty())
        o.insert("text", text);
    if (kind == QLatin1String("scalebar"))
        o.insert("scale", m_settings.value("drawing_scale").toInt(100));
    const QJsonObject r = bridge("add_symbol", {m_levels->activeStorey(), kind, compactJson(pts), compactJson(o)});
    if (!r.value("ok").toBool()) {
        m_status->showMessage(tr("Could not add it: %1").arg(r.value("error").toString()));
        return false;
    }
    afterEdit(r);
    return true;
}

bool MainWindow::addCloud(const QVector<QPointF>& points)
{
    const bool ok = addSymbol(QStringLiteral("cloud"), points, m_markupText ? m_markupText->text().trimmed() : QString());
    m_status->showMessage(tr("Revision cloud: click its outline; click the first point or press Enter to close"));
    return ok;
}

int MainWindow::tagAll()
{
    // The elements this view shows (Archicad and Revit tag what is visible); the bridge keeps the
    // untagged doors, windows and walls of the active level.
    QJsonArray shown;
    for (const QString& g : m_viewport->guids())
        if (!m_viewport->isElementHidden(g))
            shown.append(g);
    const QJsonObject r = bridge("tag_all", {m_levels->activeStorey(), compactJson(shown), QString()});
    if (!r.value("ok").toBool()) {
        m_status->showMessage(tr("Could not tag them: %1").arg(r.value("error").toString()));
        return -1;
    }
    const int n = r.value("tagged").toInt();
    if (n > 0)
        afterEdit(r);
    m_status->showMessage(n ? tr("Tagged %n element(s)", nullptr, n) : tr("Everything shown is tagged already"));
    return n;
}

bool MainWindow::placeSheetSymbol(const QString& number, const QString& kind)
{
    QString options;
    if (kind == QLatin1String("text")) { // D91: free text on a sheet
        bool ok = false;
        const QString text = QInputDialog::getMultiLineText(this, tr("Place text"), tr("Text:"), QString(), &ok);
        if (!ok || text.trimmed().isEmpty())
            return false;
        options = QString::fromUtf8(QJsonDocument(QJsonObject{{"text", text}}).toJson(QJsonDocument::Compact));
    }
    const QJsonObject r = bridge("place_sheet_symbol", {number, kind, options});
    if (!r.value("ok").toBool()) {
        m_status->showMessage(tr("Could not place it: %1").arg(r.value("error").toString()));
        return false;
    }
    afterEdit(r);
    openSheet(number);
    refreshSheets(true);
    return true;
}

} // namespace kimbim

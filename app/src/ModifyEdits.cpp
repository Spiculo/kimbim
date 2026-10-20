// SPDX-License-Identifier: GPL-3.0-or-later
// D80: the Split, Trim/extend and Join tools of the main window (doc 14 §4). The clicking is
// ModifyTool's; the edits are python/kimbim/modify.py's, one undo step each.
#include <QComboBox>
#include <QJsonArray>
#include <QJsonDocument>

#include <cmath>

#include "LevelsBar.h"
#include "MainWindow.h"
#include "ModifyTool.h"
#include "StatusStrip.h"
#include "ToolOptionsBar.h"
#include "Viewport.h"

namespace kimbim {

namespace {

QString num(double v)
{
    return QString::number(v, 'g', 17);
}

QString flag(bool on)
{
    return on ? QStringLiteral("1") : QStringLiteral("0");
}

} // namespace

void MainWindow::setupModifyTools(ToolOptionsBar* bar)
{
    m_modifyTool = new ModifyTool(this);
    m_modifyTool->setJoinDefault(m_prefs.splitJoin()); // D92
    m_modifyMode = new QComboBox(bar);
    m_modifyMode->setObjectName(QStringLiteral("modifyMode"));
    m_modifyMode->setToolTip(tr("What the tool does"));
    m_modifyMode->setVisible(false);
    bar->addField(m_modifyMode);
    connect(m_modifyMode, &QComboBox::currentIndexChanged, this, [this] {
        if (m_modifyMode->currentIndex() < 0)
            return;
        m_modifyTool->setMode(ModifyTool::Mode(m_modifyMode->currentData().toInt()));
        m_status->showMessage(m_modifyTool->hint());
    });
    connect(m_modifyTool, &ModifyTool::previewChanged, this, &MainWindow::updateToolPreview);
    connect(m_modifyTool, &ModifyTool::splitRequested, this,
        [this](const QString& g, QPointF at, bool join) { splitElement(g, at, join); });
    connect(m_modifyTool, &ModifyTool::trimRequested, this,
        [this](const QString& g, QPointF keep, const QString& boundary, QPointF b1, QPointF b2, bool join) {
            trimElement(g, keep, boundary, b1, b2, join);
        });
    connect(m_modifyTool, &ModifyTool::cornerRequested, this,
        [this](const QString& a, QPointF p1, const QString& b, QPointF p2, bool join) { cornerElements(a, p1, b, p2, join); });
    connect(m_modifyTool, &ModifyTool::joinRequested, this, [this](const QString& a, const QString& b) { joinElements(a, b); });
    connect(m_modifyTool, &ModifyTool::unjoinRequested, this, [this](const QString& a, const QString& b) { unjoinElements(a, b); });
}

void MainWindow::startModifyTool(Tool tool)
{
    // The options bar's mode list for this tool (Trim: to a boundary / corner; Join: join / unjoin).
    const bool modify = tool == Tool::Split || tool == Tool::Trim || tool == Tool::Join;
    {
        const QSignalBlocker block(m_modifyMode);
        m_modifyMode->clear();
        if (tool == Tool::Trim) {
            m_modifyMode->addItem(tr("To a boundary"), int(ModifyTool::Mode::Trim));
            m_modifyMode->addItem(tr("Two to their corner"), int(ModifyTool::Mode::Corner));
        } else if (tool == Tool::Join) {
            m_modifyMode->addItem(tr("Join or merge"), int(ModifyTool::Mode::Join));
            m_modifyMode->addItem(tr("Unjoin"), int(ModifyTool::Mode::Unjoin));
        }
    }
    m_modifyMode->setVisible(tool == Tool::Trim || tool == Tool::Join);
    if (tool == Tool::Split)
        m_modifyTool->setMode(ModifyTool::Mode::Split);
    else if (m_modifyMode->count())
        m_modifyTool->setMode(ModifyTool::Mode(m_modifyMode->currentData().toInt()));
    if (!modify)
        m_modifyTool->cancel();
}

void MainWindow::updateModifyPreview()
{
    // The element under the cursor, the picked boundary or first element, and where a split goes.
    const double z = m_levels ? m_levels->activeElevation() : 0.0;
    QVector<Viewport::PreviewBox> boxes;
    auto outline = [&](const ModifyTool::Target& t, double extra) {
        boxes.push_back({t.a, t.b, std::max(t.width, 0.03) + extra, z, z + 0.05});
    };
    if (const auto first = m_modifyTool->first())
        outline(*first, 0.08);
    if (const auto hover = m_modifyTool->hovered())
        outline(*hover, 0.03);
    if (const auto at = m_modifyTool->splitPoint(); at && m_modifyTool->hovered()) {
        const ModifyTool::Target t = *m_modifyTool->hovered();
        const QPointF d = t.b - t.a;
        const double len = std::hypot(d.x(), d.y());
        if (len > 0) {
            const QPointF n(-d.y() / len, d.x() / len);
            const double half = t.width / 2 + 0.2;
            boxes.push_back({*at - n * half, *at + n * half, 0.04, z, z + 3.0});
        }
    }
    m_viewport->setPreviewBoxes(boxes);
}

bool MainWindow::modifyResult(const QJsonObject& r, const QString& failure)
{
    if (!r.value("ok").toBool()) {
        m_status->showMessage(failure.arg(r.value("error").toString()));
        return false;
    }
    afterEdit(r);
    m_status->showMessage(m_modifyTool->hint());
    return true;
}

bool MainWindow::splitElement(const QString& guid, QPointF at, bool join)
{
    return modifyResult(bridge("split_element", {guid, num(at.x()), num(at.y()), flag(join)}), tr("Could not split: %1"));
}

bool MainWindow::trimElement(const QString& guid, QPointF keep, const QString& boundary, QPointF b1, QPointF b2, bool join)
{
    return modifyResult(bridge("trim_extend", {guid, num(keep.x()), num(keep.y()), boundary, num(b1.x()), num(b1.y()),
                            num(b2.x()), num(b2.y()), flag(join)}),
        tr("Could not trim or extend: %1"));
}

bool MainWindow::cornerElements(const QString& first, QPointF p1, const QString& second, QPointF p2, bool join)
{
    return modifyResult(bridge("trim_corner", {first, num(p1.x()), num(p1.y()), second, num(p2.x()), num(p2.y()), flag(join)}),
        tr("Could not make the corner: %1"));
}

bool MainWindow::joinElements(const QString& first, const QString& second)
{
    return modifyResult(bridge("join_elements", {first, second, m_prefs.mergeProps()}), tr("Could not join: %1"));
}

bool MainWindow::unjoinElements(const QString& first, const QString& second)
{
    const QString list = QString::fromUtf8(QJsonDocument(QJsonArray{first, second}).toJson(QJsonDocument::Compact));
    return modifyResult(bridge("unjoin_elements", {list}), tr("Could not unjoin: %1"));
}

} // namespace kimbim

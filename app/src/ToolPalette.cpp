// SPDX-License-Identifier: GPL-3.0-or-later
#include "ToolPalette.h"

#include "Icons.h"

#include <QAction>
#include <QActionGroup>
#include <QContextMenuEvent>
#include <QGridLayout>
#include <QHelpEvent>
#include <QMenu>
#include <QMouseEvent>
#include <QPainter>
#include <QScrollArea>
#include <QScrollBar>
#include <QStyleOptionToolButton>
#include <QStylePainter>
#include <QToolButton>
#include <QToolTip>
#include <QVBoxLayout>

namespace kimcad {

namespace {

constexpr int kCorner = 9; // the flyout triangle's hit area, pixels from the bottom-right corner

// A palette button: its label elided to the cell, a letter icon when the action has none, a tooltip
// with the tool's name, shortcut and description, and for a flyout a corner triangle that opens it.
class PaletteButton : public QToolButton {
public:
    using QToolButton::QToolButton;
    QList<QAction*> members; // a flyout's tools; empty for a single tool

protected:
    void paintEvent(QPaintEvent*) override
    {
        QStylePainter p(this);
        QStyleOptionToolButton opt;
        initStyleOption(&opt);
        opt.features &= ~(QStyleOptionToolButton::HasMenu | QStyleOptionToolButton::PopupDelay
            | QStyleOptionToolButton::MenuButtonPopup);
        opt.subControls &= ~QStyle::SC_ToolButtonMenu;
        const QIcon icon = opt.icon.isNull() ? letterIcon(text()) : opt.icon;
        const QIcon::Mode mode = !isEnabled() ? QIcon::Disabled : QIcon::Normal;
        if (toolButtonStyle() == Qt::ToolButtonIconOnly) {
            opt.icon = icon;
            p.drawComplexControl(QStyle::CC_ToolButton, opt);
        } else {
            // The style centres icon and label in the cell; a palette reads better left-aligned.
            opt.text.clear();
            opt.icon = QIcon();
            p.drawComplexControl(QStyle::CC_ToolButton, opt);
            const QSize is = iconSize();
            const QRect ir(5, (height() - is.height()) / 2, is.width(), is.height());
            icon.paint(&p, ir, Qt::AlignCenter, mode, isChecked() ? QIcon::On : QIcon::Off);
            const int left = ir.right() + 6;
            const int room = width() - left - (members.isEmpty() ? 3 : kCorner - 2);
            QString label = text();
            label.replace(QStringLiteral("&&"), QStringLiteral("&"));
            p.setPen(palette().color(isEnabled() ? QPalette::Active : QPalette::Disabled, QPalette::ButtonText));
            p.drawText(QRect(left, 0, std::max(room, 0), height()), Qt::AlignLeft | Qt::AlignVCenter,
                fontMetrics().elidedText(label, Qt::ElideRight, std::max(room, 0)));
        }
        if (!members.isEmpty()) {
            QColor c = palette().color(QPalette::WindowText);
            c.setAlphaF(isEnabled() ? 0.75 : 0.3);
            p.setRenderHint(QPainter::Antialiasing);
            p.setPen(Qt::NoPen);
            p.setBrush(c);
            const QPointF br(width() - 2.5, height() - 2.5);
            p.drawPolygon(QPolygonF({br, br - QPointF(5, 0), br - QPointF(0, 5)}));
        }
    }

    void mousePressEvent(QMouseEvent* e) override
    {
        if (!members.isEmpty() && e->button() == Qt::LeftButton && e->pos().x() >= width() - kCorner
            && e->pos().y() >= height() - kCorner) {
            showMenu(); // the corner opens the flyout at once; elsewhere press and hold
            return;
        }
        QToolButton::mousePressEvent(e);
    }

    bool event(QEvent* e) override
    {
        if (e->type() == QEvent::ToolTip && defaultAction()) {
            QToolTip::showText(static_cast<QHelpEvent*>(e)->globalPos(), tipFor(defaultAction()), this);
            return true;
        }
        return QToolButton::event(e);
    }

private:
    QString tipFor(const QAction* a) const
    {
        QString tip = QStringLiteral("<b>%1</b>").arg(a->iconText().toHtmlEscaped());
        if (!a->shortcut().isEmpty())
            tip += QStringLiteral("&nbsp;&nbsp;<span style=\"opacity:0.7\">%1</span>")
                       .arg(a->shortcut().toString(QKeySequence::NativeText).toHtmlEscaped());
        if (!a->toolTip().isEmpty() && a->toolTip() != a->iconText())
            tip += QStringLiteral("<br>") + a->toolTip().toHtmlEscaped();
        if (!members.isEmpty()) {
            QStringList others;
            for (const QAction* m : members)
                if (m != a)
                    others << m->iconText().toHtmlEscaped();
            tip += QStringLiteral("<br><i>%1</i>")
                       .arg(ToolPalette::tr("Press and hold, or click the corner, for: %1").arg(others.join(QStringLiteral(", "))));
        }
        return QStringLiteral("<p style=\"white-space:pre-wrap\">%1</p>").arg(tip);
    }
};

// A group's header: a small chevron, the title and a hairline to the edge (Archicad's Toolbox
// section titles), no button face; click to fold the group.
class PaletteHeader : public QToolButton {
public:
    using QToolButton::QToolButton;

protected:
    void paintEvent(QPaintEvent*) override
    {
        QPainter p(this);
        p.setRenderHint(QPainter::Antialiasing);
        QColor ink = palette().color(QPalette::WindowText);
        if (!underMouse())
            ink.setAlphaF(0.72);
        const int h = height();
        const qreal cx = 7.5, cy = h / 2.0;
        QPen pen(ink, 1.3);
        p.setPen(pen);
        if (isChecked())
            p.drawPolyline(QPolygonF({{cx - 3, cy - 1.5}, {cx, cy + 1.5}, {cx + 3, cy - 1.5}}));
        else
            p.drawPolyline(QPolygonF({{cx - 1.5, cy - 3}, {cx + 1.5, cy}, {cx - 1.5, cy + 3}}));
        p.setFont(font());
        const QRect tr(14, 0, width() - 14, h);
        p.drawText(tr, Qt::AlignLeft | Qt::AlignVCenter, text());
        const int after = 14 + fontMetrics().horizontalAdvance(text()) + 6;
        QColor line = ink;
        line.setAlphaF(0.25);
        p.setPen(QPen(line, 1));
        if (after < width() - 2)
            p.drawLine(QPointF(after, cy + 0.5), QPointF(width() - 2, cy + 0.5));
    }
};

} // namespace

ToolPalette::ToolPalette(QWidget* parent)
    : QWidget(parent)
{
    setObjectName(QStringLiteral("toolPalette"));
    auto* outer = new QVBoxLayout(this);
    outer->setContentsMargins(0, 0, 0, 0);
    m_scroll = new QScrollArea(this);
    m_scroll->setWidgetResizable(true);
    m_scroll->setFrameShape(QFrame::NoFrame);
    m_scroll->setHorizontalScrollBarPolicy(Qt::ScrollBarAlwaysOff);
    auto* inner = new QWidget(m_scroll);
    m_column = new QVBoxLayout(inner);
    m_column->setContentsMargins(3, 2, 3, 3);
    m_column->setSpacing(0);
    m_column->addStretch(1);
    m_scroll->setWidget(inner);
    m_scroll->viewport()->installEventFilter(this);
    outer->addWidget(m_scroll);

    m_menu = new QMenu(this);
    m_menu->setObjectName(QStringLiteral("paletteMenu"));
    m_looks = new QActionGroup(this);
    const struct {
        Mode mode;
        const char* name;
        QString text;
    } looks[] = {{Mode::Icons, "actionPaletteIcons", tr("&Icons only")},
        {Mode::IconsAndLabels, "actionPaletteLabels", tr("Icons and &labels")},
        {Mode::List, "actionPaletteList", tr("&List")}};
    for (const auto& l : looks) {
        QAction* a = m_menu->addAction(l.text);
        a->setObjectName(QLatin1String(l.name));
        a->setCheckable(true);
        a->setChecked(l.mode == m_mode);
        m_looks->addAction(a);
        const Mode mode = l.mode;
        connect(a, &QAction::triggered, this, [this, mode] { setMode(mode); });
    }
}

QString ToolPalette::iconName(const QAction* action)
{
    QString n = action->objectName();
    if (n.startsWith(QLatin1String("action")))
        n = n.mid(6);
    if (n.endsWith(QLatin1String("Tool")))
        n.chop(4);
    QString out = QStringLiteral("tool");
    for (const QChar c : std::as_const(n)) {
        if (c.isUpper())
            out += QLatin1Char('-');
        out += c.toLower();
    }
    return out;
}

ToolPalette::Group* ToolPalette::group(const QString& id)
{
    for (Group& g : m_groups)
        if (g.id == id)
            return &g;
    return nullptr;
}

const ToolPalette::Group* ToolPalette::group(const QString& id) const
{
    for (const Group& g : m_groups)
        if (g.id == id)
            return &g;
    return nullptr;
}

void ToolPalette::styleHeader(QToolButton* h) const
{
    QFont f = font();
    f.setBold(true);
    f.setPointSizeF(f.pointSizeF() * 0.85);
    h->setFont(f);
    h->setFixedHeight(QFontMetrics(f).height() + 4);
    h->setIconSize(QSize(8, 8));
}

void ToolPalette::addGroup(const QString& id, const QString& title, const QList<QAction*>& actions)
{
    Group g;
    g.id = id;
    g.header = new PaletteHeader(this);
    g.header->setObjectName(QStringLiteral("toolGroup_") + id);
    g.header->setText(title);
    g.header->setCheckable(true);
    g.header->setChecked(true);
    g.header->setArrowType(Qt::DownArrow);
    g.header->setToolButtonStyle(Qt::ToolButtonTextBesideIcon);
    g.header->setAutoRaise(true);
    g.header->setSizePolicy(QSizePolicy::Expanding, QSizePolicy::Fixed);
    styleHeader(g.header);
    g.body = new QWidget(this);
    g.grid = new QGridLayout(g.body);
    g.grid->setContentsMargins(0, 0, 0, 3);
    g.grid->setSpacing(1);
    for (QAction* a : actions)
        if (a) {
            if (a->icon().isNull()) // D90: :/icons/tool-<name>.svg, "actionSlabOpeningTool" -> "tool-slab-opening"
                a->setIcon(themedIcon(iconName(a)));
            g.actions << a;
            g.items << QList<QAction*>{a};
        }
    QToolButton* header = g.header;
    QWidget* body = g.body;
    connect(header, &QToolButton::toggled, this, [header, body](bool open) {
        body->setVisible(open);
        header->setArrowType(open ? Qt::DownArrow : Qt::RightArrow);
    });
    const int at = m_column->count() - 1; // before the stretch
    m_column->insertWidget(at, g.header);
    m_column->insertWidget(at + 1, g.body);
    m_groups.append(g);
    rebuild(m_groups.last());
}

void ToolPalette::addFlyout(const QString& id, const QList<QAction*>& members)
{
    Group* g = group(id);
    if (!g)
        return;
    QList<QAction*> folded;
    int at = -1;
    for (int i = 0; i < g->items.size(); ++i) {
        const QList<QAction*>& item = g->items.at(i);
        if (item.size() == 1 && members.contains(item.first())) {
            if (at < 0)
                at = i;
            folded << item.first();
        }
    }
    if (folded.size() < 2)
        return; // nothing to fold (a tool another build doesn't have)
    QList<QList<QAction*>> items;
    for (int i = 0; i < g->items.size(); ++i) {
        const QList<QAction*>& item = g->items.at(i);
        if (i == at)
            items << folded;
        else if (!(item.size() == 1 && folded.contains(item.first())))
            items << item;
    }
    g->items = items;
    rebuild(*g);
}

void ToolPalette::styleButton(QToolButton* b) const
{
    b->setToolButtonStyle(m_mode == Mode::Icons ? Qt::ToolButtonIconOnly : Qt::ToolButtonTextBesideIcon);
    b->setIconSize(QSize(16, 16));
    b->setSizePolicy(QSizePolicy::Ignored, QSizePolicy::Fixed);
    const int h = m_mode == Mode::Icons ? 28 : (m_mode == Mode::List ? 22 : 24);
    b->setFixedHeight(h);
    b->setMinimumWidth(m_mode == Mode::Icons ? 26 : 40);
}

void ToolPalette::rebuild(Group& g)
{
    qDeleteAll(g.buttons);
    g.buttons.clear();
    for (const QList<QAction*>& item : std::as_const(g.items)) {
        auto* b = new PaletteButton(g.body);
        b->setObjectName(QStringLiteral("toolButton"));
        b->setAutoRaise(true);
        if (item.size() > 1) {
            b->members = item;
            auto* menu = new QMenu(b);
            menu->addActions(item);
            b->setMenu(menu);
            b->setPopupMode(QToolButton::DelayedPopup);
            QAction* face = item.first();
            for (QAction* a : item)
                if (a->isChecked())
                    face = a;
            b->setDefaultAction(face);
            for (QAction* a : item) {
                // The last one used takes the button (Archicad's and Revit's flyouts).
                connect(a, &QAction::triggered, b, [b, a] { b->setDefaultAction(a); });
                connect(a, &QAction::toggled, b, [b, a](bool on) {
                    if (on)
                        b->setDefaultAction(a);
                });
            }
        } else {
            b->setDefaultAction(item.first());
        }
        styleButton(b);
        g.buttons << b;
    }
    relayout(true);
}

void ToolPalette::relayout(bool force)
{
    const int avail = m_scroll->viewport()->width() - m_column->contentsMargins().left()
        - m_column->contentsMargins().right();
    int cols = 1;
    if (m_mode == Mode::Icons)
        cols = std::max(1, avail / 30);
    else if (m_mode == Mode::IconsAndLabels)
        cols = std::max(1, avail / 72);
    if (cols == m_columns && !force)
        return;
    m_columns = cols;
    for (Group& g : m_groups) {
        for (QToolButton* b : std::as_const(g.buttons))
            g.grid->removeWidget(b);
        for (int c = 0; c < g.grid->columnCount(); ++c)
            g.grid->setColumnStretch(c, 0);
        for (int i = 0; i < g.buttons.size(); ++i)
            g.grid->addWidget(g.buttons.at(i), i / cols, i % cols);
        for (int c = 0; c < cols; ++c)
            g.grid->setColumnStretch(c, 1);
    }
}

bool ToolPalette::eventFilter(QObject* watched, QEvent* event)
{
    if (watched == m_scroll->viewport() && event->type() == QEvent::Resize)
        relayout();
    return QWidget::eventFilter(watched, event);
}

void ToolPalette::contextMenuEvent(QContextMenuEvent* event)
{
    m_menu->popup(event->globalPos());
    event->accept();
}

QStringList ToolPalette::groups() const
{
    QStringList out;
    for (const Group& g : m_groups)
        out << g.id;
    return out;
}

QList<QAction*> ToolPalette::actions(const QString& id) const
{
    const Group* g = group(id);
    return g ? g->actions : QList<QAction*>();
}

QList<QToolButton*> ToolPalette::buttons(const QString& id) const
{
    const Group* g = group(id);
    return g ? g->buttons : QList<QToolButton*>();
}

QToolButton* ToolPalette::buttonFor(const QAction* action) const
{
    for (const Group& g : m_groups)
        for (int i = 0; i < g.items.size(); ++i)
            if (g.items.at(i).contains(const_cast<QAction*>(action)))
                return g.buttons.value(i);
    return nullptr;
}

void ToolPalette::setCollapsed(const QString& id, bool collapsed)
{
    if (Group* g = group(id))
        g->header->setChecked(!collapsed);
}

bool ToolPalette::isCollapsed(const QString& id) const
{
    const Group* g = group(id);
    return g && !g->header->isChecked();
}

void ToolPalette::setMode(Mode mode)
{
    const bool changed = mode != m_mode;
    m_mode = mode;
    for (QAction* a : m_looks->actions())
        a->setChecked(a->objectName() == (mode == Mode::Icons ? QLatin1String("actionPaletteIcons")
                : mode == Mode::List ? QLatin1String("actionPaletteList") : QLatin1String("actionPaletteLabels")));
    for (const Group& g : std::as_const(m_groups))
        for (QToolButton* b : g.buttons)
            styleButton(b);
    relayout(true);
    if (changed)
        emit modeChanged(mode);
}

QString ToolPalette::modeKey(Mode mode)
{
    switch (mode) {
    case Mode::Icons:
        return QStringLiteral("icons");
    case Mode::List:
        return QStringLiteral("list");
    default:
        return QStringLiteral("labels");
    }
}

ToolPalette::Mode ToolPalette::modeFromKey(const QString& key)
{
    if (key == QLatin1String("icons"))
        return Mode::Icons;
    if (key == QLatin1String("list"))
        return Mode::List;
    return Mode::IconsAndLabels;
}

} // namespace kimcad

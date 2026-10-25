// SPDX-License-Identifier: GPL-3.0-or-later
#include "JsonTreeEditor.h"

#include "PythonEngine.h"

#include <QHBoxLayout>
#include <QHash>
#include <QHeaderView>
#include <QInputDialog>
#include <QJsonArray>
#include <QJsonDocument>
#include <QMenu>
#include <QMessageBox>
#include <QPushButton>
#include <QStyledItemDelegate>
#include <QTreeWidget>
#include <QTreeWidgetItemIterator>
#include <QVBoxLayout>

#include <algorithm>

namespace kimbim {

namespace {

enum Column { KeyColumn, ValueColumn, ErrorColumn, Columns };
enum Role { KindRole = Qt::UserRole + 1, KeyRole, ValueRole, GivenRole };
enum Kind { Object, List, Leaf };

const QColor kInvalidColor(0xf8, 0xd7, 0xda);
const char* const kRoots[] = {"parts", "components", "symbol"};

// Only the Value column is edited in place: the keys come from the definition or Add field.
class ValueOnlyDelegate : public QStyledItemDelegate {
public:
    using QStyledItemDelegate::QStyledItemDelegate;
    QWidget* createEditor(QWidget*, const QStyleOptionViewItem&, const QModelIndex&) const override { return nullptr; }
};

// A leaf's value as its cell shows it: a number as JSON writes it, text as it is (a formula), a list as JSON.
QString leafText(const QJsonValue& v)
{
    if (v.isString())
        return v.toString();
    const QByteArray json = QJsonDocument(QJsonArray{v}).toJson(QJsonDocument::Compact);
    return QString::fromUtf8(json.mid(1, json.size() - 2)); // the value inside [ ]
}

// The value a cell's text stands for: the leaf's own value while the text is what it showed, what the text
// reads as in JSON when that is a number, true/false, null, a list or an object, else the text.
QJsonValue leafValue(const QString& text, const QJsonValue& was)
{
    if (!was.isUndefined() && text == leafText(was))
        return was;
    QJsonParseError error;
    const QJsonDocument doc = QJsonDocument::fromJson(QByteArray("[") + text.trimmed().toUtf8() + "]", &error);
    if (error.error == QJsonParseError::NoError && doc.array().size() == 1 && !doc.array().at(0).isString())
        return doc.array().at(0);
    return text;
}

// A list shown as one leaf: numbers or texts (a point, a vector, a step), not parts, parameters or symbol items.
bool isLeafList(const QString& key, const QJsonValue& v)
{
    if (key == QLatin1String("parts") || key == QLatin1String("params") || key == QLatin1String("symbol"))
        return false;
    for (const auto& item : v.toArray())
        if (item.isArray() || item.isObject())
            return false;
    return true;
}

int kindOf(const QTreeWidgetItem* item)
{
    return item->data(KeyColumn, KindRole).toInt();
}

QString keyOf(const QTreeWidgetItem* item)
{
    return item->data(KeyColumn, KeyRole).toString();
}

bool isPartsList(const QTreeWidgetItem* item)
{
    return item && kindOf(item) == List && keyOf(item) == QLatin1String("parts");
}

QTreeWidgetItem* childOf(QTreeWidgetItem* item, const QString& key)
{
    for (int k = 0; k < item->childCount(); ++k)
        if (keyOf(item->child(k)) == key)
            return item->child(k);
    return nullptr;
}

// The list Add item appends to: the selected list, or the list of the selected item.
QTreeWidgetItem* itemListOf(QTreeWidgetItem* item)
{
    if (item && kindOf(item) == List)
        return item;
    return item && item->parent() && kindOf(item->parent()) == List ? item->parent() : nullptr;
}

QPushButton* treeButton(const QString& text, const char* name, QWidget* parent)
{
    auto* b = new QPushButton(text, parent);
    b->setObjectName(QLatin1String(name));
    b->setAutoDefault(false);
    return b;
}

} // namespace

JsonTreeEditor::JsonTreeEditor(QWidget* parent)
    : QWidget(parent)
    , m_tree(new QTreeWidget(this))
    , m_addPart(treeButton(tr("Add part"), "partsAddPart", this))
    , m_addField(treeButton(tr("Add field"), "partsAddField", this))
    , m_addItem(treeButton(tr("Add item..."), "partsAddItem", this))
    , m_remove(treeButton(tr("Remove"), "partsRemove", this))
    , m_up(treeButton(tr("Up"), "partsUp", this))
    , m_down(treeButton(tr("Down"), "partsDown", this))
{
    setObjectName(QStringLiteral("editorParts"));
    m_tree->setColumnCount(Columns);
    m_tree->setHeaderLabels({tr("Key"), tr("Value"), tr("Error")});
    m_tree->headerItem()->setToolTip(ValueColumn, tr("A number, true/false, a list as [ ], or a formula"));
    m_tree->header()->resizeSection(KeyColumn, 170);
    m_tree->header()->resizeSection(ValueColumn, 240);
    m_tree->setItemDelegateForColumn(KeyColumn, new ValueOnlyDelegate(m_tree));
    m_tree->setItemDelegateForColumn(ErrorColumn, new ValueOnlyDelegate(m_tree));
    auto* componentButton = treeButton(tr("Add component"), "partsAddComponent", this);
    auto* menu = new QMenu(m_addPart);
    const QPair<QString, const char*> shapes[] = {{tr("Box"), "box"}, {tr("Cylinder"), "cylinder"}, {tr("Cone"), "cone"},
        {tr("Prism"), "prism"}, {tr("Revolve"), "revolve"}, {tr("Sweep"), "sweep"}, {tr("Anchors only"), "anchors"}, {tr("Use"), "use"}};
    for (const auto& [text, shape] : shapes)
        connect(menu->addAction(text), &QAction::triggered, this, [this, shape = QLatin1String(shape)] { addPart(shape); });
    m_addPart->setMenu(menu);
    m_addPart->setToolTip(tr("A part that builds as it is, into the selected component or the object"));
    m_addItem->setToolTip(tr("An item at the end of the selected list: a parameter, a symbol line or shape, or JSON"));

    auto* layout = new QVBoxLayout(this);
    layout->setContentsMargins(0, 0, 0, 0);
    layout->addWidget(m_tree, 1);
    auto* buttons = new QHBoxLayout;
    for (QPushButton* b : {m_addPart, componentButton, m_addField, m_addItem, m_remove, m_up, m_down})
        buttons->addWidget(b);
    buttons->addStretch();
    layout->addLayout(buttons);

    connect(m_tree, &QTreeWidget::itemChanged, this, [this](QTreeWidgetItem* item, int column) {
        if (column != ValueColumn || kindOf(item) != Leaf)
            return;
        if (keyOf(item) == QLatin1String("id") && item->parent() && isPartsList(item->parent()->parent()))
            relabel(item->parent()->parent()); // the part's label and path follow its id
        emit changed();
    });
    connect(m_tree, &QTreeWidget::currentItemChanged, this, &JsonTreeEditor::updateButtons);
    connect(componentButton, &QPushButton::clicked, this, [this] {
        bool ok = false;
        const QString name = QInputDialog::getText(this, tr("Add component"), tr("Component name:"), QLineEdit::Normal, QString(), &ok);
        if (ok && !name.trimmed().isEmpty())
            addComponent(name.trimmed());
    });
    connect(m_addField, &QPushButton::clicked, this, [this] {
        bool ok = false;
        const QString key = QInputDialog::getText(this, tr("Add field"), tr("Key:"), QLineEdit::Normal, QString(), &ok);
        if (!ok || key.trimmed().isEmpty())
            return;
        const QString value = QInputDialog::getText(this, tr("Add field"), tr("Value:"), QLineEdit::Normal, QString(), &ok);
        if (ok)
            addField(key.trimmed(), value);
    });
    connect(m_addItem, &QPushButton::clicked, this, [this] {
        QTreeWidgetItem* list = itemListOf(m_tree->currentItem());
        if (!list)
            return;
        bool ok = true;
        QString what;
        const bool symbol = keyOf(list) == QLatin1String("symbol") && !list->parent();
        const bool asJson = !symbol && keyOf(list) != QLatin1String("params");
        if (symbol) {
            const QPair<QString, const char*> kinds[] = {{tr("Line"), "line"}, {tr("Rectangle"), "rect"}, {tr("Circle"), "circle"}, {tr("Arc"), "arc"}};
            QStringList names;
            for (const auto& k : kinds)
                names << k.first;
            const QString name = QInputDialog::getItem(this, tr("Add item"), tr("Symbol item:"), names, 0, false, &ok);
            for (const auto& [text, kind] : kinds)
                if (text == name)
                    what = QLatin1String(kind);
        } else if (asJson) {
            what = QInputDialog::getText(this, tr("Add item"), tr("Item (JSON):"), QLineEdit::Normal, QString(), &ok);
        }
        if (ok && !addItem(what) && asJson)
            QMessageBox::warning(this, tr("Add item"), tr("The item is not JSON: %1").arg(what));
    });
    connect(m_remove, &QPushButton::clicked, this, [this] {
        QTreeWidgetItem* item = m_tree->currentItem();
        if (!item || !item->parent())
            return; // the roots stay
        QTreeWidgetItem* parent = item->parent();
        delete item;
        relabel(parent);
        relabel(parent->parent()); // a part's id removed: the part goes by its index
        emit changed();
    });
    connect(m_up, &QPushButton::clicked, this, [this] { move(-1); });
    connect(m_down, &QPushButton::clicked, this, [this] { move(1); });
    updateButtons();
}

void JsonTreeEditor::setRoots(const QJsonObject& roots)
{
    const QSignalBlocker block(m_tree);
    m_tree->clear();
    for (const char* key : kRoots) {
        const QString k = QLatin1String(key);
        const QJsonValue empty = k == QLatin1String("components") ? QJsonValue(QJsonObject()) : QJsonValue(QJsonArray());
        QTreeWidgetItem* root = addNode(nullptr, k, roots.contains(k) ? roots.value(k) : empty);
        root->setData(KeyColumn, GivenRole, roots.contains(k));
        root->setExpanded(true);
    }
    updateButtons();
}

QJsonObject JsonTreeEditor::roots() const
{
    QJsonObject out;
    for (int k = 0; k < m_tree->topLevelItemCount(); ++k) {
        QTreeWidgetItem* root = m_tree->topLevelItem(k);
        if (root->data(KeyColumn, GivenRole).toBool() || root->childCount() > 0)
            out.insert(keyOf(root), valueOf(root));
    }
    return out;
}

QTreeWidgetItem* JsonTreeEditor::addNode(QTreeWidgetItem* parent, const QString& key, const QJsonValue& v, int at)
{
    auto* item = new QTreeWidgetItem;
    item->setText(KeyColumn, key);
    item->setData(KeyColumn, KeyRole, key);
    const int kind = v.isObject() ? Object : v.isArray() && (!parent || !isLeafList(key, v)) ? List : Leaf;
    item->setData(KeyColumn, KindRole, kind);
    if (!parent)
        m_tree->addTopLevelItem(item);
    else
        parent->insertChild(at < 0 ? parent->childCount() : at, item);
    if (kind == Leaf) {
        item->setData(KeyColumn, ValueRole, QVariant::fromValue(v));
        item->setText(ValueColumn, leafText(v));
        item->setFlags(item->flags() | Qt::ItemIsEditable);
    } else if (kind == Object) {
        const QJsonObject o = v.toObject();
        for (auto it = o.begin(); it != o.end(); ++it)
            addNode(item, it.key(), it.value());
    } else {
        for (const auto& child : v.toArray())
            addNode(item, QString(), child);
        relabel(item);
    }
    return item;
}

QJsonValue JsonTreeEditor::valueOf(QTreeWidgetItem* item) const
{
    if (kindOf(item) == Leaf)
        return leafValue(item->text(ValueColumn), item->data(KeyColumn, ValueRole).toJsonValue());
    if (kindOf(item) == Object) {
        QJsonObject o;
        for (int k = 0; k < item->childCount(); ++k)
            o.insert(keyOf(item->child(k)), valueOf(item->child(k)));
        return o;
    }
    QJsonArray a;
    for (int k = 0; k < item->childCount(); ++k)
        a.append(valueOf(item->child(k)));
    return a;
}

void JsonTreeEditor::relabel(QTreeWidgetItem* list) const
{
    if (!list || kindOf(list) != List)
        return;
    const QSignalBlocker block(m_tree);
    for (int k = 0; k < list->childCount(); ++k) {
        QTreeWidgetItem* item = list->child(k);
        QTreeWidgetItem* id = isPartsList(list) && kindOf(item) == Object ? childOf(item, QStringLiteral("id")) : nullptr;
        const QJsonValue v = id && kindOf(id) == Leaf ? valueOf(id) : QJsonValue();
        item->setText(KeyColumn, v.isString() ? v.toString() : QStringLiteral("[%1]").arg(k));
    }
}

QString JsonTreeEditor::pathOf(QTreeWidgetItem* item) const
{
    QTreeWidgetItem* parent = item->parent();
    if (!parent)
        return keyOf(item);
    if (kindOf(parent) == Object)
        return pathOf(parent) + QLatin1Char('.') + keyOf(item);
    if (isPartsList(parent) && kindOf(item) == Object) // a part: by its id, as the check names it
        if (QTreeWidgetItem* id = childOf(item, QStringLiteral("id")); id && kindOf(id) == Leaf)
            if (const QJsonValue v = valueOf(id); v.isString())
                return pathOf(parent) + QLatin1Char('.') + v.toString();
    return pathOf(parent) + QStringLiteral("[%1]").arg(parent->indexOfChild(item));
}

void JsonTreeEditor::markErrors(const QList<QPair<QString, QString>>& pathMessages)
{
    const QSignalBlocker block(m_tree); // marking an item is an itemChanged too
    QHash<QString, QList<QTreeWidgetItem*>> nodes; // a part id used twice names both
    for (QTreeWidgetItemIterator it(m_tree); *it; ++it) {
        (*it)->setText(ErrorColumn, QString());
        for (int c = 0; c < Columns; ++c) {
            (*it)->setBackground(c, QBrush());
            (*it)->setToolTip(c, QString());
        }
        nodes[pathOf(*it)] << *it;
    }
    for (const auto& [path, message] : pathMessages) {
        QString p = path;
        while (!p.isEmpty() && !nodes.contains(p)) { // the nearest node: drop the last .field, [i] or >part
            const qsizetype cut = std::max({p.lastIndexOf(QLatin1Char('.')), p.lastIndexOf(QLatin1Char('[')), p.lastIndexOf(QLatin1Char('>'))});
            p = cut > 0 ? p.left(cut) : QString();
        }
        for (QTreeWidgetItem* item : nodes.value(p)) {
            const QString was = item->text(ErrorColumn);
            item->setText(ErrorColumn, was.isEmpty() ? message : was + QStringLiteral("; ") + message);
            for (int c = 0; c < Columns; ++c) {
                item->setBackground(c, kInvalidColor);
                const QString tip = item->toolTip(c);
                item->setToolTip(c, tip.isEmpty() ? message : tip + QLatin1Char('\n') + message);
            }
            for (QTreeWidgetItem* up = item->parent(); up; up = up->parent())
                up->setExpanded(true);
        }
    }
}

QTreeWidgetItem* JsonTreeEditor::partsListOf(QTreeWidgetItem* item) const
{
    for (QTreeWidgetItem* at = item; at; at = at->parent()) {
        if (isPartsList(at))
            return at;
        if (at->parent() && !at->parent()->parent() && keyOf(at->parent()) == QLatin1String("components"))
            if (QTreeWidgetItem* parts = childOf(at, QStringLiteral("parts")); isPartsList(parts))
                return parts; // a component's parts
    }
    for (int k = 0; k < m_tree->topLevelItemCount(); ++k)
        if (isPartsList(m_tree->topLevelItem(k)))
            return m_tree->topLevelItem(k);
    return nullptr;
}

void JsonTreeEditor::addPart(const QString& shape)
{
    const QJsonObject r = PythonEngine::instance().callJson("object_part_template", {shape}).object();
    QTreeWidgetItem* list = partsListOf(m_tree->currentItem());
    if (!r.value("ok").toBool() || !list)
        return;
    QStringList ids;
    for (int k = 0; k < list->childCount(); ++k)
        if (QTreeWidgetItem* id = childOf(list->child(k), QStringLiteral("id")); id && kindOf(id) == Leaf)
            ids << valueOf(id).toString();
    QString id = QStringLiteral("part");
    for (int k = 2; ids.contains(id); ++k)
        id = QStringLiteral("part%1").arg(k);
    QJsonObject part = r.value("part").toObject();
    part.insert("id", id);
    QTreeWidgetItem* item;
    {
        const QSignalBlocker block(m_tree);
        item = addNode(list, QString(), part);
        relabel(list);
        list->setExpanded(true);
        item->setExpanded(true);
    }
    m_tree->setCurrentItem(item);
    emit changed();
}

void JsonTreeEditor::addComponent(const QString& name)
{
    QTreeWidgetItem* components = nullptr;
    for (int k = 0; k < m_tree->topLevelItemCount(); ++k)
        if (keyOf(m_tree->topLevelItem(k)) == QLatin1String("components"))
            components = m_tree->topLevelItem(k);
    if (!components)
        return;
    QString key = name;
    for (int k = 2; childOf(components, key); ++k)
        key = name + QString::number(k);
    QTreeWidgetItem* item;
    {
        const QSignalBlocker block(m_tree);
        item = addNode(components, key, QJsonObject{{"params", QJsonArray()}, {"parts", QJsonArray()}});
        components->setExpanded(true);
        item->setExpanded(true);
    }
    m_tree->setCurrentItem(item);
    emit changed();
}

void JsonTreeEditor::addField(const QString& key, const QString& value)
{
    QTreeWidgetItem* object = m_tree->currentItem();
    if (!object || kindOf(object) != Object || key.isEmpty())
        return;
    QTreeWidgetItem* item;
    {
        const QSignalBlocker block(m_tree);
        delete childOf(object, key); // a key given again takes the new value
        item = addNode(object, key, leafValue(value, QJsonValue(QJsonValue::Undefined)));
        object->setExpanded(true);
        if (QTreeWidgetItem* list = object->parent(); list && kindOf(list) == List)
            relabel(list); // a part given an id
    }
    m_tree->setCurrentItem(item);
    emit changed();
}

bool JsonTreeEditor::addItem(const QString& what)
{
    QTreeWidgetItem* list = itemListOf(m_tree->currentItem());
    if (!list)
        return false;
    QJsonValue item;
    if (keyOf(list) == QLatin1String("params")) { // a parameter with a key of its own
        QStringList keys;
        for (int k = 0; k < list->childCount(); ++k)
            if (QTreeWidgetItem* key = childOf(list->child(k), QStringLiteral("key")); key && kindOf(key) == Leaf)
                keys << valueOf(key).toString();
        QString key = QStringLiteral("p");
        for (int k = 2; keys.contains(key); ++k)
            key = QStringLiteral("p%1").arg(k);
        item = QJsonObject{{"key", key}, {"kind", "length"}, {"label", key.toUpper()}, {"default", 0.1}};
    } else if (keyOf(list) == QLatin1String("symbol") && !list->parent()) {
        const QJsonObject r = PythonEngine::instance().callJson("object_symbol_template", {what}).object();
        if (!r.value("ok").toBool())
            return false;
        item = r.value("item");
    } else {
        QJsonParseError error;
        const QJsonDocument doc = QJsonDocument::fromJson(QByteArray("[") + what.trimmed().toUtf8() + "]", &error);
        if (what.trimmed().isEmpty() || error.error != QJsonParseError::NoError || doc.array().size() != 1)
            return false;
        item = doc.array().at(0);
    }
    QTreeWidgetItem* added;
    {
        const QSignalBlocker block(m_tree);
        added = addNode(list, QString(), item);
        relabel(list);
        list->setExpanded(true);
        added->setExpanded(true);
    }
    m_tree->setCurrentItem(added);
    emit changed();
    return true;
}

void JsonTreeEditor::move(int by)
{
    QTreeWidgetItem* item = m_tree->currentItem();
    QTreeWidgetItem* parent = item ? item->parent() : nullptr;
    if (!parent)
        return;
    const int at = parent->indexOfChild(item), to = at + by;
    if (to < 0 || to >= parent->childCount())
        return;
    {
        const QSignalBlocker block(m_tree);
        const bool open = item->isExpanded();
        parent->takeChild(at);
        parent->insertChild(to, item);
        item->setExpanded(open);
        relabel(parent);
    }
    m_tree->setCurrentItem(item);
    emit changed();
}

void JsonTreeEditor::updateButtons()
{
    QTreeWidgetItem* item = m_tree->currentItem();
    m_addField->setEnabled(item && kindOf(item) == Object);
    m_addItem->setEnabled(itemListOf(item) != nullptr);
    for (QPushButton* b : {m_remove, m_up, m_down})
        b->setEnabled(item && item->parent());
}

} // namespace kimbim

// SPDX-License-Identifier: GPL-3.0-or-later
#include "MaterialsDialog.h"

#include <QCheckBox>
#include <QColorDialog>
#include <QComboBox>
#include <QDialogButtonBox>
#include <QDoubleSpinBox>
#include <QFormLayout>
#include <QHBoxLayout>
#include <QHeaderView>
#include <QInputDialog>
#include <QLabel>
#include <QLineEdit>
#include <QListWidget>
#include <QMessageBox>
#include <QPainter>
#include <QPixmap>
#include <QPushButton>
#include <QSlider>
#include <QSpinBox>
#include <QTabWidget>
#include <QTableWidget>
#include <QVBoxLayout>

#include "PenGrid.h"

namespace kimbim {

namespace {

const char* kKeys[3] = {"surfaces", "materials", "composites"};

QIcon chip(const QString& colour)
{
    QPixmap pm(14, 14);
    pm.fill(Qt::transparent);
    QPainter p(&pm);
    p.setPen(QColor(0x60, 0x60, 0x60));
    p.setBrush(colour.isEmpty() ? QBrush(Qt::NoBrush) : QBrush(QColor(colour)));
    p.drawRect(0, 0, 13, 13);
    return QIcon(pm);
}

// The reflectance methods IFC names, in the order Archicad lists its shading models.
const QStringList kReflectance = {"MATT", "PLASTIC", "METAL", "GLASS", "MIRROR", "NOTDEFINED"};

} // namespace

// ---------------------------------------------------------------- MaterialsEdits

MaterialsEdits::MaterialsEdits(const QJsonObject& state)
{
    for (int k = 0; k < 3; ++k)
        m_items[k] = state.value(QLatin1String(kKeys[k])).toArray();
    for (const auto& p : state.value("patterns").toArray())
        m_patterns << p.toString();
}

int MaterialsEdits::indexOf(Kind k, const QString& name) const
{
    for (int i = 0; i < count(k); ++i)
        if (item(k, i).value("name").toString() == name)
            return i;
    return -1;
}

QStringList MaterialsEdits::names(Kind k) const
{
    QStringList out;
    for (int i = 0; i < count(k); ++i)
        out << item(k, i).value("name").toString();
    return out;
}

QStringList MaterialsEdits::compositeNames(const QString& type) const
{
    QStringList out;
    for (int i = 0; i < count(Composites); ++i)
        if (item(Composites, i).value("type").toString() == type)
            out << item(Composites, i).value("name").toString();
    return out;
}

QString MaterialsEdits::checkName(Kind k, int i, const QString& name) const
{
    if (name.trimmed().isEmpty())
        return QObject::tr("A name is needed.");
    const int other = indexOf(k, name.trimmed());
    if (other >= 0 && other != i)
        return QObject::tr("The name %1 is already used.").arg(name.trimmed());
    return QString();
}

void MaterialsEdits::setItem(Kind k, int i, const QJsonObject& fields)
{
    QJsonObject o = item(k, i);
    const QString oldName = o.value("name").toString();
    for (auto it = fields.begin(); it != fields.end(); ++it)
        if (it.key() != QLatin1String("key") && it.key() != QLatin1String("used_by"))
            o.insert(it.key(), it.value());
    if (o == item(k, i))
        return;
    m_items[k][i] = o;
    m_dirty[k].insert(i);
    const QString newName = o.value("name").toString();
    if (newName == oldName)
        return;
    // A rename follows into what refers to it by name (sent along so the engine sees one picture).
    if (k == Surfaces) {
        for (int m = 0; m < count(Materials); ++m)
            if (item(Materials, m).value("surface").toString() == oldName) {
                QJsonObject mo = item(Materials, m);
                mo.insert("surface", newName);
                m_items[Materials][m] = mo;
                m_dirty[Materials].insert(m);
            }
    } else if (k == Materials) {
        for (int c = 0; c < count(Composites); ++c) {
            QJsonObject co = item(Composites, c);
            QJsonArray layers = co.value("layers").toArray();
            bool hit = false;
            for (int l = 0; l < layers.size(); ++l) {
                QJsonObject lo = layers[l].toObject();
                if (lo.value("material").toString() == oldName) {
                    lo.insert("material", newName);
                    layers[l] = lo;
                    hit = true;
                }
            }
            if (hit) {
                co.insert("layers", layers);
                m_items[Composites][c] = co;
                m_dirty[Composites].insert(c);
            }
        }
    }
}

int MaterialsEdits::add(Kind k, QJsonObject fields, const QString& base)
{
    QString name = base;
    for (int n = 2; indexOf(k, name) >= 0; ++n)
        name = QStringLiteral("%1 %2").arg(base).arg(n);
    fields.remove("key");
    fields.insert("name", name);
    fields.insert("used_by", 0);
    m_items[k].append(fields);
    m_dirty[k].insert(count(k) - 1);
    return count(k) - 1;
}

int MaterialsEdits::duplicate(Kind k, int i)
{
    return add(k, item(k, i), item(k, i).value("name").toString());
}

void MaterialsEdits::remove(Kind k, int i, const QString& replace)
{
    const QJsonObject o = item(k, i);
    const QString name = o.value("name").toString();
    if (o.contains("key") && !o.value("key").isNull()) {
        QJsonObject deleted = m_deleted;
        QJsonArray list = deleted.value(QLatin1String(kKeys[k])).toArray();
        if (k == Surfaces)
            list.append(o.value("key"));
        else
            list.append(QJsonObject{{"key", o.value("key")}, {"replace", replace}});
        deleted.insert(QLatin1String(kKeys[k]), list);
        m_deleted = deleted;
        m_removed = true;
    }
    m_items[k].removeAt(i);
    QSet<int> dirty;
    for (int d : std::as_const(m_dirty[k]))
        if (d != i)
            dirty.insert(d > i ? d - 1 : d);
    m_dirty[k] = dirty;
    // What referred to it now refers to its replacement (or to nothing, for a surface).
    if (k == Surfaces) {
        for (int m = 0; m < count(Materials); ++m)
            if (item(Materials, m).value("surface").toString() == name) {
                QJsonObject mo = item(Materials, m);
                mo.insert("surface", QString());
                m_items[Materials][m] = mo;
                m_dirty[Materials].insert(m);
            }
    } else if (k == Materials && !replace.isEmpty()) {
        for (int c = 0; c < count(Composites); ++c) {
            QJsonObject co = item(Composites, c);
            QJsonArray layers = co.value("layers").toArray();
            bool hit = false;
            for (int l = 0; l < layers.size(); ++l) {
                QJsonObject lo = layers[l].toObject();
                if (lo.value("material").toString() == name) {
                    lo.insert("material", replace);
                    layers[l] = lo;
                    hit = true;
                }
            }
            if (hit) { // shown with the replacement; only edited composites are sent, the engine swaps the rest
                co.insert("layers", layers);
                m_items[Composites][c] = co;
            }
        }
    }
}

bool MaterialsEdits::modified() const
{
    return m_removed || !m_dirty[0].isEmpty() || !m_dirty[1].isEmpty() || !m_dirty[2].isEmpty();
}

QJsonObject MaterialsEdits::changes() const
{
    QJsonObject out;
    for (int k = 0; k < 3; ++k) {
        QList<int> rows(m_dirty[k].begin(), m_dirty[k].end());
        std::sort(rows.begin(), rows.end());
        QJsonArray list;
        for (int i : rows) {
            QJsonObject o = item(Kind(k), i);
            o.remove("used_by");
            if (k == Materials)
                o.remove("colour");
            list.append(o);
        }
        if (!list.isEmpty())
            out.insert(QLatin1String(kKeys[k]), list);
    }
    if (!m_deleted.isEmpty())
        out.insert("deleted", m_deleted);
    return out;
}

// ---------------------------------------------------------------- MaterialsDialog

MaterialsDialog::MaterialsDialog(const QJsonObject& state, const QHash<int, LineStyle>& pens, QWidget* parent)
    : QDialog(parent)
    , m_edits(state)
    , m_pens(pens)
{
    setWindowTitle(tr("Materials"));
    setObjectName(QStringLiteral("materialsDialog"));
    resize(760, 520);
    auto* layout = new QVBoxLayout(this);
    m_tabs = new QTabWidget(this);
    m_tabs->setObjectName(QStringLiteral("materialsTabs"));
    layout->addWidget(m_tabs);
    const QString titles[3] = {tr("Surfaces"), tr("Building materials"), tr("Composites")};
    QWidget* pages[3];
    for (int k = 0; k < 3; ++k) {
        pages[k] = new QWidget(m_tabs);
        auto* row = new QHBoxLayout(pages[k]);
        auto* left = new QVBoxLayout;
        m_filters[k] = new QLineEdit(pages[k]);
        m_filters[k]->setPlaceholderText(tr("Search"));
        m_filters[k]->setClearButtonEnabled(true);
        m_filters[k]->setObjectName(QStringLiteral("materialsFilter%1").arg(k));
        m_lists[k] = new QListWidget(pages[k]);
        m_lists[k]->setObjectName(QStringLiteral("materialsList%1").arg(k));
        m_lists[k]->setMinimumWidth(220);
        left->addWidget(m_filters[k]);
        left->addWidget(m_lists[k], 1);
        auto* buttons = new QHBoxLayout;
        const auto kind = MaterialsEdits::Kind(k);
        auto button = [&](const QString& text, const char* name, auto slot) {
            auto* b = new QPushButton(text, pages[k]);
            b->setObjectName(QStringLiteral("%1%2").arg(QLatin1String(name)).arg(k));
            connect(b, &QPushButton::clicked, this, slot);
            buttons->addWidget(b);
        };
        button(tr("Add"), "materialsNew", [this, kind] { newItem(kind); });
        button(tr("Duplicate"), "materialsDuplicate", [this, kind] { duplicateItem(kind); });
        button(tr("Delete"), "materialsDelete", [this, kind] { deleteItem(kind); });
        left->addLayout(buttons);
        row->addLayout(left);
        connect(m_filters[k], &QLineEdit::textChanged, this, [this, kind] { fillList(kind, current(kind)); });
        m_tabs->addTab(pages[k], titles[k]);
    }
    buildSurfaces(pages[0]);
    buildMaterials(pages[1]);
    buildComposites(pages[2]);
    for (int k = 0; k < 3; ++k) {
        const auto kind = MaterialsEdits::Kind(k);
        connect(m_lists[k], &QListWidget::currentRowChanged, this, [this, kind] {
            if (m_loading)
                return;
            const int i = current(kind);
            if (kind == MaterialsEdits::Surfaces)
                loadSurface(i);
            else if (kind == MaterialsEdits::Materials)
                loadMaterial(i);
            else
                loadComposite(i);
        });
        fillList(kind, 0);
    }
    m_tabs->setCurrentIndex(MaterialsEdits::Materials); // Archicad opens on building materials
    auto* box = new QDialogButtonBox(QDialogButtonBox::Ok | QDialogButtonBox::Cancel, this);
    connect(box, &QDialogButtonBox::accepted, this, &MaterialsDialog::accept);
    connect(box, &QDialogButtonBox::rejected, this, &QDialog::reject);
    layout->addWidget(box);
}

void MaterialsDialog::showTab(MaterialsEdits::Kind kind)
{
    m_tabs->setCurrentIndex(int(kind));
}

int MaterialsDialog::current(MaterialsEdits::Kind k) const
{
    const QListWidgetItem* it = m_lists[k]->currentItem();
    return it ? it->data(Qt::UserRole).toInt() : -1;
}

void MaterialsDialog::fillList(MaterialsEdits::Kind k, int select)
{
    m_loading = true;
    m_lists[k]->clear();
    const QString filter = m_filters[k]->text().trimmed();
    int row = -1;
    for (int i = 0; i < m_edits.count(k); ++i) {
        const QJsonObject o = m_edits.item(k, i);
        const QString name = o.value("name").toString();
        if (!filter.isEmpty() && !name.contains(filter, Qt::CaseInsensitive))
            continue;
        auto* it = new QListWidgetItem(name, m_lists[k]);
        it->setData(Qt::UserRole, i);
        if (k != MaterialsEdits::Composites)
            it->setIcon(chip(o.value("colour").toString()));
        if (i == select)
            row = m_lists[k]->count() - 1;
    }
    m_loading = false;
    m_lists[k]->setCurrentRow(row >= 0 ? row : (m_lists[k]->count() ? 0 : -1));
    if (m_lists[k]->count() == 0) { // nothing to show: clear the form
        if (k == MaterialsEdits::Surfaces)
            loadSurface(-1);
        else if (k == MaterialsEdits::Materials)
            loadMaterial(-1);
        else
            loadComposite(-1);
    }
}

// ---------------------------------------------------------------- surfaces

void MaterialsDialog::buildSurfaces(QWidget* page)
{
    auto* form = new QFormLayout;
    m_sName = new QLineEdit(page);
    m_sName->setObjectName(QStringLiteral("surfaceName"));
    form->addRow(tr("Name:"), m_sName);
    m_sColour = new QPushButton(page);
    m_sColour->setObjectName(QStringLiteral("surfaceColour"));
    form->addRow(tr("Colour:"), m_sColour);
    m_sTransparency = new QSlider(Qt::Horizontal, page);
    m_sTransparency->setObjectName(QStringLiteral("surfaceTransparency"));
    m_sTransparency->setRange(0, 100);
    form->addRow(tr("Transparency (%):"), m_sTransparency);
    m_sShine = new QSlider(Qt::Horizontal, page);
    m_sShine->setObjectName(QStringLiteral("surfaceShine"));
    m_sShine->setRange(0, 100);
    form->addRow(tr("Shine (%):"), m_sShine);
    m_sReflectance = new QComboBox(page);
    m_sReflectance->setObjectName(QStringLiteral("surfaceReflectance"));
    const QStringList labels = {tr("Matt"), tr("Plastic"), tr("Metal"), tr("Glass"), tr("Mirror"), tr("Not defined")};
    for (int i = 0; i < kReflectance.size(); ++i)
        m_sReflectance->addItem(labels[i], kReflectance[i]);
    form->addRow(tr("Reflectance:"), m_sReflectance);
    m_sUsed = new QLabel(page);
    form->addRow(QString(), m_sUsed);
    static_cast<QHBoxLayout*>(page->layout())->addLayout(form, 1);
    connect(m_sColour, &QPushButton::clicked, this, [this] {
        const QColor c = QColorDialog::getColor(QColor(m_colour), this, tr("Surface colour"));
        if (!c.isValid())
            return;
        m_colour = c.name();
        m_sColour->setIcon(chip(m_colour));
        m_sColour->setText(m_colour);
        storeSurface();
    });
    connect(m_sName, &QLineEdit::editingFinished, this, &MaterialsDialog::storeSurface);
    connect(m_sTransparency, &QSlider::valueChanged, this, &MaterialsDialog::storeSurface);
    connect(m_sShine, &QSlider::valueChanged, this, &MaterialsDialog::storeSurface);
    connect(m_sReflectance, &QComboBox::currentIndexChanged, this, &MaterialsDialog::storeSurface);
}

void MaterialsDialog::loadSurface(int i)
{
    m_loading = true;
    const QJsonObject o = i >= 0 ? m_edits.item(MaterialsEdits::Surfaces, i) : QJsonObject();
    for (QWidget* w : {static_cast<QWidget*>(m_sName), static_cast<QWidget*>(m_sColour), static_cast<QWidget*>(m_sTransparency),
             static_cast<QWidget*>(m_sShine), static_cast<QWidget*>(m_sReflectance)})
        w->setEnabled(i >= 0);
    m_sName->setText(o.value("name").toString());
    m_colour = o.value("colour").toString(QStringLiteral("#cccccc"));
    m_sColour->setIcon(chip(m_colour));
    m_sColour->setText(m_colour);
    m_sTransparency->setValue(qRound(o.value("transparency").toDouble() * 100));
    m_sShine->setValue(qRound(o.value("shine").toDouble() * 100));
    const int r = m_sReflectance->findData(o.value("reflectance").toString(QStringLiteral("NOTDEFINED")));
    m_sReflectance->setCurrentIndex(r >= 0 ? r : m_sReflectance->count() - 1);
    m_sUsed->setText(i >= 0 ? tr("Used by %n element(s)", nullptr, o.value("used_by").toInt()) : QString());
    m_loading = false;
}

void MaterialsDialog::storeSurface()
{
    const int i = current(MaterialsEdits::Surfaces);
    if (m_loading || i < 0)
        return;
    QString name = m_sName->text().trimmed();
    if (const QString err = m_edits.checkName(MaterialsEdits::Surfaces, i, name); !err.isEmpty()) {
        m_sName->setText(m_edits.item(MaterialsEdits::Surfaces, i).value("name").toString());
        name = m_sName->text();
        if (isVisible())
            QMessageBox::warning(this, tr("Materials"), err);
    }
    m_edits.setItem(MaterialsEdits::Surfaces, i, {{"name", name}, {"colour", m_colour},
        {"transparency", m_sTransparency->value() / 100.0}, {"shine", m_sShine->value() / 100.0},
        {"reflectance", m_sReflectance->currentData().toString()}});
    if (QListWidgetItem* it = m_lists[MaterialsEdits::Surfaces]->currentItem()) {
        it->setText(name);
        it->setIcon(chip(m_colour));
    }
}

// ---------------------------------------------------------------- building materials

void MaterialsDialog::setPenButton(QPushButton* b, int pen)
{
    if (pen <= 0) {
        b->setIcon(QIcon());
        b->setText(tr("None"));
        return;
    }
    b->setIcon(chip(m_pens.value(pen, LineStyle{}).color.name()));
    b->setText(QString::number(pen));
}

void MaterialsDialog::buildMaterials(QWidget* page)
{
    auto* form = new QFormLayout;
    auto line = [&](QLineEdit*& e, const char* name, const QString& label) {
        e = new QLineEdit(page);
        e->setObjectName(QLatin1String(name));
        form->addRow(label, e);
        connect(e, &QLineEdit::editingFinished, this, &MaterialsDialog::storeMaterial);
    };
    line(m_mName, "materialName", tr("Name:"));
    line(m_mId, "materialId", tr("ID:"));
    line(m_mCategory, "materialCategory", tr("Category:"));
    line(m_mManufacturer, "materialManufacturer", tr("Manufacturer:"));
    line(m_mDescription, "materialDescription", tr("Description:"));
    m_mSurface = new QComboBox(page);
    m_mSurface->setObjectName(QStringLiteral("materialSurface"));
    form->addRow(tr("Surface:"), m_mSurface);
    m_mPattern = new QComboBox(page);
    m_mPattern->setObjectName(QStringLiteral("materialPattern"));
    m_mPattern->addItem(tr("(element style)"), QString());
    for (const QString& p : m_edits.patterns())
        m_mPattern->addItem(p, p);
    form->addRow(tr("Cut fill:"), m_mPattern);
    auto* pens = new QHBoxLayout;
    m_mPen = new QPushButton(page);
    m_mPen->setObjectName(QStringLiteral("materialPen"));
    m_mBg = new QPushButton(page);
    m_mBg->setObjectName(QStringLiteral("materialBackground"));
    pens->addWidget(new QLabel(tr("Fill pen:"), page));
    pens->addWidget(m_mPen);
    pens->addWidget(new QLabel(tr("Background:"), page));
    pens->addWidget(m_mBg);
    pens->addStretch();
    form->addRow(tr("Cut fill pens:"), pens);
    m_mPriority = new QSpinBox(page);
    m_mPriority->setObjectName(QStringLiteral("materialPriority"));
    m_mPriority->setRange(0, 999);
    m_mPriority->setToolTip(tr("Intersection priority: where elements meet, the higher number runs through"));
    form->addRow(tr("Intersection priority:"), m_mPriority);
    auto number = [&](QDoubleSpinBox*& s, const char* name, const QString& label, double max, int decimals, const QString& suffix) {
        s = new QDoubleSpinBox(page);
        s->setObjectName(QLatin1String(name));
        s->setRange(0, max);
        s->setDecimals(decimals);
        s->setSuffix(suffix);
        s->setSpecialValueText(tr("Not set"));
        form->addRow(label, s);
        connect(s, &QDoubleSpinBox::valueChanged, this, &MaterialsDialog::storeMaterial);
    };
    number(m_mDensity, "materialDensity", tr("Density:"), 30000, 1, QStringLiteral(" kg/m³"));
    number(m_mConductivity, "materialConductivity", tr("Thermal conductivity:"), 1000, 3, QStringLiteral(" W/(m·K)"));
    number(m_mHeat, "materialHeat", tr("Heat capacity:"), 10000, 0, QStringLiteral(" J/(kg·K)"));
    m_mUsed = new QLabel(page);
    form->addRow(QString(), m_mUsed);
    static_cast<QHBoxLayout*>(page->layout())->addLayout(form, 1);
    connect(m_mSurface, &QComboBox::currentIndexChanged, this, &MaterialsDialog::storeMaterial);
    connect(m_mPattern, &QComboBox::currentIndexChanged, this, &MaterialsDialog::storeMaterial);
    connect(m_mPriority, &QSpinBox::valueChanged, this, &MaterialsDialog::storeMaterial);
    auto pick = [this](QPushButton* b, int* pen) {
        const int picked = PenGrid::pick(b, m_pens, {}, *pen);
        if (picked <= 0)
            return;
        *pen = picked;
        setPenButton(b, picked);
        storeMaterial();
    };
    connect(m_mPen, &QPushButton::clicked, this, [this, pick] { pick(m_mPen, &m_pen); });
    connect(m_mBg, &QPushButton::clicked, this, [this, pick] { pick(m_mBg, &m_bg); });
}

void MaterialsDialog::loadMaterial(int i)
{
    m_loading = true;
    const QJsonObject o = i >= 0 ? m_edits.item(MaterialsEdits::Materials, i) : QJsonObject();
    m_mName->setText(o.value("name").toString());
    m_mId->setText(o.value("identifier").toString());
    m_mCategory->setText(o.value("category").toString());
    m_mManufacturer->setText(o.value("manufacturer").toString());
    m_mDescription->setText(o.value("description").toString());
    m_mSurface->clear();
    m_mSurface->addItem(tr("(none)"), QString());
    for (int s = 0; s < m_edits.count(MaterialsEdits::Surfaces); ++s) {
        const QJsonObject so = m_edits.item(MaterialsEdits::Surfaces, s);
        m_mSurface->addItem(chip(so.value("colour").toString()), so.value("name").toString(), so.value("name").toString());
    }
    m_mSurface->setCurrentIndex(std::max(0, m_mSurface->findData(o.value("surface").toString())));
    m_mPattern->setCurrentIndex(std::max(0, m_mPattern->findData(o.value("pattern").toString())));
    m_pen = o.value("pen").toInt(0);
    m_bg = o.value("bg").toInt(0);
    setPenButton(m_mPen, m_pen);
    setPenButton(m_mBg, m_bg);
    m_mPriority->setValue(o.value("priority").toInt(500));
    m_mDensity->setValue(o.value("density").toDouble(0));
    m_mConductivity->setValue(o.value("conductivity").toDouble(0));
    m_mHeat->setValue(o.value("heat").toDouble(0));
    m_mUsed->setText(i >= 0 ? tr("Used by %n element(s)", nullptr, o.value("used_by").toInt()) : QString());
    m_loading = false;
}

void MaterialsDialog::storeMaterial()
{
    const int i = current(MaterialsEdits::Materials);
    if (m_loading || i < 0)
        return;
    QString name = m_mName->text().trimmed();
    if (const QString err = m_edits.checkName(MaterialsEdits::Materials, i, name); !err.isEmpty()) {
        name = m_edits.item(MaterialsEdits::Materials, i).value("name").toString();
        m_mName->setText(name);
        if (isVisible())
            QMessageBox::warning(this, tr("Materials"), err);
    }
    auto optional = [](QDoubleSpinBox* s) { return s->value() > 0 ? QJsonValue(s->value()) : QJsonValue(); };
    const QString surface = m_mSurface->currentData().toString();
    QString colour;
    if (const int s = m_edits.indexOf(MaterialsEdits::Surfaces, surface); s >= 0)
        colour = m_edits.item(MaterialsEdits::Surfaces, s).value("colour").toString();
    m_edits.setItem(MaterialsEdits::Materials, i, {{"name", name}, {"identifier", m_mId->text()},
        {"category", m_mCategory->text()}, {"manufacturer", m_mManufacturer->text()},
        {"description", m_mDescription->text()}, {"surface", surface}, {"colour", colour},
        {"pattern", m_mPattern->currentData().toString()},
        {"pen", m_pen > 0 ? QJsonValue(m_pen) : QJsonValue()}, {"bg", m_bg > 0 ? QJsonValue(m_bg) : QJsonValue()},
        {"priority", m_mPriority->value()}, {"density", optional(m_mDensity)},
        {"conductivity", optional(m_mConductivity)}, {"heat", optional(m_mHeat)}});
    if (QListWidgetItem* it = m_lists[MaterialsEdits::Materials]->currentItem()) {
        it->setText(name);
        it->setIcon(chip(colour));
    }
}

// ---------------------------------------------------------------- composites

void MaterialsDialog::buildComposites(QWidget* page)
{
    auto* right = new QVBoxLayout;
    auto* form = new QFormLayout;
    m_cName = new QLineEdit(page);
    m_cName->setObjectName(QStringLiteral("compositeName"));
    form->addRow(tr("Name:"), m_cName);
    m_cType = new QLabel(page);
    form->addRow(tr("For:"), m_cType);
    right->addLayout(form);
    m_cLayers = new QTableWidget(0, 3, page);
    m_cLayers->setObjectName(QStringLiteral("compositeLayers"));
    m_cLayers->setHorizontalHeaderLabels({tr("Building material"), tr("Thickness"), tr("Core")});
    m_cLayers->horizontalHeader()->setSectionResizeMode(0, QHeaderView::Stretch);
    m_cLayers->verticalHeader()->setVisible(false);
    m_cLayers->setSelectionBehavior(QAbstractItemView::SelectRows);
    m_cLayers->setSelectionMode(QAbstractItemView::SingleSelection);
    right->addWidget(m_cLayers, 1);
    auto* buttons = new QHBoxLayout;
    auto button = [&](const QString& text, const char* name, auto slot) {
        auto* b = new QPushButton(text, page);
        b->setObjectName(QLatin1String(name));
        connect(b, &QPushButton::clicked, this, slot);
        buttons->addWidget(b);
    };
    button(tr("Add layer"), "compositeAddLayer", [this] {
        QJsonArray layers = layersFromTable();
        const int row = m_cLayers->currentRow();
        const QJsonObject layer{{"material", m_edits.names(MaterialsEdits::Materials).value(0)}, {"thickness", 0.05}, {"core", false}};
        layers.insert(row >= 0 ? row + 1 : layers.size(), layer);
        rebuildLayers(layers);
        m_cLayers->selectRow(row >= 0 ? row + 1 : layers.size() - 1);
        storeComposite();
    });
    button(tr("Remove layer"), "compositeRemoveLayer", [this] {
        QJsonArray layers = layersFromTable();
        const int row = m_cLayers->currentRow();
        if (row < 0 || layers.size() <= 1)
            return; // a composite keeps at least one layer
        layers.removeAt(row);
        rebuildLayers(layers);
        storeComposite();
    });
    auto move = [this](int by) {
        QJsonArray layers = layersFromTable();
        const int row = m_cLayers->currentRow(), to = row + by;
        if (row < 0 || to < 0 || to >= layers.size())
            return;
        const QJsonValue v = layers[row];
        layers[row] = layers[to];
        layers[to] = v;
        rebuildLayers(layers);
        m_cLayers->selectRow(to);
        storeComposite();
    };
    button(tr("Up"), "compositeUp", [move] { move(-1); });
    button(tr("Down"), "compositeDown", [move] { move(1); });
    buttons->addStretch();
    right->addLayout(buttons);
    m_cTotal = new QLabel(page);
    m_cTotal->setObjectName(QStringLiteral("compositeTotal"));
    right->addWidget(m_cTotal);
    m_cUsed = new QLabel(page);
    right->addWidget(m_cUsed);
    static_cast<QHBoxLayout*>(page->layout())->addLayout(right, 1);
    connect(m_cName, &QLineEdit::editingFinished, this, &MaterialsDialog::storeComposite);
}

void MaterialsDialog::rebuildLayers(const QJsonArray& layers)
{
    const bool was = m_loading;
    m_loading = true;
    m_cLayers->setRowCount(0);
    m_cLayers->setRowCount(int(layers.size()));
    const QStringList materials = m_edits.names(MaterialsEdits::Materials);
    for (int r = 0; r < layers.size(); ++r) {
        const QJsonObject l = layers[r].toObject();
        auto* combo = new QComboBox(m_cLayers);
        for (const QString& m : materials) {
            const int mi = m_edits.indexOf(MaterialsEdits::Materials, m);
            combo->addItem(chip(m_edits.item(MaterialsEdits::Materials, mi).value("colour").toString()), m);
        }
        combo->setCurrentText(l.value("material").toString());
        connect(combo, &QComboBox::currentIndexChanged, this, &MaterialsDialog::storeComposite);
        m_cLayers->setCellWidget(r, 0, combo);
        auto* thickness = new QDoubleSpinBox(m_cLayers);
        thickness->setRange(0.1, 5000);
        thickness->setDecimals(1);
        thickness->setSuffix(QStringLiteral(" mm"));
        thickness->setValue(l.value("thickness").toDouble() * 1000.0);
        connect(thickness, &QDoubleSpinBox::valueChanged, this, &MaterialsDialog::storeComposite);
        m_cLayers->setCellWidget(r, 1, thickness);
        auto* core = new QCheckBox(m_cLayers);
        core->setChecked(l.value("core").toBool());
        connect(core, &QCheckBox::toggled, this, &MaterialsDialog::storeComposite);
        m_cLayers->setCellWidget(r, 2, core);
    }
    m_loading = was;
    updateTotal();
}

QJsonArray MaterialsDialog::layersFromTable() const
{
    QJsonArray out;
    for (int r = 0; r < m_cLayers->rowCount(); ++r) {
        auto* combo = qobject_cast<QComboBox*>(m_cLayers->cellWidget(r, 0));
        auto* thickness = qobject_cast<QDoubleSpinBox*>(m_cLayers->cellWidget(r, 1));
        auto* core = qobject_cast<QCheckBox*>(m_cLayers->cellWidget(r, 2));
        if (!combo || !thickness || !core)
            continue;
        out.append(QJsonObject{{"material", combo->currentText()}, {"thickness", thickness->value() / 1000.0},
            {"core", core->isChecked()}});
    }
    return out;
}

void MaterialsDialog::updateTotal()
{
    double total = 0;
    for (const auto& l : layersFromTable())
        total += l.toObject().value("thickness").toDouble();
    m_cTotal->setText(tr("Total thickness: %1 mm").arg(total * 1000.0, 0, 'f', 1));
}

void MaterialsDialog::loadComposite(int i)
{
    m_loading = true;
    const QJsonObject o = i >= 0 ? m_edits.item(MaterialsEdits::Composites, i) : QJsonObject();
    m_cName->setText(o.value("name").toString());
    m_cName->setEnabled(i >= 0);
    const QString type = o.value("type").toString();
    m_cType->setText(type == QLatin1String("IfcWallType") ? tr("Walls")
            : type == QLatin1String("IfcSlabType") ? tr("Slabs") : type.isEmpty() ? QString() : type);
    rebuildLayers(o.value("layers").toArray());
    m_cUsed->setText(i >= 0 ? tr("Used by %n element(s)", nullptr, o.value("used_by").toInt()) : QString());
    m_loading = false;
}

void MaterialsDialog::storeComposite()
{
    updateTotal();
    const int i = current(MaterialsEdits::Composites);
    if (m_loading || i < 0)
        return;
    QString name = m_cName->text().trimmed();
    if (const QString err = m_edits.checkName(MaterialsEdits::Composites, i, name); !err.isEmpty()) {
        name = m_edits.item(MaterialsEdits::Composites, i).value("name").toString();
        m_cName->setText(name);
        if (isVisible())
            QMessageBox::warning(this, tr("Materials"), err);
    }
    m_edits.setItem(MaterialsEdits::Composites, i, {{"name", name}, {"layers", layersFromTable()}});
    if (QListWidgetItem* it = m_lists[MaterialsEdits::Composites]->currentItem())
        it->setText(name);
}

// ---------------------------------------------------------------- list buttons

void MaterialsDialog::newItem(MaterialsEdits::Kind k)
{
    int i = -1;
    if (k == MaterialsEdits::Surfaces) {
        i = m_edits.add(k, {{"colour", "#cccccc"}, {"transparency", 0.0}, {"shine", 0.1}, {"reflectance", "MATT"}},
            tr("New surface"));
    } else if (k == MaterialsEdits::Materials) {
        i = m_edits.add(k, {{"surface", ""}, {"pattern", "Solid"}, {"pen", 12}, {"priority", 500}}, tr("New material"));
    } else {
        bool ok = false;
        const QStringList kinds = {tr("Walls"), tr("Slabs")};
        const QString kind = isVisible() ? QInputDialog::getItem(this, tr("New composite"), tr("For:"), kinds, 0, false, &ok)
                                         : (ok = true, kinds[0]);
        if (!ok)
            return;
        const QString type = kind == kinds[1] ? QStringLiteral("IfcSlabType") : QStringLiteral("IfcWallType");
        const QJsonArray layers{QJsonObject{{"material", m_edits.names(MaterialsEdits::Materials).value(0)},
            {"thickness", 0.2}, {"core", true}}};
        i = m_edits.add(k, {{"type", type}, {"layers", layers}}, tr("New composite"));
    }
    m_filters[k]->clear();
    fillList(k, i);
}

void MaterialsDialog::duplicateItem(MaterialsEdits::Kind k)
{
    const int i = current(k);
    if (i < 0)
        return;
    m_filters[k]->clear();
    fillList(k, m_edits.duplicate(k, i));
}

void MaterialsDialog::deleteItem(MaterialsEdits::Kind k)
{
    const int i = current(k);
    if (i < 0)
        return;
    const QJsonObject o = m_edits.item(k, i);
    QString replace;
    if (k != MaterialsEdits::Surfaces && o.value("used_by").toInt() > 0) {
        QStringList others = k == MaterialsEdits::Materials ? m_edits.names(k) : m_edits.compositeNames(o.value("type").toString());
        others.removeAll(o.value("name").toString());
        if (others.isEmpty()) {
            QMessageBox::information(this, tr("Materials"), tr("%1 is in use and there is nothing to replace it with.")
                .arg(o.value("name").toString()));
            return;
        }
        bool ok = false;
        replace = isVisible() ? QInputDialog::getItem(this, tr("Delete"),
                                    tr("%1 is used by %n element(s). Replace it with:", nullptr, o.value("used_by").toInt())
                                        .arg(o.value("name").toString()), others, 0, false, &ok)
                              : (ok = true, others.first());
        if (!ok)
            return;
    }
    m_edits.remove(k, i, replace);
    fillList(k, std::min(i, m_edits.count(k) - 1));
    if (k == MaterialsEdits::Surfaces)
        loadMaterial(current(MaterialsEdits::Materials)); // its surface list changed
}

void MaterialsDialog::accept()
{
    // Commit a field still being typed (editingFinished comes after the button's click otherwise).
    storeSurface();
    storeMaterial();
    storeComposite();
    QDialog::accept();
}

} // namespace kimbim

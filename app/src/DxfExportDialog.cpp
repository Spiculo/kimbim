// SPDX-License-Identifier: GPL-3.0-or-later
#include "DxfExportDialog.h"

#include <QCheckBox>
#include <QComboBox>
#include <QDialogButtonBox>
#include <QFileInfo>
#include <QDir>
#include <QFileDialog>
#include <QFormLayout>
#include <QHBoxLayout>
#include <QHeaderView>
#include <QJsonDocument>
#include <QLabel>
#include <QLineEdit>
#include <QPointer>
#include <QProgressBar>
#include <QPushButton>
#include <QThread>
#include <QTreeWidget>
#include <QVBoxLayout>

namespace kimcad {

namespace {
enum Role { KeyRole = Qt::UserRole, KindRole, FileRole };
constexpr int ItemColumn = 0;
constexpr int FileColumn = 1;
} // namespace

DxfExportDialog::DxfExportDialog(const QJsonObject& targets, Bridge run, QWidget* parent)
    : QDialog(parent)
    , m_run(std::move(run))
    , m_tree(new QTreeWidget(this))
    , m_folder(new QLineEdit(this))
    , m_browse(new QPushButton(tr("Browse..."), this))
    , m_layers(new QComboBox(this))
    , m_dimensions(new QCheckBox(tr("Dimensions as DIMENSION entities"), this))
    , m_progress(new QProgressBar(this))
    , m_status(new QLabel(this))
{
    setObjectName(QStringLiteral("dxfExportDialog"));
    setWindowTitle(tr("Export DXF"));
    m_tree->setObjectName(QStringLiteral("dxfItems"));
    m_tree->setColumnCount(2);
    m_tree->setHeaderLabels({tr("Drawing or sheet"), tr("File")});
    m_tree->header()->setSectionResizeMode(ItemColumn, QHeaderView::Stretch);
    m_tree->setMinimumSize(520, 300);
    m_drawings = new QTreeWidgetItem(m_tree, {tr("Drawings")});
    m_sheets = new QTreeWidgetItem(m_tree, {tr("Sheets")});
    const QHash<QString, QString> kinds{{"plan", tr("Floor plan")}, {"section", tr("Section")},
        {"elevation", tr("Elevation")}};
    auto add = [this](QTreeWidgetItem* parentItem, const QString& key, const QString& kind, const QString& label,
                   const QString& file) {
        auto* item = new QTreeWidgetItem(parentItem, {label, file});
        item->setFlags(item->flags() | Qt::ItemIsUserCheckable);
        item->setCheckState(ItemColumn, Qt::Checked);
        item->setData(ItemColumn, KeyRole, key);
        item->setData(ItemColumn, KindRole, kind);
        item->setData(ItemColumn, FileRole, file);
    };
    for (const auto& v : targets.value("drawings").toArray()) {
        const QJsonObject d = v.toObject();
        add(m_drawings, d.value("guid").toString(), QStringLiteral("drawing"),
            d.value("name").toString() + QStringLiteral("  (") + kinds.value(d.value("kind").toString()) + QLatin1Char(')'),
            d.value("file").toString());
    }
    for (const auto& v : targets.value("sheets").toArray()) {
        const QJsonObject s = v.toObject();
        add(m_sheets, s.value("number").toString(), QStringLiteral("sheet"),
            s.value("number").toString() + QStringLiteral("  ") + s.value("title").toString(), s.value("file").toString());
    }
    for (QTreeWidgetItem* group : {m_drawings, m_sheets}) {
        group->setFlags(group->flags() | Qt::ItemIsUserCheckable | Qt::ItemIsAutoTristate);
        group->setExpanded(true);
        if (group->childCount() == 0)
            group->setDisabled(true);
    }
    m_folder->setObjectName(QStringLiteral("dxfFolder"));
    m_folder->setPlaceholderText(tr("Folder for the DXF files"));
    m_layers->setObjectName(QStringLiteral("dxfLayers"));
    m_layers->addItem(tr("By KIMCAD layer"), QStringLiteral("layer"));
    m_layers->addItem(tr("By element kind (A-WALL, A-DOOR...)"), QStringLiteral("kind"));
    m_layers->setToolTip(tr("Elements without a KIMCAD layer go on the layer of their kind"));
    m_dimensions->setObjectName(QStringLiteral("dxfDimensions"));
    m_dimensions->setChecked(true);
    m_dimensions->setToolTip(tr("Off: dimensions as lines and text"));
    m_progress->setObjectName(QStringLiteral("dxfProgress"));
    m_progress->setRange(0, 1);
    m_progress->setValue(0);
    m_status->setObjectName(QStringLiteral("dxfStatus"));
    m_status->setWordWrap(true);
    m_status->setText(tr("Drawings go to model space at real size; sheets to a paper-space layout."));

    auto* folderRow = new QHBoxLayout;
    folderRow->addWidget(m_folder, 1);
    folderRow->addWidget(m_browse);
    auto* form = new QFormLayout;
    form->addRow(tr("Folder:"), folderRow);
    form->addRow(tr("Layers:"), m_layers);
    form->addRow(QString(), m_dimensions);
    auto* buttons = new QDialogButtonBox(this);
    m_export = buttons->addButton(tr("Export"), QDialogButtonBox::AcceptRole);
    m_export->setObjectName(QStringLiteral("dxfExportButton"));
    m_close = buttons->addButton(QDialogButtonBox::Close);
    auto* layout = new QVBoxLayout(this);
    layout->addWidget(m_tree, 1);
    layout->addLayout(form);
    layout->addWidget(m_progress);
    layout->addWidget(m_status);
    layout->addWidget(buttons);

    connect(m_browse, &QPushButton::clicked, this, [this] {
        const QString dir = QFileDialog::getExistingDirectory(this, tr("Export DXF to"), m_folder->text());
        if (!dir.isEmpty())
            m_folder->setText(QDir::toNativeSeparators(dir));
    });
    connect(m_export, &QPushButton::clicked, this, &DxfExportDialog::start);
    connect(m_close, &QPushButton::clicked, this, [this] { isRunning() ? cancel() : reject(); });
    connect(m_folder, &QLineEdit::textChanged, this, &DxfExportDialog::updateButtons);
    connect(m_tree, &QTreeWidget::itemChanged, this, &DxfExportDialog::updateButtons);
    updateButtons();
}

DxfExportDialog::~DxfExportDialog()
{
    if (m_worker) { // closed while exporting: let the current file finish, never leave a running thread
        m_cancel = true;
        m_worker->wait();
        delete m_worker;
    }
}

QString DxfExportDialog::folder() const
{
    return m_folder->text().trimmed();
}

void DxfExportDialog::setFolder(const QString& folder)
{
    m_folder->setText(folder);
}

QString DxfExportDialog::layerMode() const
{
    return m_layers->currentData().toString();
}

void DxfExportDialog::setLayerMode(const QString& mode)
{
    const int i = m_layers->findData(mode);
    if (i >= 0)
        m_layers->setCurrentIndex(i);
}

QJsonArray DxfExportDialog::checkedItems() const
{
    QJsonArray out;
    for (QTreeWidgetItem* group : {m_drawings, m_sheets})
        for (int i = 0; i < group->childCount(); ++i) {
            QTreeWidgetItem* item = group->child(i);
            if (item->checkState(ItemColumn) == Qt::Checked)
                out.append(QJsonObject{{item->data(ItemColumn, KindRole).toString(), item->data(ItemColumn, KeyRole).toString()}});
        }
    return out;
}

void DxfExportDialog::setChecked(const QString& key, bool checked)
{
    for (QTreeWidgetItem* group : {m_drawings, m_sheets})
        for (int i = 0; i < group->childCount(); ++i)
            if (group->child(i)->data(ItemColumn, KeyRole).toString() == key)
                group->child(i)->setCheckState(ItemColumn, checked ? Qt::Checked : Qt::Unchecked);
}

void DxfExportDialog::setAllChecked(bool checked)
{
    for (QTreeWidgetItem* group : {m_drawings, m_sheets})
        for (int i = 0; i < group->childCount(); ++i)
            group->child(i)->setCheckState(ItemColumn, checked ? Qt::Checked : Qt::Unchecked);
}

QJsonObject DxfExportDialog::options() const
{
    return {{"layers", layerMode()},
        {"dimensions", m_dimensions->isChecked() ? QStringLiteral("native") : QStringLiteral("exploded")}};
}

void DxfExportDialog::updateButtons()
{
    m_export->setEnabled(!isRunning() && !folder().isEmpty() && !checkedItems().isEmpty());
}

void DxfExportDialog::setBusy(bool busy)
{
    m_tree->setEnabled(!busy);
    m_folder->setEnabled(!busy);
    m_browse->setEnabled(!busy);
    m_layers->setEnabled(!busy);
    m_dimensions->setEnabled(!busy);
    m_close->setText(busy ? tr("Cancel") : tr("Close"));
    updateButtons();
}

void DxfExportDialog::start()
{
    if (isRunning() || folder().isEmpty())
        return;
    // One job per checked item: (bridge function, key, path).
    struct Job { QByteArray fn; QString key; QString path; };
    QList<Job> jobs;
    const QDir dir(folder());
    if (!dir.exists() && !QDir().mkpath(folder())) {
        m_status->setText(tr("Cannot create the folder %1").arg(folder()));
        return;
    }
    for (QTreeWidgetItem* group : {m_drawings, m_sheets})
        for (int i = 0; i < group->childCount(); ++i) {
            QTreeWidgetItem* item = group->child(i);
            if (item->checkState(ItemColumn) != Qt::Checked)
                continue;
            const bool sheet = item->data(ItemColumn, KindRole).toString() == QLatin1String("sheet");
            jobs.append({sheet ? QByteArrayLiteral("export_sheet_dxf") : QByteArrayLiteral("export_drawing_dxf"),
                item->data(ItemColumn, KeyRole).toString(), dir.filePath(item->data(ItemColumn, FileRole).toString())});
        }
    if (jobs.isEmpty())
        return;
    m_files.clear();
    m_errors.clear();
    m_total = int(jobs.size());
    m_cancel = false;
    m_progress->setRange(0, m_total);
    m_progress->setValue(0);
    m_status->setText(tr("Exporting %1 of %2...").arg(1).arg(m_total));
    const QString options = QString::fromUtf8(QJsonDocument(this->options()).toJson(QJsonDocument::Compact));
    QPointer<DxfExportDialog> self(this);
    Bridge run = m_run;
    std::atomic<bool>* cancel = &m_cancel; // the destructor waits for the thread, so this stays valid
    m_worker = QThread::create([self, run, jobs, options, cancel] {
        for (int i = 0; i < jobs.size(); ++i) {
            if (*cancel)
                break;
            const Job& job = jobs.at(i);
            const QJsonObject r = run(job.fn.constData(), {job.key, job.path, options});
            const QString error = r.value("ok").toBool() ? QString()
                : (r.value("error").toString().isEmpty() ? QStringLiteral("export failed") : r.value("error").toString());
            QMetaObject::invokeMethod(self, [self, i, path = job.path, error] {
                if (self)
                    self->itemDone(i, path, error);
            }, Qt::QueuedConnection);
        }
    });
    connect(m_worker, &QThread::finished, this, &DxfExportDialog::allDone, Qt::QueuedConnection);
    setBusy(true);
    m_worker->start();
}

void DxfExportDialog::itemDone(int index, const QString& path, const QString& error)
{
    if (error.isEmpty())
        m_files << path;
    else
        m_errors << QStringLiteral("%1: %2").arg(QFileInfo(path).fileName(), error);
    m_progress->setValue(index + 1);
    if (index + 1 < m_total)
        m_status->setText(tr("Exporting %1 of %2...").arg(index + 2).arg(m_total));
    emit progressed(index + 1, m_total);
}

void DxfExportDialog::allDone()
{
    if (!m_worker)
        return;
    m_worker->wait();
    delete m_worker;
    m_worker = nullptr;
    QString text = m_cancel ? tr("Cancelled: %n file(s) exported to %1.", nullptr, int(m_files.size())).arg(folder())
                            : tr("%n file(s) exported to %1.", nullptr, int(m_files.size())).arg(folder());
    if (!m_errors.isEmpty())
        text += QLatin1Char('\n') + tr("Not exported:") + QLatin1Char('\n') + m_errors.join(QLatin1Char('\n'));
    m_status->setText(text);
    setBusy(false);
    emit finished(m_files, m_errors);
}

void DxfExportDialog::cancel()
{
    if (isRunning()) {
        m_cancel = true;
        m_status->setText(tr("Cancelling after the current file..."));
    }
}

void DxfExportDialog::reject()
{
    if (isRunning()) { // Escape or the window's close button while exporting: cancel first
        cancel();
        return;
    }
    QDialog::reject();
}

} // namespace kimcad

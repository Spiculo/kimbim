// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once

#include <QDialog>
#include <QJsonArray>
#include <QJsonObject>
#include <QStringList>

#include <atomic>
#include <functional>

class QCheckBox;
class QComboBox;
class QLabel;
class QLineEdit;
class QProgressBar;
class QPushButton;
class QThread;
class QTreeWidget;
class QTreeWidgetItem;

namespace kimbim {

// File > Export DXF... (D83, Archicad's Publisher, lite): tick drawings and sheets, pick a folder and the
// layer mapping, Export. Each item becomes one DXF file, written by Python (kimbim.dxf) on a worker
// thread, one bridge call per item, so the window keeps painting and the bar moves; Cancel stops after
// the current file.
class DxfExportDialog : public QDialog {
    Q_OBJECT
public:
    using Bridge = std::function<QJsonObject(const char*, const QStringList&)>;
    // `targets`: dxf_targets() ({drawings: [{guid, name, kind, file}], sheets: [{number, title, file}]}).
    // `run` is called on the worker thread (the Python engine takes the GIL itself).
    DxfExportDialog(const QJsonObject& targets, Bridge run, QWidget* parent = nullptr);
    ~DxfExportDialog() override;

    QString folder() const;
    void setFolder(const QString& folder);
    QString layerMode() const; // "layer" or "kind"
    void setLayerMode(const QString& mode);
    // [{"drawing": guid} | {"sheet": number}, ...] in list order.
    QJsonArray checkedItems() const;
    void setChecked(const QString& key, bool checked); // a drawing's GlobalId or a sheet's number
    void setAllChecked(bool checked);
    QJsonObject options() const;

    bool isRunning() const { return m_worker != nullptr; }
    QStringList files() const { return m_files; }
    QStringList errors() const { return m_errors; }

    QTreeWidget* tree() const { return m_tree; }
    QProgressBar* progressBar() const { return m_progress; }
    QPushButton* exportButton() const { return m_export; }
    QLabel* statusLabel() const { return m_status; }

public slots:
    void start();
    void cancel();
    void reject() override; // while exporting: cancel (after the current file) instead of closing

signals:
    void progressed(int done, int total);
    void finished(const QStringList& files, const QStringList& errors);

private:
    void itemDone(int index, const QString& path, const QString& error);
    void allDone();
    void updateButtons();
    void setBusy(bool busy);

    Bridge m_run;
    QTreeWidget* m_tree;
    QTreeWidgetItem* m_drawings;
    QTreeWidgetItem* m_sheets;
    QLineEdit* m_folder;
    QPushButton* m_browse;
    QComboBox* m_layers;
    QCheckBox* m_dimensions;
    QProgressBar* m_progress;
    QLabel* m_status;
    QPushButton* m_export;
    QPushButton* m_close;
    QThread* m_worker = nullptr;
    std::atomic<bool> m_cancel{false};
    int m_total = 0;
    QStringList m_files;
    QStringList m_errors;
};

} // namespace kimbim

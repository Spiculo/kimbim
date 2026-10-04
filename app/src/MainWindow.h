// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once

#include <QElapsedTimer>
#include <QMainWindow>
#include <QThread>

namespace kimcad {

class ModelLoader;
class ModelTreePanel;
class PropertiesPanel;
class Viewport;
struct MeshChunk;

class MainWindow : public QMainWindow {
    Q_OBJECT
public:
    // quiet: report errors through signals only (no dialogs), for --self-test and automation.
    explicit MainWindow(QWidget* parent = nullptr, bool quiet = false, int chunkSize = 1000);
    ~MainWindow() override;

    void openFile(const QString& path);
    bool isLoading() const { return m_loading; }
    Viewport* viewport() const { return m_viewport; }
    ModelTreePanel* treePanel() const { return m_tree; }
    PropertiesPanel* propertiesPanel() const { return m_properties; }

signals:
    void firstChunkShown();
    void loadFinished(int elements, bool stopped);
    void loadFailed(const QString& error);

protected:
    void closeEvent(QCloseEvent* event) override;

private:
    void buildMenus();
    void buildDocks();
    void showAbout();
    void openDialog();
    void stopLoading();
    void showError(const QString& title, const QString& message);
    void showPropertiesOf(const QString& guid);

    void onOpened(const QJsonObject& info);
    void onChunk(const MeshChunk& chunk);
    void onFinished(int elements, bool stopped);
    void onFailed(const QString& error);

    bool m_quiet;
    bool m_loading = false;
    int m_loadedElements = 0;
    QString m_path;
    QElapsedTimer m_loadTimer;
    Viewport* m_viewport;
    ModelTreePanel* m_tree;
    PropertiesPanel* m_properties;
    QThread m_thread;
    ModelLoader* m_loader;
};

} // namespace kimcad

// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once

#include <QJsonObject>
#include <QObject>

#include <atomic>

#include "MeshChunk.h"

namespace kimbim {

// Opens a model and streams mesh chunks from a worker thread (the GUI thread never tessellates,
// docs/01 threading rule 1). Every Python call takes the GIL, so GUI queries stay possible.
class ModelLoader : public QObject {
    Q_OBJECT
public:
    explicit ModelLoader(int chunkSize = 1000)
        : m_chunkSize(chunkSize)
    {
    }
    void requestStop() { m_stop = true; }
    void reset() { m_stop = false; } // re-arm before queueing a new load (from the GUI thread)

public slots:
    void load(const QString& path);

signals:
    void opened(const QJsonObject& info);
    void chunkReady(const kimbim::MeshChunk& chunk);
    void finished(int elements, bool stopped);
    void failed(const QString& error);

private:
    int m_chunkSize;
    std::atomic<bool> m_stop{false};
};

} // namespace kimbim

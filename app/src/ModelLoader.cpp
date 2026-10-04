// SPDX-License-Identifier: GPL-3.0-or-later
#include "ModelLoader.h"

#include "PythonEngine.h"

namespace kimcad {

void ModelLoader::load(const QString& path)
{
    // Do NOT clear m_stop here: a close can request a stop before this queued call starts.
    // The GUI thread re-arms the loader with reset() before queueing a new load.
    if (m_stop) {
        emit finished(0, true);
        return;
    }
    PythonEngine& py = PythonEngine::instance();
    QString error;
    const QJsonObject info = py.callJson("open_model", {path}, &error).object();
    if (!info.value("ok").toBool()) {
        emit failed(info.value("error").toString(error));
        return;
    }
    emit opened(info);
    const QJsonObject started = py.callJson("start_meshing", {QStringLiteral("0")}, &error).object();
    if (!started.value("ok").toBool()) {
        emit failed(started.value("error").toString(error));
        return;
    }
    int elements = 0;
    bool done = false;
    while (!done) {
        if (m_stop) {
            emit finished(elements, true);
            return;
        }
        MeshChunk chunk;
        if (!fetchMeshChunk(py, m_chunkSize, &chunk, &done, &error)) {
            emit failed(error);
            return;
        }
        if (!done) {
            elements += chunk.elementCount();
            emit chunkReady(chunk);
        }
    }
    emit finished(elements, false);
}

} // namespace kimcad

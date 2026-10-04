// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once

#include <QByteArray>
#include <QJsonDocument>
#include <QString>
#include <QStringList>

namespace kimcad {

// Embedded CPython running `kimcad.app_bridge` (docs/01, D22, D44).
// Thread-safe: every call takes the GIL, so the model loader can call from a worker thread.
class PythonEngine {
public:
    static PythonEngine& instance();

    // Starts the interpreter (idempotent). PYTHONHOME comes from CONDA_PREFIX (the pixi
    // environment); KIMCAD_PYTHON_PATH is prepended to sys.path. Imports kimcad.app_bridge.
    bool start(QString* error);
    bool isRunning() const { return m_module != nullptr; }
    void stop();

    // Calls app_bridge.<fn>(*args) and parses the returned JSON string.
    // Returns a null document (and sets *error) on a Python exception or invalid JSON.
    QJsonDocument callJson(const char* fn, const QStringList& args, QString* error = nullptr);

    // Calls app_bridge.<fn>(*args) expecting a tuple of str/bytes (or None).
    // Returns false and leaves `out` empty for None; sets *error on failure.
    bool callParts(const char* fn, const QStringList& args, QList<QByteArray>* out, bool* isNone, QString* error);

private:
    PythonEngine() = default;
    void* m_module = nullptr; // PyObject*, kept opaque so Python.h stays out of headers
    void* m_mainThreadState = nullptr;
};

} // namespace kimcad

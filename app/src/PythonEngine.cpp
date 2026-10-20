// SPDX-License-Identifier: GPL-3.0-or-later
// Python.h must come first (it defines macros Qt headers may clash with).
#define PY_SSIZE_T_CLEAN
#undef slots
#include <Python.h>
#define slots Q_SLOTS

#include "PythonEngine.h"

#include <QDir>
#include <QJsonParseError>

namespace kimbim {

namespace {

PyObject* asModule(void* p) { return static_cast<PyObject*>(p); }

QString fetchError()
{
    PyObject *type = nullptr, *value = nullptr, *tb = nullptr;
    PyErr_Fetch(&type, &value, &tb);
    PyErr_NormalizeException(&type, &value, &tb);
    QString msg = QStringLiteral("Python error");
    if (value) {
        if (PyObject* s = PyObject_Str(value)) {
            const char* utf8 = PyUnicode_AsUTF8(s);
            if (utf8) {
                const char* name = type ? reinterpret_cast<PyTypeObject*>(type)->tp_name : "Exception";
                msg = QStringLiteral("%1: %2").arg(QString::fromUtf8(name), QString::fromUtf8(utf8));
            }
            Py_DECREF(s);
        }
    }
    Py_XDECREF(type);
    Py_XDECREF(value);
    Py_XDECREF(tb);
    PyErr_Clear();
    return msg;
}

struct Gil {
    PyGILState_STATE state = PyGILState_Ensure();
    ~Gil() { PyGILState_Release(state); }
};

PyObject* buildArgs(const QStringList& args)
{
    PyObject* tuple = PyTuple_New(args.size());
    for (int i = 0; i < args.size(); ++i) {
        QByteArray utf8 = args[i].toUtf8();
        PyTuple_SET_ITEM(tuple, i, PyUnicode_FromStringAndSize(utf8.constData(), utf8.size()));
    }
    return tuple;
}

} // namespace

PythonEngine& PythonEngine::instance()
{
    static PythonEngine engine;
    return engine;
}

bool PythonEngine::start(QString* error)
{
    if (m_module)
        return true;
    const QByteArray prefix = qgetenv("CONDA_PREFIX");
    if (prefix.isEmpty()) {
        if (error)
            *error = QStringLiteral("CONDA_PREFIX is not set: run KimBim through `pixi run app`");
        return false;
    }

    PyConfig config;
    PyConfig_InitPythonConfig(&config);
    const std::wstring home = QDir::toNativeSeparators(QString::fromLocal8Bit(prefix)).toStdWString();
    PyStatus status = PyConfig_SetString(&config, &config.home, home.c_str());
    if (!PyStatus_Exception(status))
        status = Py_InitializeFromConfig(&config);
    PyConfig_Clear(&config);
    if (PyStatus_Exception(status)) {
        if (error)
            *error = QStringLiteral("could not start Python: %1").arg(QString::fromUtf8(status.err_msg ? status.err_msg : "?"));
        return false;
    }

    const QByteArray extra = qgetenv("KIMBIM_PYTHON_PATH");
    if (!extra.isEmpty()) {
        PyObject* sysPath = PySys_GetObject("path"); // borrowed
        PyObject* dir = PyUnicode_FromString(QDir::toNativeSeparators(QString::fromLocal8Bit(extra)).toUtf8().constData());
        PyList_Insert(sysPath, 0, dir);
        Py_DECREF(dir);
    }

    PyObject* module = PyImport_ImportModule("kimbim.app_bridge");
    if (!module) {
        if (error)
            *error = QStringLiteral("could not import kimbim.app_bridge: %1").arg(fetchError());
        return false;
    }
    m_module = module;
    m_mainThreadState = PyEval_SaveThread(); // release the GIL; every call re-acquires it
    return true;
}

void PythonEngine::stop()
{
    if (!m_module)
        return;
    PyEval_RestoreThread(static_cast<PyThreadState*>(m_mainThreadState));
    Py_DECREF(asModule(m_module));
    m_module = nullptr;
    Py_FinalizeEx();
}

QJsonDocument PythonEngine::callJson(const char* fn, const QStringList& args, QString* error)
{
    QList<QByteArray> parts;
    bool isNone = false;
    if (!callParts(fn, args, &parts, &isNone, error) || isNone || parts.size() != 1)
        return {};
    QJsonParseError parseError;
    QJsonDocument doc = QJsonDocument::fromJson(parts.first(), &parseError);
    if (doc.isNull() && error)
        *error = QStringLiteral("%1 returned invalid JSON: %2").arg(QString::fromUtf8(fn), parseError.errorString());
    return doc;
}

bool PythonEngine::callParts(const char* fn, const QStringList& args, QList<QByteArray>* out, bool* isNone, QString* error)
{
    out->clear();
    *isNone = false;
    if (!m_module) {
        if (error)
            *error = QStringLiteral("Python engine not started");
        return false;
    }
    Gil gil;
    PyObject* func = PyObject_GetAttrString(asModule(m_module), fn);
    if (!func) {
        if (error)
            *error = QStringLiteral("kimbim.app_bridge has no function %1 (%2)").arg(QString::fromUtf8(fn), fetchError());
        return false;
    }
    PyObject* pyArgs = buildArgs(args);
    PyObject* result = PyObject_CallObject(func, pyArgs);
    Py_DECREF(pyArgs);
    Py_DECREF(func);
    if (!result) {
        if (error)
            *error = fetchError();
        return false;
    }
    auto take = [&](PyObject* item) -> bool {
        if (PyUnicode_Check(item)) {
            Py_ssize_t n = 0;
            const char* s = PyUnicode_AsUTF8AndSize(item, &n);
            out->append(QByteArray(s, n));
            return true;
        }
        if (PyBytes_Check(item)) {
            out->append(QByteArray(PyBytes_AS_STRING(item), PyBytes_GET_SIZE(item)));
            return true;
        }
        return false;
    };
    bool ok = true;
    if (result == Py_None) {
        *isNone = true;
    } else if (PyTuple_Check(result)) {
        for (Py_ssize_t i = 0; ok && i < PyTuple_GET_SIZE(result); ++i)
            ok = take(PyTuple_GET_ITEM(result, i));
    } else {
        ok = take(result);
    }
    Py_DECREF(result);
    if (!ok && error)
        *error = QStringLiteral("%1 returned an unsupported type (expected str, bytes, tuple or None)").arg(QString::fromUtf8(fn));
    return ok;
}

} // namespace kimbim

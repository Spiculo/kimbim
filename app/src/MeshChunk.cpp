// SPDX-License-Identifier: GPL-3.0-or-later
#include "MeshChunk.h"

#include <QJsonArray>
#include <QJsonDocument>
#include <QJsonObject>

#include <cstring>

#include "PythonEngine.h"

namespace kimcad {

namespace {

bool fail(QString* error, const QString& msg)
{
    if (error)
        *error = msg;
    return false;
}

std::vector<uint32_t> toOffsets(const QJsonArray& a)
{
    std::vector<uint32_t> out;
    out.reserve(a.size());
    for (const auto& v : a)
        out.push_back(uint32_t(v.toInteger(-1)));
    return out;
}

} // namespace

std::optional<MeshChunk> MeshChunk::parse(const QByteArray& metaJson, const QByteArray& verts,
    const QByteArray& tris, QString* error)
{
    QJsonParseError pe;
    const QJsonObject meta = QJsonDocument::fromJson(metaJson, &pe).object();
    if (pe.error != QJsonParseError::NoError) {
        fail(error, QStringLiteral("mesh chunk metadata is not JSON: %1").arg(pe.errorString()));
        return std::nullopt;
    }
    MeshChunk c;
    for (const auto& g : meta.value("guids").toArray())
        c.guids << g.toString();
    for (const auto& t : meta.value("types").toArray())
        c.types << t.toString();
    c.voff = toOffsets(meta.value("voff").toArray());
    c.toff = toOffsets(meta.value("toff").toArray());

    const size_t n = size_t(c.guids.size());
    if (c.types.size() != c.guids.size() || c.voff.size() != n + 1 || c.toff.size() != n + 1) {
        fail(error, QStringLiteral("mesh chunk: element counts disagree"));
        return std::nullopt;
    }
    if (verts.size() % (3 * sizeof(float)) || tris.size() % (3 * sizeof(uint32_t))) {
        fail(error, QStringLiteral("mesh chunk: vertex or triangle data is not whole triples"));
        return std::nullopt;
    }
    c.verts.resize(size_t(verts.size()) / sizeof(float));
    std::memcpy(c.verts.data(), verts.constData(), size_t(verts.size()));
    c.tris.resize(size_t(tris.size()) / sizeof(uint32_t));
    std::memcpy(c.tris.data(), tris.constData(), size_t(tris.size()));

    const uint32_t nv = uint32_t(c.vertexCount()), nt = uint32_t(c.triangleCount());
    for (size_t i = 0; i < n; ++i) {
        if (c.voff[i] > c.voff[i + 1] || c.toff[i] > c.toff[i + 1]) {
            fail(error, QStringLiteral("mesh chunk: offsets are not increasing"));
            return std::nullopt;
        }
    }
    if (c.voff.front() != 0 || c.toff.front() != 0 || c.voff.back() != nv || c.toff.back() != nt) {
        fail(error, QStringLiteral("mesh chunk: offsets do not match the data (%1 vertices, %2 triangles)").arg(nv).arg(nt));
        return std::nullopt;
    }
    for (uint32_t idx : c.tris) {
        if (idx >= nv) {
            fail(error, QStringLiteral("mesh chunk: triangle index %1 out of range (%2 vertices)").arg(idx).arg(nv));
            return std::nullopt;
        }
    }
    return c;
}

bool fetchElementMeshes(PythonEngine& py, const QStringList& guids, MeshChunk* out, bool* none, QString* error)
{
    QList<QByteArray> parts;
    const QString list = QString::fromUtf8(QJsonDocument(QJsonArray::fromStringList(guids)).toJson(QJsonDocument::Compact));
    if (!py.callParts("mesh_elements", {list}, &parts, none, error))
        return false;
    if (*none)
        return true;
    if (parts.size() != 3)
        return fail(error, QStringLiteral("mesh_elements returned %1 parts, expected 3").arg(parts.size()));
    auto chunk = MeshChunk::parse(parts[0], parts[1], parts[2], error);
    if (!chunk)
        return false;
    *out = std::move(*chunk);
    return true;
}

bool fetchMeshChunk(PythonEngine& py, int maxElements, MeshChunk* out, bool* done, QString* error)
{
    *done = false;
    QList<QByteArray> parts;
    bool isNone = false;
    if (!py.callParts("next_mesh_chunk", {QString::number(maxElements)}, &parts, &isNone, error))
        return false;
    if (isNone) {
        *done = true;
        return true;
    }
    if (parts.size() != 3)
        return fail(error, QStringLiteral("next_mesh_chunk returned %1 parts, expected 3").arg(parts.size()));
    auto chunk = MeshChunk::parse(parts[0], parts[1], parts[2], error);
    if (!chunk)
        return false;
    *out = std::move(*chunk);
    return true;
}

} // namespace kimcad

// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once

#include <QByteArray>
#include <QJsonObject>
#include <QMetaType>
#include <QString>
#include <QStringList>

#include <cstdint>
#include <optional>
#include <vector>

namespace kimbim {

class PythonEngine;

// A batch of element meshes from app_bridge.next_mesh_chunk: world coordinates, triangle indices
// local to the chunk. Element i owns vertices [voff[i], voff[i+1]) and triangles [toff[i], toff[i+1]).
struct MeshChunk {
    QStringList guids;
    QStringList types;
    std::vector<uint32_t> voff; // size elementCount()+1
    std::vector<uint32_t> toff; // size elementCount()+1
    std::vector<float> verts;   // xyz per vertex
    std::vector<uint32_t> tris; // 3 indices per triangle
    // D96: each triangle's surface as an index into `palette` (kNoColor: none, the class colour).
    // Empty when the producer sent no colours.
    struct Surface {
        float r = 0, g = 0, b = 0; // sRGB 0-1
        float transparency = 0;    // 0 opaque - 1 invisible
        QString texture;           // D96: an image file repeated every texW x texH metres; "" = none
        float texW = 1, texH = 1;
    };
    static constexpr uint16_t kNoColor = 0xFFFF;
    std::vector<uint16_t> faceColors;
    std::vector<Surface> palette;

    int elementCount() const { return int(guids.size()); }
    int vertexCount() const { return int(verts.size() / 3); }
    int triangleCount() const { return int(tris.size() / 3); }
    // The surface of triangle t (chunk-wide index), or nullptr without one.
    const Surface* surfaceOf(uint32_t t) const
    {
        if (t >= faceColors.size() || faceColors[t] == kNoColor || faceColors[t] >= palette.size())
            return nullptr;
        return &palette[faceColors[t]];
    }

    // Validates sizes, offsets and index ranges; returns nullopt and sets *error otherwise. `colors`
    // (one little-endian uint16 per triangle) may be empty.
    static std::optional<MeshChunk> parse(const QByteArray& metaJson, const QByteArray& verts,
        const QByteArray& tris, QString* error, const QByteArray& colors = QByteArray());
};

// Pulls the next chunk from Python. Returns false on error; sets *done when meshing is finished.
bool fetchMeshChunk(PythonEngine& py, int maxElements, MeshChunk* out, bool* done, QString* error);
// Meshes of specific elements after an edit (app_bridge.mesh_elements). *none: nothing to draw.
bool fetchElementMeshes(PythonEngine& py, const QStringList& guids, MeshChunk* out, bool* none, QString* error);
// D100: the Object settings dialog's preview, one placement of library object `key` with these values
// at the origin, built from saved version `version`'s stored definition when given (library.object_preview). False with the reason in *error
// when the values don't build.
bool fetchObjectPreview(PythonEngine& py, const QString& key, const QJsonObject& params, MeshChunk* out,
    QString* error, const QString& version = QString());

} // namespace kimbim

Q_DECLARE_METATYPE(kimbim::MeshChunk)

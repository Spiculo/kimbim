// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once

#include <QByteArray>
#include <QMetaType>
#include <QString>
#include <QStringList>

#include <cstdint>
#include <optional>
#include <vector>

namespace kimcad {

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

    int elementCount() const { return int(guids.size()); }
    int vertexCount() const { return int(verts.size() / 3); }
    int triangleCount() const { return int(tris.size() / 3); }

    // Validates sizes, offsets and index ranges; returns nullopt and sets *error otherwise.
    static std::optional<MeshChunk> parse(const QByteArray& metaJson, const QByteArray& verts,
        const QByteArray& tris, QString* error);
};

// Pulls the next chunk from Python. Returns false on error; sets *done when meshing is finished.
bool fetchMeshChunk(PythonEngine& py, int maxElements, MeshChunk* out, bool* done, QString* error);
// Meshes of specific elements after an edit (app_bridge.mesh_elements). *none: nothing to draw.
bool fetchElementMeshes(PythonEngine& py, const QStringList& guids, MeshChunk* out, bool* none, QString* error);

} // namespace kimcad

Q_DECLARE_METATYPE(kimcad::MeshChunk)

// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once

#include <AIS_InteractiveObject.hxx>
#include <Bnd_Box.hxx>
#include <Graphic3d_ArrayOfTriangles.hxx>
#include <SelectMgr_EntityOwner.hxx>

#include <QHash>
#include <QString>

#include <vector>

#include "MeshChunk.h"

namespace kimcad {

class ElementBatch;

// Selection owner for ONE element inside a batch (D42): picking, highlighting and selection are per
// element even though the batch draws ~1,000 elements as a single OCCT object.
class ElementOwner : public SelectMgr_EntityOwner {
    DEFINE_STANDARD_RTTI_INLINE(ElementOwner, SelectMgr_EntityOwner)
public:
    ElementOwner(const Handle(ElementBatch)& batch, int index);
    int index() const { return m_index; }
    ElementBatch* batch() const;

    void HilightWithColor(const Handle(PrsMgr_PresentationManager)& pm, const Handle(Prs3d_Drawer)& style,
        const int mode = 0) override;
    void Unhilight(const Handle(PrsMgr_PresentationManager)& pm, const int mode = 0) override;
    bool IsHilighted(const Handle(PrsMgr_PresentationManager)& pm, const int mode = 0) const override;
    void Clear(const Handle(PrsMgr_PresentationManager)& pm, const int mode = 0) override;

private:
    int m_index;
    Handle(Prs3d_Presentation) m_selected; // persistent highlight while selected
    Handle(Prs3d_Presentation) m_hover;    // immediate-mode highlight under the mouse
};

// Many IFC elements drawn as one AIS object (D42), flat-shaded and coloured by IFC type.
class ElementBatch : public AIS_InteractiveObject {
    DEFINE_STANDARD_RTTI_INLINE(ElementBatch, AIS_InteractiveObject)
public:
    explicit ElementBatch(MeshChunk chunk);

    int elementCount() const { return m_chunk.elementCount(); }
    int triangleCount() const { return m_chunk.triangleCount(); }
    QString guid(int i) const { return m_chunk.guids.at(i); }
    QString type(int i) const { return m_chunk.types.at(i); }
    int indexOf(const QString& guid) const { return m_index.value(guid, -1); }

    void setHidden(int i, bool hidden);
    bool isHidden(int i) const { return m_hidden[size_t(i)] != 0; }
    int visibleCount() const { return m_visible; }

    Bnd_Box elementBounds(int i) const;
    Bnd_Box visibleBounds() const;

    Handle(ElementOwner) owner(int i);
    // Flat-shaded triangles of one element (used for highlights).
    Handle(Graphic3d_ArrayOfTriangles) elementTriangles(int i) const;

    bool AcceptDisplayMode(const int mode) const override { return mode == 0; }
    void Compute(const Handle(PrsMgr_PresentationManager)& pm, const Handle(Prs3d_Presentation)& prs,
        const int mode) override;
    void ComputeSelection(const Handle(SelectMgr_Selection)& selection, const int mode) override;

private:
    void addElement(Graphic3d_ArrayOfTriangles& out, int i, bool withColors) const;

    MeshChunk m_chunk;
    QHash<QString, int> m_index;
    std::vector<char> m_hidden;
    int m_visible = 0;
    std::vector<Handle(ElementOwner)> m_owners;
    Handle(Graphic3d_ArrayOfTriangles) m_pickArray; // indexed positions for Select3D_SensitivePrimitiveArray
};

} // namespace kimcad

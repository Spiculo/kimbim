// SPDX-License-Identifier: GPL-3.0-or-later
#include "ElementBatch.h"

#include <Graphic3d_AspectFillArea3d.hxx>
#include <Graphic3d_Group.hxx>
#include <Prs3d_Drawer.hxx>
#include <Prs3d_ShadingAspect.hxx>
#include <PrsMgr_PresentationManager.hxx>
#include <Select3D_SensitivePrimitiveArray.hxx>
#include <SelectMgr_Selection.hxx>
#include <TopLoc_Location.hxx>
#include <gp_Dir.hxx>
#include <gp_Pnt.hxx>
#include <gp_Vec.hxx>

namespace kimcad {

namespace {

// Calm architectural palette by IFC class (display only; never stored).
Quantity_Color colorFor(const QString& type)
{
    struct Entry { const char* prefix; double r, g, b; };
    static const Entry palette[] = {
        {"IfcWall", 0.86, 0.84, 0.80},   {"IfcSlab", 0.70, 0.70, 0.70},  {"IfcRoof", 0.62, 0.36, 0.30},
        {"IfcWindow", 0.55, 0.75, 0.90}, {"IfcDoor", 0.65, 0.50, 0.35},  {"IfcColumn", 0.75, 0.75, 0.78},
        {"IfcBeam", 0.72, 0.72, 0.76},   {"IfcStair", 0.68, 0.66, 0.62}, {"IfcRailing", 0.45, 0.45, 0.48},
        {"IfcCovering", 0.80, 0.78, 0.72}, {"IfcFurnish", 0.70, 0.60, 0.50}, {"IfcSpace", 0.60, 0.80, 0.60},
    };
    const QByteArray t = type.toLatin1();
    for (const auto& e : palette)
        if (t.startsWith(e.prefix))
            return Quantity_Color(e.r, e.g, e.b, Quantity_TOC_RGB);
    return Quantity_Color(0.78, 0.78, 0.78, Quantity_TOC_RGB);
}

gp_Pnt vertex(const MeshChunk& c, uint32_t i)
{
    return gp_Pnt(c.verts[3 * i], c.verts[3 * i + 1], c.verts[3 * i + 2]);
}

} // namespace

// ---------------- ElementOwner ----------------

ElementOwner::ElementOwner(const Handle(ElementBatch)& batch, int index)
    : SelectMgr_EntityOwner(batch, 5)
    , m_index(index)
{
}

ElementBatch* ElementOwner::batch() const
{
    return static_cast<ElementBatch*>(Selectable().get());
}

void ElementOwner::HilightWithColor(const Handle(PrsMgr_PresentationManager)& pm, const Handle(Prs3d_Drawer)& style,
    const int)
{
    ElementBatch* b = batch();
    if (!b || b->isHidden(m_index))
        return;
    const bool hover = pm->IsImmediateModeOn();
    Handle(Prs3d_Presentation)& prs = hover ? m_hover : m_selected;
    if (prs.IsNull())
        prs = new Prs3d_Presentation(pm->StructureManager());
    prs->Clear();
    Handle(Graphic3d_AspectFillArea3d) aspect = new Graphic3d_AspectFillArea3d();
    aspect->SetInteriorStyle(Aspect_IS_SOLID);
    aspect->SetInteriorColor(style->Color());
    aspect->SetShadingModel(Graphic3d_TypeOfShadingModel_Unlit);
    Handle(Graphic3d_Group) group = prs->NewGroup();
    group->SetGroupPrimitivesAspect(aspect);
    group->AddPrimitiveArray(b->elementTriangles(m_index));
    prs->SetZLayer(style->ZLayer() != Graphic3d_ZLayerId_UNKNOWN ? style->ZLayer()
                   : (hover ? Graphic3d_ZLayerId_Top : Graphic3d_ZLayerId_Default));
    if (hover)
        pm->AddToImmediateList(prs);
    else
        prs->Display();
}

void ElementOwner::Unhilight(const Handle(PrsMgr_PresentationManager)&, const int)
{
    if (!m_selected.IsNull())
        m_selected->Erase();
    if (!m_hover.IsNull())
        m_hover->Erase();
}

bool ElementOwner::IsHilighted(const Handle(PrsMgr_PresentationManager)&, const int) const
{
    return !m_selected.IsNull() && m_selected->IsDisplayed();
}

void ElementOwner::Clear(const Handle(PrsMgr_PresentationManager)& pm, const int mode)
{
    Unhilight(pm, mode);
    m_selected.Nullify();
    m_hover.Nullify();
}

// ---------------- ElementBatch ----------------

ElementBatch::ElementBatch(MeshChunk chunk)
    : m_chunk(std::move(chunk))
    , m_hidden(size_t(m_chunk.elementCount()), 0)
    , m_visible(m_chunk.elementCount())
    , m_owners(size_t(m_chunk.elementCount()))
{
    for (int i = 0; i < m_chunk.elementCount(); ++i)
        m_index.insert(m_chunk.guids.at(i), i);
    m_pickArray = new Graphic3d_ArrayOfTriangles(m_chunk.vertexCount(), int(m_chunk.tris.size()));
    for (int v = 0; v < m_chunk.vertexCount(); ++v)
        m_pickArray->AddVertex(vertex(m_chunk, uint32_t(v)));
    for (uint32_t idx : m_chunk.tris)
        m_pickArray->AddEdge(int(idx) + 1); // AddEdge is 1-based
}

void ElementBatch::setHidden(int i, bool hidden)
{
    char& h = m_hidden[size_t(i)];
    if (bool(h) == hidden)
        return;
    h = hidden ? 1 : 0;
    m_visible += hidden ? -1 : 1;
}

Bnd_Box ElementBatch::elementBounds(int i) const
{
    Bnd_Box box;
    for (uint32_t v = m_chunk.voff[size_t(i)]; v < m_chunk.voff[size_t(i) + 1]; ++v)
        box.Add(vertex(m_chunk, v));
    return box;
}

Bnd_Box ElementBatch::visibleBounds() const
{
    Bnd_Box box;
    for (int i = 0; i < elementCount(); ++i)
        if (!isHidden(i))
            box.Add(elementBounds(i));
    return box;
}

Handle(ElementOwner) ElementBatch::owner(int i)
{
    Handle(ElementOwner)& o = m_owners[size_t(i)];
    if (o.IsNull())
        o = new ElementOwner(this, i);
    return o;
}

void ElementBatch::addElement(Graphic3d_ArrayOfTriangles& out, int i, bool withColors) const
{
    const Quantity_Color color = colorFor(m_chunk.types.at(i));
    for (uint32_t t = m_chunk.toff[size_t(i)]; t < m_chunk.toff[size_t(i) + 1]; ++t) {
        const gp_Pnt a = vertex(m_chunk, m_chunk.tris[3 * t]);
        const gp_Pnt b = vertex(m_chunk, m_chunk.tris[3 * t + 1]);
        const gp_Pnt c = vertex(m_chunk, m_chunk.tris[3 * t + 2]);
        gp_Vec n = gp_Vec(a, b).Crossed(gp_Vec(a, c));
        const gp_Dir dir = n.Magnitude() > 1e-12 ? gp_Dir(n) : gp_Dir(0, 0, 1); // degenerate triangle
        for (const gp_Pnt& p : {a, b, c}) {
            if (withColors)
                out.AddVertex(p, dir, color);
            else
                out.AddVertex(p, dir);
        }
    }
}

Handle(Graphic3d_ArrayOfTriangles) ElementBatch::elementTriangles(int i) const
{
    const int n = int(m_chunk.toff[size_t(i) + 1] - m_chunk.toff[size_t(i)]);
    Handle(Graphic3d_ArrayOfTriangles) arr = new Graphic3d_ArrayOfTriangles(n * 3, 0, Graphic3d_ArrayFlags_VertexNormal);
    addElement(*arr, i, false);
    return arr;
}

void ElementBatch::Compute(const Handle(PrsMgr_PresentationManager)&, const Handle(Prs3d_Presentation)& prs,
    const int mode)
{
    if (mode != 0)
        return;
    int tris = 0;
    for (int i = 0; i < elementCount(); ++i)
        if (!isHidden(i))
            tris += int(m_chunk.toff[size_t(i) + 1] - m_chunk.toff[size_t(i)]);
    if (tris == 0)
        return;
    Handle(Graphic3d_ArrayOfTriangles) arr = new Graphic3d_ArrayOfTriangles(
        tris * 3, 0, Graphic3d_ArrayFlags_VertexNormal | Graphic3d_ArrayFlags_VertexColor);
    for (int i = 0; i < elementCount(); ++i)
        if (!isHidden(i))
            addElement(*arr, i, true);
    Handle(Graphic3d_Group) group = prs->NewGroup();
    Handle(Graphic3d_AspectFillArea3d) aspect = new Graphic3d_AspectFillArea3d(*myDrawer->ShadingAspect()->Aspect());
    aspect->SetInteriorColor(Quantity_NOC_WHITE); // vertex colours carry the palette
    group->SetGroupPrimitivesAspect(aspect);
    group->AddPrimitiveArray(arr);
}

void ElementBatch::ComputeSelection(const Handle(SelectMgr_Selection)& selection, const int mode)
{
    if (mode != 0)
        return;
    for (int i = 0; i < elementCount(); ++i) {
        const int t0 = int(m_chunk.toff[size_t(i)]), t1 = int(m_chunk.toff[size_t(i) + 1]);
        if (isHidden(i) || t1 == t0)
            continue;
        Handle(Select3D_SensitivePrimitiveArray) sensitive = new Select3D_SensitivePrimitiveArray(owner(i));
        sensitive->InitTriangulation(m_pickArray->Attributes(), m_pickArray->Indices(), TopLoc_Location(), t0 * 3,
            t1 * 3 - 1);
        selection->Add(sensitive);
    }
}

} // namespace kimcad

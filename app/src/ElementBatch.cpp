// SPDX-License-Identifier: GPL-3.0-or-later
#define _USE_MATH_DEFINES
#include "ElementBatch.h"
#include <unordered_map>
#include <cmath>
#include <cstdio>
#include <Graphic3d_AspectLine3d.hxx>
#include <Graphic3d_ArrayOfSegments.hxx>

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
    // The highlight is cut like the element (else the cut-away part shows as a floating overlay).
    prs->SetClipPlanes(b->ClipPlanes());
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
    , m_retired(size_t(m_chunk.elementCount()), 0)
    , m_override(size_t(m_chunk.elementCount()))
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

void ElementBatch::retire(int i)
{
    setHidden(i, true);
    m_retired[size_t(i)] = 1;
}

void ElementBatch::setHidden(int i, bool hidden)
{
    if (!hidden && isRetired(i))
        return;
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

void ElementBatch::addElement(Graphic3d_ArrayOfTriangles& out, int i, bool withColors, const Quantity_Color* fixed) const
{
    const Quantity_Color color = fixed ? *fixed : m_override[size_t(i)].value_or(colorFor(m_chunk.types.at(i)));
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

Quantity_Color ElementBatch::s_background(0.97, 0.97, 0.98, Quantity_TOC_RGB);

namespace {

// Vertex position quantised to 10 micrometres, so unwelded copies of a vertex compare equal.
struct Key {
    long long x, y, z;
    bool operator==(const Key& o) const { return x == o.x && y == o.y && z == o.z; }
    bool operator<(const Key& o) const { return x != o.x ? x < o.x : (y != o.y ? y < o.y : z < o.z); }
};

Key keyOf(const gp_Pnt& p)
{
    constexpr double q = 1e-5;
    return Key{std::llround(p.X() / q), std::llround(p.Y() / q), std::llround(p.Z() / q)};
}

struct EdgeKey {
    Key a, b;
    bool operator==(const EdgeKey& o) const { return a == o.a && b == o.b; }
};

struct EdgeHash {
    size_t operator()(const EdgeKey& e) const
    {
        size_t h = 1469598103934665603ull;
        for (long long v : {e.a.x, e.a.y, e.a.z, e.b.x, e.b.y, e.b.z})
            h = (h ^ size_t(v)) * 1099511628211ull;
        return h;
    }
};

struct EdgeInfo {
    gp_Pnt a, b;
    gp_Dir firstNormal;
    int faces = 0;
    bool crease = false;
};

} // namespace

std::vector<std::pair<gp_Pnt, gp_Pnt>> ElementBatch::featureEdges(const MeshChunk& c, int element, double angleDeg)
{
    const double cosLimit = std::cos(angleDeg * M_PI / 180.0);
    std::unordered_map<EdgeKey, EdgeInfo, EdgeHash> edges;
    std::vector<EdgeKey> order; // deterministic output order
    for (uint32_t t = c.toff[size_t(element)]; t < c.toff[size_t(element) + 1]; ++t) {
        const gp_Pnt p[3] = {vertex(c, c.tris[3 * t]), vertex(c, c.tris[3 * t + 1]), vertex(c, c.tris[3 * t + 2])};
        const gp_Vec n = gp_Vec(p[0], p[1]).Crossed(gp_Vec(p[0], p[2]));
        if (n.Magnitude() < 1e-14)
            continue; // degenerate triangle
        const gp_Dir normal(n);
        for (int k = 0; k < 3; ++k) {
            gp_Pnt a = p[k], b = p[(k + 1) % 3];
            Key ka = keyOf(a), kb = keyOf(b);
            if (ka == kb)
                continue;
            if (kb < ka) {
                std::swap(ka, kb);
                std::swap(a, b);
            }
            const EdgeKey key{ka, kb};
            auto [it, inserted] = edges.try_emplace(key);
            EdgeInfo& e = it->second;
            if (inserted) {
                e.a = a;
                e.b = b;
                e.firstNormal = normal;
                order.push_back(key);
            } else if (std::abs(e.firstNormal.Dot(normal)) < cosLimit) {
                e.crease = true; // |dot|: inconsistently wound neighbours are still coplanar
            }
            ++e.faces;
        }
    }
    std::vector<std::pair<gp_Pnt, gp_Pnt>> out;
    for (const EdgeKey& k : order) {
        const EdgeInfo& e = edges.at(k);
        if (e.faces == 1 || e.faces > 2 || e.crease)
            out.emplace_back(e.a, e.b);
    }
    return out;
}

std::vector<std::vector<gp_Pnt2d>> ElementBatch::sectionLoops(const MeshChunk& c, int element, double z)
{
    // 1. Every triangle crossing the plane gives one segment.
    struct P {
        long long x, y;
        bool operator==(const P& o) const { return x == o.x && y == o.y; }
    };
    struct PH {
        size_t operator()(const P& p) const { return size_t(p.x * 73856093LL ^ p.y * 19349663LL); }
    };
    constexpr double q = 1e-5;
    auto key = [&](const gp_Pnt2d& p) { return P{std::llround(p.X() / q), std::llround(p.Y() / q)}; };
    std::vector<std::pair<gp_Pnt2d, gp_Pnt2d>> segments;
    for (uint32_t t = c.toff[size_t(element)]; t < c.toff[size_t(element) + 1]; ++t) {
        const gp_Pnt v[3] = {vertex(c, c.tris[3 * t]), vertex(c, c.tris[3 * t + 1]), vertex(c, c.tris[3 * t + 2])};
        std::vector<gp_Pnt2d> hits;
        for (int k = 0; k < 3; ++k) {
            const gp_Pnt& a = v[k];
            const gp_Pnt& b = v[(k + 1) % 3];
            const double da = a.Z() - z, db = b.Z() - z;
            if ((da < 0 && db > 0) || (da > 0 && db < 0)) {
                const double s = da / (da - db);
                hits.emplace_back(a.X() + s * (b.X() - a.X()), a.Y() + s * (b.Y() - a.Y()));
            } else if (da == 0 && db != 0) {
                hits.emplace_back(a.X(), a.Y());
            }
        }
        if (hits.size() == 2 && !(key(hits[0]) == key(hits[1])))
            segments.emplace_back(hits[0], hits[1]);
    }
    // 2. Chain the segments into closed loops.
    std::unordered_multimap<P, size_t, PH> byEnd;
    for (size_t i = 0; i < segments.size(); ++i) {
        byEnd.emplace(key(segments[i].first), i);
        byEnd.emplace(key(segments[i].second), i);
    }
    std::vector<char> used(segments.size(), 0);
    std::vector<std::vector<gp_Pnt2d>> loops;
    for (size_t start = 0; start < segments.size(); ++start) {
        if (used[start])
            continue;
        used[start] = 1;
        std::vector<gp_Pnt2d> loop{segments[start].first, segments[start].second};
        const P first = key(loop.front());
        bool closed = false;
        while (true) {
            const P end = key(loop.back());
            if (end == first) {
                loop.pop_back();
                closed = true;
                break;
            }
            bool extended = false;
            auto range = byEnd.equal_range(end);
            for (auto it = range.first; it != range.second; ++it) {
                if (used[it->second])
                    continue;
                used[it->second] = 1;
                const auto& sg = segments[it->second];
                loop.push_back(key(sg.first) == end ? sg.second : sg.first);
                extended = true;
                break;
            }
            if (!extended)
                break;
        }
        if (!closed || loop.size() < 3)
            continue;
        // 3. Drop points on straight runs (the triangulation splits faces).
        std::vector<gp_Pnt2d> clean;
        for (size_t i = 0; i < loop.size(); ++i) {
            const gp_Pnt2d& a = loop[(i + loop.size() - 1) % loop.size()];
            const gp_Pnt2d& b = loop[i];
            const gp_Pnt2d& d = loop[(i + 1) % loop.size()];
            const double cross = (b.X() - a.X()) * (d.Y() - b.Y()) - (b.Y() - a.Y()) * (d.X() - b.X());
            if (std::abs(cross) > 1e-10)
                clean.push_back(b);
        }
        if (clean.size() >= 3)
            loops.push_back(std::move(clean));
    }
    return loops;
}

void ElementBatch::computeEdges()
{
    if (!m_edgeOffsets.empty())
        return;
    m_edgeOffsets.reserve(size_t(elementCount()) + 1);
    m_edgeOffsets.push_back(0);
    for (int i = 0; i < elementCount(); ++i) {
        for (const auto& [a, b] : featureEdges(m_chunk, i)) {
            m_edgePoints.push_back(a);
            m_edgePoints.push_back(b);
        }
        m_edgeOffsets.push_back(uint32_t(m_edgePoints.size() / 2));
    }
}

void ElementBatch::addTriangles(const Handle(Prs3d_Presentation)& prs, int mode)
{
    int tris = 0;
    for (int i = 0; i < elementCount(); ++i)
        if (!isHidden(i))
            tris += int(m_chunk.toff[size_t(i) + 1] - m_chunk.toff[size_t(i)]);
    if (tris == 0)
        return;
    const bool colours = mode == Shaded || mode == Ids;
    Handle(Graphic3d_ArrayOfTriangles) arr = new Graphic3d_ArrayOfTriangles(
        tris * 3, 0, Graphic3d_ArrayFlags_VertexNormal | (colours ? Graphic3d_ArrayFlags_VertexColor : 0));
    for (int i = 0; i < elementCount(); ++i) {
        if (isHidden(i))
            continue;
        if (mode == Ids) {
            const auto rgb = idRgb(m_idBase + i + 1);
            // Linear RGB: the offscreen buffer stores these values as they are (no sRGB encoding).
            const Quantity_Color id(rgb[0] / 255.0, rgb[1] / 255.0, rgb[2] / 255.0, Quantity_TOC_RGB);
            addElement(*arr, i, true, &id);
        } else {
            addElement(*arr, i, colours);
        }
    }
    Handle(Graphic3d_Group) group = prs->NewGroup();
    Handle(Graphic3d_AspectFillArea3d) aspect = new Graphic3d_AspectFillArea3d(*myDrawer->ShadingAspect()->Aspect());
    if (mode == Shaded) {
        // A colour-driven ("aspect") material, so per-vertex palette colours are used. The AIS
        // default (brass) is a physical material that ignores vertex colours.
        Graphic3d_MaterialAspect material(Graphic3d_NameOfMaterial_Plastified);
        material.SetSpecularColor(Quantity_Color(0.08, 0.08, 0.08, Quantity_TOC_RGB));
        aspect->SetFrontMaterial(material);
        aspect->SetBackMaterial(material);
        aspect->SetInteriorColor(Quantity_NOC_WHITE);
    } else if (mode == Ids) { // exact flat colours: no lighting
        aspect->SetShadingModel(Graphic3d_TypeOfShadingModel_Unlit);
    } else { // lines only: faces just hide what is behind them
        aspect->SetShadingModel(Graphic3d_TypeOfShadingModel_Unlit);
        aspect->SetInteriorColor(s_background);
    }
    // Push faces back a little so their border lines are drawn on top, not half hidden.
    aspect->SetPolygonOffsets(Aspect_POM_Fill, 1.0f, 1.0f);
    group->SetGroupPrimitivesAspect(aspect);
    group->AddPrimitiveArray(arr);
}

void ElementBatch::addLines(const Handle(Prs3d_Presentation)& prs, const Quantity_Color& color)
{
    if (!m_showEdges)
        return;
    computeEdges();
    int segments = 0;
    for (int i = 0; i < elementCount(); ++i)
        if (!isHidden(i))
            segments += int(m_edgeOffsets[size_t(i) + 1] - m_edgeOffsets[size_t(i)]);
    if (segments == 0)
        return;
    Handle(Graphic3d_ArrayOfSegments) arr = new Graphic3d_ArrayOfSegments(segments * 2);
    for (int i = 0; i < elementCount(); ++i) {
        if (isHidden(i))
            continue;
        for (uint32_t s = m_edgeOffsets[size_t(i)]; s < m_edgeOffsets[size_t(i) + 1]; ++s) {
            arr->AddVertex(m_edgePoints[2 * s]);
            arr->AddVertex(m_edgePoints[2 * s + 1]);
        }
    }
    Handle(Graphic3d_Group) group = prs->NewGroup();
    group->SetGroupPrimitivesAspect(new Graphic3d_AspectLine3d(color, Aspect_TOL_SOLID, 1.0));
    group->AddPrimitiveArray(arr);
}

void ElementBatch::Compute(const Handle(PrsMgr_PresentationManager)&, const Handle(Prs3d_Presentation)& prs,
    const int mode)
{
    switch (mode) {
    case Shaded:
        addTriangles(prs, Shaded);
        addLines(prs, Quantity_Color(0.22, 0.22, 0.24, Quantity_TOC_RGB));
        break;
    case LinesOnly:
        addTriangles(prs, LinesOnly);
        addLines(prs, Quantity_Color(0.05, 0.05, 0.05, Quantity_TOC_RGB));
        break;
    case Ids:
        addTriangles(prs, Ids); // no lines: they would cover thin elements' ids
        break;
    default:
        break;
    }
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

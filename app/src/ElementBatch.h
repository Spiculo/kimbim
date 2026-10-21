// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once

#include <array>
#include <optional>
#include <utility>
#include <gp_Dir.hxx>
#include <gp_Pln.hxx>
#include <gp_Pnt.hxx>
#include <gp_Pnt2d.hxx>
#include <TopoDS_Shape.hxx>
#include <Quantity_Color.hxx>
#include <AIS_InteractiveObject.hxx>
#include <Bnd_Box.hxx>
#include <Graphic3d_ArrayOfTriangles.hxx>
#include <SelectMgr_EntityOwner.hxx>

#include <QHash>
#include <QString>

#include <vector>

#include "MeshChunk.h"

namespace kimbim {

class ElementBatch;

// A border-line style (D73): colour, width in pixels and a 16-bit screen pattern (0xFFFF = solid).
struct BatchLine {
    Quantity_Color color;
    float width = 1.0f;
    uint16_t pattern = 0xFFFF;
};

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
    // Display modes: shaded faces with border lines; element ids as flat colours (visibility
    // queries, never shown); lines only (hidden-line: faces in the background colour, black lines).
    enum Mode { Shaded = 0, Ids = 1, LinesOnly = 2 };

    explicit ElementBatch(MeshChunk chunk);

    // Border lines of one element: boundary edges and creases sharper than angleDeg. Triangulation
    // diagonals and coplanar seams are skipped; unwelded meshes pair up by vertex position.
    static std::vector<std::pair<gp_Pnt, gp_Pnt>> featureEdges(const MeshChunk& chunk, int element, double angleDeg = 30.0);
    // The same, minus the edges whose faces all face away from `toward`: a section/elevation projection
    // does not show a solid's back edges through it.
    static std::vector<std::pair<gp_Pnt, gp_Pnt>> featureEdgesFacing(const MeshChunk& chunk, int element,
        const gp_Dir& toward, double angleDeg = 30.0);
    // The element's section by the horizontal plane at z: closed outlines in plan (x, y).
    static std::vector<std::vector<gp_Pnt2d>> sectionLoops(const MeshChunk& chunk, int element, double z);
    std::vector<std::vector<gp_Pnt2d>> sectionLoops(int element, double z) const { return sectionLoops(m_chunk, element, z); }
    // The element's section by an arbitrary plane: closed 3D outlines (used to draw a section drawing).
    static std::vector<std::vector<gp_Pnt>> sectionLoopsPlane(const MeshChunk& chunk, int element, const gp_Pln& plane);
    // A triangulated face for one element, for OCCT's polygon hidden-line removal (section drawings).
    static TopoDS_Shape meshFace(const MeshChunk& chunk, int element);
    static void setBackground(const Quantity_Color& color) { s_background = color; }
    // Previews skip border lines (computing them on every mouse move made drawing lag).
    void setShowEdges(bool show) { m_showEdges = show; }

    // Element ids as colours (Ids mode): 6 bits per channel stored as value*4+2, so +-1 of colour
    // rounding still decodes; 0 and off-grid colours (background, lines) decode to -1.
    static std::array<int, 3> idRgb(int id)
    {
        return {((id >> 12) & 63) * 4 + 2, ((id >> 6) & 63) * 4 + 2, (id & 63) * 4 + 2};
    }
    static int idFromRgb(int r, int g, int b)
    {
        auto channel = [](int c) { return c < 0 || c > 255 || c % 4 == 0 ? -1 : c >> 2; };
        const int cr = channel(r), cg = channel(g), cb = channel(b);
        if (cr < 0 || cg < 0 || cb < 0)
            return -1;
        const int id = (cr << 12) | (cg << 6) | cb;
        return id == 0 ? -1 : id;
    }
    static constexpr int maxId() { return (1 << 18) - 1; }
    // First id of this batch's elements minus one: element i draws as id idBase() + i + 1.
    void setIdBase(int base) { m_idBase = base; }
    int idBase() const { return m_idBase; }

    int elementCount() const { return m_chunk.elementCount(); }
    int triangleCount() const { return m_chunk.triangleCount(); }
    const MeshChunk& chunk() const { return m_chunk; }
    QString guid(int i) const { return m_chunk.guids.at(i); }
    QString type(int i) const { return m_chunk.types.at(i); }
    int indexOf(const QString& guid) const { return m_index.value(guid, -1); }

    void setHidden(int i, bool hidden);
    // Hidden by the user (H / isolate), by its layer (a view's layer state) or by the purpose's visibility
    // set (D73); any of them hides it, and Show all only clears the first.
    bool isHidden(int i) const
    {
        return m_hidden[size_t(i)] != 0 || m_layerHidden[size_t(i)] != 0 || m_graphicsHidden[size_t(i)] != 0;
    }
    void setGraphicsHidden(int i, bool hidden);
    bool isGraphicsHidden(int i) const { return m_graphicsHidden[size_t(i)] != 0; }
    // D73: the element's border-line style (nullopt: the display mode's default line), and an override
    // surface colour and transparency (0 = opaque). Redisplay after.
    void setLineStyle(int i, std::optional<BatchLine> line) { m_line[size_t(i)] = line; }
    const std::optional<BatchLine>& lineStyle(int i) const { return m_line[size_t(i)]; }
    const std::optional<Quantity_Color>& surface(int i) const { return m_surface[size_t(i)]; }
    double transparency(int i) const { return m_alpha[size_t(i)]; }
    void setSurface(int i, std::optional<Quantity_Color> color, double transparency = 0.0)
    {
        m_surface[size_t(i)] = color;
        m_alpha[size_t(i)] = transparency;
    }
    // The colour the element is shaded with: Compare's override, then the surface override, then the
    // calm palette by IFC class.
    Quantity_Color surfaceColor(int i) const;
    // D96: one triangle's colour and transparency (t is the chunk-wide triangle index): an element
    // override (Compare, a graphics rule) colours every face; otherwise the face's own surface (its
    // material), else the class colour.
    Quantity_Color triangleColor(int i, uint32_t t) const;
    double triangleTransparency(int i, uint32_t t) const;
    // The visible elements' border lines grouped by style (one OCCT group each); `fallback` colours the
    // unstyled ones (1 px, solid).
    struct LineBucket {
        BatchLine line;
        std::vector<int> elements;
    };
    std::vector<LineBucket> lineBuckets(const Quantity_Color& fallback) const;
    void setLayerHidden(int i, bool hidden);
    bool isLayerHidden(int i) const { return m_layerHidden[size_t(i)] != 0; }
    // Locked by its layer: shown, but not selectable.
    void setLocked(int i, bool locked) { m_locked[size_t(i)] = locked ? 1 : 0; }
    bool isLocked(int i) const { return m_locked[size_t(i)] != 0; }
    // A retired element was replaced or deleted by an edit: hidden for good (never shown again).
    void retire(int i);
    bool isRetired(int i) const { return m_retired[size_t(i)] != 0; }
    // A colour that replaces the IFC-class colour (Compare); nullopt restores it. Redisplay after.
    void setColorOverride(int i, std::optional<Quantity_Color> color) { m_override[size_t(i)] = color; }
    std::optional<Quantity_Color> colorOverride(int i) const { return m_override[size_t(i)]; }
    int visibleCount() const { return m_visible; }

    Bnd_Box elementBounds(int i) const;
    Bnd_Box visibleBounds() const;

    Handle(ElementOwner) owner(int i);
    // Flat-shaded triangles of one element (used for highlights).
    Handle(Graphic3d_ArrayOfTriangles) elementTriangles(int i) const;

    bool AcceptDisplayMode(const int mode) const override { return mode >= Shaded && mode <= LinesOnly; }
    void Compute(const Handle(PrsMgr_PresentationManager)& pm, const Handle(Prs3d_Presentation)& prs,
        const int mode) override;
    void ComputeSelection(const Handle(SelectMgr_Selection)& selection, const int mode) override;

private:
    // Appends element i's triangles; with `onlyAlpha` only those whose transparency is that value.
    void addElement(Graphic3d_ArrayOfTriangles& out, int i, bool withColors, const Quantity_Color* fixed = nullptr,
        std::optional<double> onlyAlpha = std::nullopt) const;

    MeshChunk m_chunk;
    QHash<QString, int> m_index;
    std::vector<char> m_hidden;
    std::vector<char> m_layerHidden;
    std::vector<char> m_locked;
    void updateVisible(int i, bool wasHidden);
    std::vector<char> m_retired;
    std::vector<std::optional<Quantity_Color>> m_override;
    std::vector<char> m_graphicsHidden;
    std::vector<std::optional<BatchLine>> m_line;
    std::vector<std::optional<Quantity_Color>> m_surface;
    std::vector<double> m_alpha;
    int m_visible = 0;
    std::vector<Handle(ElementOwner)> m_owners;
    Handle(Graphic3d_ArrayOfTriangles) m_pickArray; // indexed positions for Select3D_SensitivePrimitiveArray
    void computeEdges();
    void addTriangles(const Handle(Prs3d_Presentation)& prs, int mode);
    void addLines(const Handle(Prs3d_Presentation)& prs, const Quantity_Color& color);
    std::vector<gp_Pnt> m_edgePoints;    // segment end points of all elements' border lines
    std::vector<uint32_t> m_edgeOffsets; // per element: first segment, one past the last (size n+1)
    static Quantity_Color s_background;
    int m_idBase = 0;
    bool m_showEdges = true;
};

} // namespace kimbim

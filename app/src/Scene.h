// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once

#include <AIS_InteractiveContext.hxx>
#include <V3d_DirectionalLight.hxx>
#include <V3d_View.hxx>
#include <V3d_Viewer.hxx>

#include <QColor>
#include <QHash>
#include <QObject>
#include <QSet>
#include <QString>

#include <vector>

#include "ElementBatch.h"
#include "Graphics.h"

namespace kimbim {

// The loaded model as OCCT shows it (D71): one viewer and interactive context, the element batches,
// the selection, element colours and layer state. Each tab's Viewport is one V3d_View of it, so a 3D
// tab and plan tabs show one loaded model and select together.
class Scene : public QObject {
    Q_OBJECT
public:
    explicit Scene(QObject* parent = nullptr);

    const Handle(V3d_Viewer)& viewer() const { return m_viewer; }
    const Handle(AIS_InteractiveContext)& context() const { return m_context; }
    Handle(V3d_View) createView();                 // emits viewsChanged()
    void removeView(const Handle(V3d_View)& view); // emits viewsChanged()
    void changed();                                // emits redrawRequested(): every view repaints
    void elementsChanged();                        // elementsAltered() (views rebuild their poché), then changed()

    // Shared model state, used by the views (was in Viewport).
    struct Loc {
        int batch;
        int index;
    };
    std::vector<Handle(ElementBatch)> batches;
    QHash<QString, Loc> locate;
    QHash<QString, QColor> colors;
    QSet<QString> layerHidden, layerLocked;
    bool linesOnly = false;
    bool whiteModel = false; // D96: Archicad's white model 3D style (surfaces white, glass kept)
    // D96: the display mode the 3D style gives every batch (lines only > white model > shaded).
    int displayMode() const
    {
        return linesOnly ? ElementBatch::LinesOnly : whiteModel ? ElementBatch::White : ElementBatch::Shaded;
    }
    void setShadows(bool on); // D96: the sun casts shadows (shadow map) in shaded and white views
    // D96: where the sun is (a unit vector towards it, world plan axes); below the horizon it only lights.
    void setSunDirection(double x, double y, double z);
    gp_Dir sunDirection() const;
    bool shadows() const { return m_shadows; }
    Graphics graphics;        // D73: the current purpose, resolved
    bool trueWeights = false; // D73: View > True line weights
    bool quietSelection = false;
    int nextIdBase = 0;
    std::vector<int> idBases; // per batch, for decoding ids

signals:
    void redrawRequested();
    void elementsAltered();
    void viewsChanged();

private:
    Handle(V3d_Viewer) m_viewer;
    Handle(AIS_InteractiveContext) m_context;
    Handle(V3d_DirectionalLight) m_sun;
    bool m_shadows = false;
};

} // namespace kimbim

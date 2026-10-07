// SPDX-License-Identifier: GPL-3.0-or-later
#include "Scene.h"

#include <Aspect_DisplayConnection.hxx>
#include <OpenGl_GraphicDriver.hxx>
#include <Prs3d_Drawer.hxx>
#include <Standard_Failure.hxx>
#include <V3d_AmbientLight.hxx>
#include <V3d_DirectionalLight.hxx>

#include <QThread>

namespace kimcad {

namespace {

// One display connection per process, shared by every view (on X11 each one is a connection to the X
// server). Opening a connection can fail for a moment on a busy server (CI's Xvfb did, aborting the
// app with an uncaught OCCT exception), so it is retried a few times before giving up.
Handle(Aspect_DisplayConnection) sharedDisplay()
{
    static Handle(Aspect_DisplayConnection) display;
    if (!display.IsNull())
        return display;
    for (int attempt = 0;; ++attempt) {
        try {
            display = new Aspect_DisplayConnection();
            return display;
        } catch (const Standard_Failure& e) {
            if (attempt >= 9)
                throw;
            qWarning("KIMCAD: no display connection yet (%s), retrying", e.what());
            QThread::msleep(200);
        }
    }
}

} // namespace

Scene::Scene(QObject* parent)
    : QObject(parent)
{
    Handle(OpenGl_GraphicDriver) driver = new OpenGl_GraphicDriver(sharedDisplay(), false);
    // No vsync by default: the view only redraws when something changes, so this never spins, and a
    // frame takes ~1 ms. With vsync each redraw blocked the UI until the next screen refresh (33 ms
    // on 30 Hz laptop panels), so drawing tools lagged behind the mouse (owner feedback).
    // KIMCAD_VSYNC=1 turns it back on (e.g. if orbiting tears on some screen).
    if (qEnvironmentVariableIntValue("KIMCAD_VSYNC") != 1)
        driver->ChangeOptions().swapInterval = 0;
    m_viewer = new V3d_Viewer(driver);
    // A fixed "sun" from the south-east above plus soft ambient and fill. A headlight along the
    // isometric view direction lights the top and both visible sides equally, so boxes look flat.
    Handle(V3d_AmbientLight) ambient = new V3d_AmbientLight(Quantity_Color(0.42, 0.42, 0.42, Quantity_TOC_RGB));
    Handle(V3d_DirectionalLight) sun = new V3d_DirectionalLight(gp_Dir(-0.3, 0.5, -0.8), Quantity_NOC_WHITE);
    sun->SetIntensity(0.75f);
    Handle(V3d_DirectionalLight) fill = new V3d_DirectionalLight(gp_Dir(0.6, -0.25, -0.35), Quantity_NOC_WHITE);
    fill->SetIntensity(0.25f);
    for (const Handle(V3d_Light)& light : {Handle(V3d_Light)(ambient), Handle(V3d_Light)(sun), Handle(V3d_Light)(fill)})
        m_viewer->AddLight(light);
    m_viewer->SetLightOn();
    m_context = new AIS_InteractiveContext(m_viewer);
    m_context->HighlightStyle(Prs3d_TypeOfHighlight_Dynamic)->SetColor(Quantity_Color(0.98, 0.75, 0.20, Quantity_TOC_RGB));
    m_context->HighlightStyle(Prs3d_TypeOfHighlight_Selected)->SetColor(Quantity_Color(0.15, 0.50, 0.95, Quantity_TOC_RGB));
}

Handle(V3d_View) Scene::createView()
{
    Handle(V3d_View) view = m_viewer->CreateView();
    emit viewsChanged();
    return view;
}

void Scene::removeView(const Handle(V3d_View)& view)
{
    if (!view.IsNull())
        view->Remove();
    emit viewsChanged();
}

void Scene::changed()
{
    emit redrawRequested();
}

void Scene::elementsChanged()
{
    emit elementsAltered();
    emit redrawRequested();
}

} // namespace kimcad

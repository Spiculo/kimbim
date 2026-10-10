// SPDX-License-Identifier: GPL-3.0-or-later
// D85: underlays: placement maths, the snap index, and in the app placing a DXF survey and an image on
// a level, snapping to the survey, calibrating and moving it by clicks, hiding it with its layer.
#include <QDateTime>
#include <QDir>
#include <QElapsedTimer>
#include <QFile>
#include <QImage>
#include <QJsonArray>
#include <QJsonDocument>
#include <QStandardPaths>
#include <QTemporaryDir>
#include <QtTest>

#include <cmath>

#include "LevelsBar.h"
#include "MainWindow.h"
#include "PythonEngine.h"
#include "Snapper.h"
#include "TwoPointTool.h"
#include "Underlay.h"
#include "UnderlayDialogs.h"
#include "Viewport.h"

using kimcad::Snap;
using kimcad::UnderlayPlacement;
using kimcad::UnderlaySnapIndex;

namespace {

QJsonObject engine(const char* fn, const QStringList& args = {})
{
    QString error;
    return kimcad::PythonEngine::instance().callJson(fn, args, &error).object();
}

bool close(QPointF a, QPointF b, double tol = 1e-6)
{
    return std::hypot(a.x() - b.x(), a.y() - b.y()) <= tol;
}

// A minimal ASCII DXF in millimetres: a 4 x 3 m rectangle and its diagonal, plus `extra` lines.
void writeSurvey(const QString& path, int extra = 0)
{
    // A comment that differs every run: a new file, never the segment cache of an earlier run.
    QString s = QStringLiteral("999\n%1\n").arg(QDateTime::currentMSecsSinceEpoch());
    s += QStringLiteral("0\nSECTION\n2\nHEADER\n9\n$INSUNITS\n70\n4\n0\nENDSEC\n0\nSECTION\n2\nENTITIES\n");
    auto line = [&](double x1, double y1, double x2, double y2) {
        s += QStringLiteral("0\nLINE\n8\n0\n10\n%1\n20\n%2\n30\n0\n11\n%3\n21\n%4\n31\n0\n").arg(x1).arg(y1).arg(x2).arg(y2);
    };
    line(0, 0, 4000, 0);
    line(4000, 0, 4000, 3000);
    line(4000, 3000, 0, 3000);
    line(0, 3000, 0, 0);
    line(0, 0, 4000, 3000);
    for (int i = 0; i < extra; ++i)
        line(10000 + i * 5.0, 0, 10000 + i * 5.0, 2000 + i % 9);
    s += QStringLiteral("0\nENDSEC\n0\nEOF\n");
    QFile f(path);
    QVERIFY(f.open(QIODevice::WriteOnly));
    f.write(s.toLatin1());
}

} // namespace

class TestUnderlays : public QObject {
    Q_OBJECT
private slots:
    void initTestCase()
    {
        QStandardPaths::setTestModeEnabled(true);
        QString error;
        QVERIFY2(kimcad::PythonEngine::instance().start(&error), qPrintable(error));
        QVERIFY(m_data.isValid());
        engine("set_app_paths", {m_data.path()});
    }

    void placementMaths()
    {
        UnderlayPlacement p{QPointF(100, 50), QPointF(2, 3), 90.0, 0.01, false};
        QVERIFY(close(p.toWorld(QPointF(100, 50)), QPointF(2, 3)));
        QVERIFY(close(p.toWorld(QPointF(200, 50)), QPointF(2, 4))); // 1 m along x, turned to +y
        QVERIFY(close(p.toDrawing(p.toWorld(QPointF(37, -12))), QPointF(37, -12)));
        // images and PDF pages: rows run down
        UnderlayPlacement r{QPointF(0, 600), QPointF(0, 0), 0.0, 0.001, true};
        QVERIFY(close(r.toWorld(QPointF(0, 0)), QPointF(0, 0.6))); // the top left corner is up
        // two-point calibration: a stays, a..b becomes 8 m
        const UnderlayPlacement c = p.calibrated(QPointF(2, 4), QPointF(2, 6), 8.0);
        QCOMPARE(c.scale, 0.04);
        QVERIFY(close(c.toWorld(QPointF(200, 50)), QPointF(2, 4)));
        QVERIFY(close(c.toWorld(QPointF(300, 50)), QPointF(2, 8)));
        QVERIFY(close(p.moved(QPointF(1, 1)).at, QPointF(3, 4)));
        const UnderlayPlacement t = p.rotated(QPointF(0, 0), 90);
        QCOMPARE(t.rotation, 180.0);
        QVERIFY(close(t.at, QPointF(-3, 2)));
    }

    void snapIndexPointsAndPriority()
    {
        auto index = std::make_shared<UnderlaySnapIndex>();
        index->addSegment(QPointF(0, 0), QPointF(4, 0));
        index->addSegment(QPointF(0, 0), QPointF(4, 3));
        index->addSegment(QPointF(2, -1), QPointF(2, 1));
        index->build();
        QPointF q;
        QVERIFY(index->endpoint(QPointF(3.98, 0.03), 0.05, &q) && close(q, QPointF(4, 0)));
        QVERIFY(index->midpoint(QPointF(2.02, 1.48), 0.05, &q) && close(q, QPointF(2, 1.5)));
        QVERIFY(index->crossing(QPointF(2.03, 0.02), 0.05, &q) && close(q, QPointF(2, 0)));
        QVERIFY(index->onLine(QPointF(3, 0.02), 0.05, &q) && close(q, QPointF(3, 0)));
        QVERIFY(!index->endpoint(QPointF(10, 10), 0.05, &q));

        kimcad::Snapper s;
        s.setUnderlays(index);
        Snap snap = s.snap(QPointF(3.98, 0.03), 0.05);
        QCOMPARE(snap.kind, Snap::UnderlayEnd);
        QCOMPARE(s.snap(QPointF(2.01, 0.01), 0.05).kind, Snap::UnderlayCross);
        QCOMPARE(s.snap(QPointF(3.0, 0.02), 0.05).kind, Snap::OnUnderlay);
        // a wall's end wins over the underlay's
        s.setWalls({{QStringLiteral("w"), QPointF(3.99, 0.0), QPointF(3.99, 5.0), 0.2}});
        snap = s.snap(QPointF(3.98, 0.03), 0.05);
        QCOMPARE(snap.kind, Snap::Endpoint);
        QCOMPARE(snap.wallGuid, QStringLiteral("w"));
    }

    void linesFromPythonParts()
    {
        const float coords[8] = {0, 0, 10, 0, 10, 0, 10, 5};
        const unsigned char rgb[6] = {255, 0, 0, 0, 0, 0};
        QList<QByteArray> parts{R"({"ok": true, "count": 2, "origin": [512000.0, 4012000.0]})",
            QByteArray(reinterpret_cast<const char*>(coords), sizeof coords), QByteArray(reinterpret_cast<const char*>(rgb), sizeof rgb)};
        const auto lines = kimcad::UnderlayLines::fromParts(parts);
        QVERIFY(lines);
        QCOMPARE(lines->count(), 2);
        QCOMPARE(lines->origin, QPointF(512000, 4012000));
        parts[1].chop(4);
        QVERIFY(!kimcad::UnderlayLines::fromParts(parts));
        QCOMPARE(kimcad::underlayColour(Qt::red, true, QColor(), 1.0, Qt::white), QColor::fromRgbF(0.299f, 0.299f, 0.299f));
        QCOMPARE(kimcad::underlayColour(Qt::black, false, QColor(), 0.5, Qt::white).red(), 128);
        QCOMPARE(kimcad::PlaceUnderlayDialog::rasterScale("pdf", 100, 0), 0.0254 / 72 * 100);
        QCOMPARE(kimcad::PlaceUnderlayDialog::rasterScale("image", 50, 200), 0.0254 / 200 * 50);
    }

    void placeSnapCalibrateMoveAndHide()
    {
        QTemporaryDir dir;
        const QString dxf = dir.filePath("survey.dxf");
        writeSurvey(dxf);
        kimcad::MainWindow w(nullptr, true);
        QVERIFY(w.newProject());
        const QString storey = w.levelsBar()->activeStorey();
        kimcad::Viewport* plan = w.openPlanTab(storey);
        QVERIFY(plan);
        const QJsonObject r = w.placeUnderlay(dxf, {});
        QVERIFY2(r.value("ok").toBool(), qPrintable(r.value("error").toString()));
        const QString id = r.value("underlay").toObject().value("id").toString();
        QCOMPARE(plan->underlayCount(), 1);
        QCOMPARE(plan->underlaySegmentCount(), 5);
        QCOMPARE(w.modelView()->underlayCount(), 0); // not "also in 3D"
        QVERIFY(w.isDirty());                         // the settings changed
        // every drawing tool snaps to the survey: its corner, the diagonal's middle
        QVERIFY(w.underlaySnapIndex());
        Snap s = w.twoPointTool()->snapper().snap(QPointF(3.99, 0.02), 0.05);
        QCOMPARE(s.kind, Snap::UnderlayEnd);
        QVERIFY(close(s.point, QPointF(4, 0)));
        s = w.twoPointTool()->snapper().snap(QPointF(2.01, 1.49), 0.05);
        QCOMPARE(s.kind, Snap::UnderlayMid);

        // calibrate: the survey was really drawn at half size, so its 4 m side is 8 m
        w.startUnderlayPick(id, kimcad::UnderlayPicker::Calibrate);
        QVERIFY(w.underlayPicker()->isActive());
        QVERIFY(w.viewport()->isDrawingMode());
        emit w.viewport()->workPointClicked(QPointF(0.01, -0.01), 0.05, Qt::NoModifier); // snaps to 0,0
        QCOMPARE(w.underlayPicker()->stage(), 1);
        QVERIFY(w.underlayPicker()->click(QPointF(3.98, 0.01), 0.05, false));        // snaps to 4,0
        QVERIFY(w.finishUnderlayPick(8.0));
        QVERIFY(!w.underlayPicker()->isActive());
        QVERIFY(!w.viewport()->isDrawingMode());
        QJsonObject u = engine("underlays", {storey}).value("underlays").toArray().at(0).toObject();
        QCOMPARE(u.value("scale").toDouble(), 0.002);
        QCOMPARE(u.value("x").toDouble(), 0.0);
        s = w.twoPointTool()->snapper().snap(QPointF(7.98, 0.01), 0.05);
        QCOMPARE(s.kind, Snap::UnderlayEnd);
        QVERIFY(close(s.point, QPointF(8, 0)));

        // move by two clicks
        w.startUnderlayPick(id, kimcad::UnderlayPicker::Move);
        QVERIFY(!w.underlayPicker()->click(QPointF(0, 0), 0.05, false));
        QVERIFY(w.underlayPicker()->click(QPointF(1.0, 3.0), 0.001, false));
        QVERIFY(w.finishUnderlayPick());
        u = engine("underlays", {storey}).value("underlays").toArray().at(0).toObject();
        QCOMPARE(u.value("x").toDouble(), 1.0);
        QCOMPARE(u.value("y").toDouble(), 3.0);
        QVERIFY(close(w.twoPointTool()->snapper().snap(QPointF(8.99, 3.01), 0.05).point, QPointF(9.0, 3.0)));

        // Esc cancels a pick
        w.startUnderlayPick(id, kimcad::UnderlayPicker::Move);
        emit w.viewport()->drawingEnded();
        QVERIFY(!w.underlayPicker()->isActive());

        // its layer hides it (and its snap points)
        w.setLayerVisible(QStringLiteral("Underlays"), false);
        QCOMPARE(plan->underlayCount(), 0);
        QVERIFY(!w.underlaySnapIndex());
        w.setLayerVisible(QStringLiteral("Underlays"), true);
        QCOMPARE(plan->underlayCount(), 1);

        // an image: a textured quad
        QImage img(64, 32, QImage::Format_RGB32);
        img.fill(Qt::darkCyan);
        QVERIFY(img.save(dir.filePath("scan.png")));
        QVERIFY(w.placeUnderlay(dir.filePath("scan.png"), {}).value("ok").toBool());
        QCOMPARE(plan->underlayCount(), 2);
        // also in 3D
        QVERIFY(engine("set_underlay", {id, R"({"show_3d": true})"}).value("ok").toBool());
        w.refreshUnderlays();
        QCOMPARE(w.modelView()->underlayCount(), 1);
    }

    void largeSurveyDrawsFast()
    {
        QTemporaryDir dir;
        const QString dxf = dir.filePath("big.dxf");
        writeSurvey(dxf, 50000);
        kimcad::MainWindow w(nullptr, true);
        QVERIFY(w.newProject());
        kimcad::Viewport* plan = w.openPlanTab(w.levelsBar()->activeStorey());
        QElapsedTimer t;
        t.start();
        const QJsonObject probe = engine("underlay_probe", {dxf}); // what the dialog does first: reads the DXF
        const qint64 read = t.elapsed();
        QCOMPARE(probe.value("segments").toInt(), 50005);
        t.restart();
        QVERIFY(w.placeUnderlay(dxf, {}).value("ok").toBool());
        const qint64 placed = t.elapsed();
        QCOMPARE(plan->underlaySegmentCount(), 50005);
        qInfo("50 005-line DXF: read %lld ms, placed (copy + segments to C++ + presentation + snap index) %lld ms",
            static_cast<long long>(read), static_cast<long long>(placed));
        t.restart();
        w.refreshUnderlays(); // cached: no new presentation, no new snap index
        const qint64 again = t.elapsed();
        t.restart();
        QVERIFY(engine("set_underlay", {engine("underlays").value("underlays").toArray().at(0).toObject().value("id").toString(),
                                        R"({"x": 3.0, "rotation": 10})"}).value("ok").toBool());
        w.refreshUnderlays(); // a move: same presentation, new transformation; new snap index
        const qint64 moved = t.elapsed();
        qInfo("refresh %lld ms, move %lld ms",
            static_cast<long long>(again), static_cast<long long>(moved));
        QVERIFY(again < 2000);
    }

private:
    QTemporaryDir m_data;
};

QTEST_MAIN(TestUnderlays)
#include "test_underlays.moc"

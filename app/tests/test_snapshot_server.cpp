// SPDX-License-Identifier: GPL-3.0-or-later
// D102: the windowless snapshot server (kimbim-app --snapshot-server) driven as the agent worker
// does: JSON lines on stdin, one JSON line back per request, exit on EOF. Needs a real OpenGL
// context (label "gui"); the helper never shows a window.
#include <QFile>
#include <QImage>
#include <QJsonArray>
#include <QJsonDocument>
#include <QJsonObject>
#include <QProcess>
#include <QRegularExpression>
#include <QSet>
#include <QTemporaryDir>
#include <QtTest>

namespace {

// The house's walls, in file order (tools/make_house.py: Level 1's four, then Level 2's).
QStringList wallGuids(const QString& ifc)
{
    QFile f(ifc);
    if (!f.open(QIODevice::ReadOnly))
        return {};
    const QString text = QString::fromUtf8(f.readAll());
    QStringList out;
    const QRegularExpression re(QStringLiteral("=IFCWALL\\('([^']{22})'"));
    for (auto it = re.globalMatch(text); it.hasNext();)
        out << it.next().captured(1);
    return out;
}

int distinctColours(const QImage& image)
{
    QSet<QRgb> seen;
    for (int y = 0; y < image.height(); ++y)
        for (int x = 0; x < image.width(); ++x)
            seen.insert(image.pixel(x, y) & 0xffffff);
    return int(seen.size());
}

// Pixels of the colour as the renderer shades it: the same hue, saturated (lighting changes the
// brightness of a face, not its hue).
int pixelsLike(const QImage& image, const QColor& colour)
{
    int n = 0;
    for (int y = 0; y < image.height(); ++y)
        for (int x = 0; x < image.width(); ++x) {
            const QColor c = image.pixelColor(x, y).toHsv();
            if (c.hsvSaturation() >= 90 && c.value() >= 60 && std::abs(c.hsvHue() - colour.hsvHue()) <= 12)
                ++n;
        }
    return n;
}

// Pixels within `tolerance` (per channel) of `colour`.
int pixelsNear(const QImage& image, const QColor& colour, int tolerance)
{
    int n = 0;
    for (int y = 0; y < image.height(); ++y)
        for (int x = 0; x < image.width(); ++x) {
            const QColor c = image.pixelColor(x, y);
            if (std::abs(c.red() - colour.red()) <= tolerance && std::abs(c.green() - colour.green()) <= tolerance
                && std::abs(c.blue() - colour.blue()) <= tolerance)
                ++n;
        }
    return n;
}

} // namespace

class TestSnapshotServer : public QObject {
    Q_OBJECT
    QProcess m_server;
    QTemporaryDir m_tmp;

    QJsonObject request(const QJsonObject& req)
    {
        m_server.write(QJsonDocument(req).toJson(QJsonDocument::Compact) + '\n');
        while (!m_server.canReadLine())
            if (!m_server.waitForReadyRead(240000))
                return {{"ok", false}, {"error", "no reply"}};
        const QByteArray line = m_server.readLine().trimmed();
        const QJsonDocument doc = QJsonDocument::fromJson(line);
        if (!doc.isObject())
            return {{"ok", false}, {"error", QString::fromUtf8("not JSON: " + line)}};
        return doc.object();
    }

private slots:
    void initTestCase()
    {
        const QString app = qEnvironmentVariable("KIMBIM_APP");
        QVERIFY2(QFile::exists(app), qPrintable("KIMBIM_APP: " + app));
        QProcessEnvironment env = QProcessEnvironment::systemEnvironment();
        env.remove(QStringLiteral("QT_QPA_PLATFORM")); // the helper needs a real OpenGL window
        m_server.setProcessEnvironment(env);
        m_server.setProcessChannelMode(QProcess::SeparateChannels);
        m_server.setReadChannel(QProcess::StandardOutput);
        m_server.start(app, {QStringLiteral("--snapshot-server")});
        QVERIFY2(m_server.waitForStarted(), qPrintable(m_server.errorString()));
    }

    void cleanupTestCase()
    {
        m_server.closeWriteChannel(); // EOF: the server exits by itself
        const bool exited = m_server.state() == QProcess::NotRunning || m_server.waitForFinished(60000);
        if (!exited)
            m_server.kill();
        qInfo().noquote() << QString::fromUtf8(m_server.readAllStandardError()).right(2000);
        QVERIFY(exited);
        QCOMPARE(m_server.exitCode(), 0);
    }

    void badRequestsAnswerWithAnError()
    {
        const QJsonObject r = request({{"op", "fly"}});
        QCOMPARE(r.value("ok").toBool(true), false);
        QCOMPARE(r.value("error").toObject().value("code").toString(), QString("bad_request"));
        const QJsonObject early = request({{"op", "render3d"}, {"out", m_tmp.filePath("x.png")}});
        QCOMPARE(early.value("error").toObject().value("code").toString(), QString("not_loaded"));
    }

    void loadsTheHouse()
    {
        const QString house = qEnvironmentVariable("KIMBIM_HOUSE");
        QVERIFY2(QFile::exists(house), qPrintable("run `pixi run house` first: " + house));
        QFile settings(m_tmp.filePath("settings.json"));
        QVERIFY(settings.open(QIODevice::WriteOnly));
        settings.write(QJsonDocument(QJsonObject{{"length_unit", "mm"}}).toJson());
        settings.close();
        const QJsonObject r = request({{"op", "load"}, {"model", house}, {"settings", settings.fileName()}});
        QVERIFY2(r.value("ok").toBool(), QJsonDocument(r).toJson().constData());
        QVERIFY(r.value("elements").toInt() > 10);
        QCOMPARE(r.value("windows_on_screen").toInt(-1), 0); // the owner's desktop is left alone
    }

    void rendersIsoSouthEastAtTheExactSize()
    {
        const QString out = m_tmp.filePath("iso.png");
        const QJsonObject r = request({{"op", "render3d"}, {"out", out}, {"size", QJsonArray{800, 600}},
            {"camera", "iso-se"}, {"style", "shaded"}});
        QVERIFY2(r.value("ok").toBool(), QJsonDocument(r).toJson().constData());
        QCOMPARE(r.value("out").toString(), out);
        QVERIFY(r.value("framed").toInt() > 10);
        const QJsonObject camera = r.value("camera").toObject();
        QCOMPARE(camera.value("eye").toArray().size(), 3);
        QCOMPARE(camera.value("target").toArray().size(), 3);
        QCOMPARE(camera.value("up").toArray().size(), 3);
        // south-east: the eye is east (+x), south (-y) and above (+z) of the target
        const QJsonArray eye = camera.value("eye").toArray(), target = camera.value("target").toArray();
        QVERIFY(eye[0].toDouble() > target[0].toDouble());
        QVERIFY(eye[1].toDouble() < target[1].toDouble());
        QVERIFY(eye[2].toDouble() > target[2].toDouble());
        const QImage image(out);
        QCOMPARE(image.size(), QSize(800, 600));
        QVERIFY2(distinctColours(image) >= 100, qPrintable(QString::number(distinctColours(image))));
    }

    void rendersTopWithAWallHighlighted()
    {
        const QStringList walls = wallGuids(qEnvironmentVariable("KIMBIM_HOUSE"));
        QVERIFY(walls.size() >= 4);
        const QString out = m_tmp.filePath("top.png");
        // The roof covers the walls from above: the highlighted wall is shown alone.
        const QJsonObject r = request({{"op", "render3d"}, {"out", out}, {"size", QJsonArray{640, 480}},
            {"camera", "top"}, {"frame", QJsonArray{walls[0]}}, {"isolate", true}, {"highlight", QJsonArray{walls[0]}}});
        QVERIFY2(r.value("ok").toBool(), QJsonDocument(r).toJson().constData());
        QCOMPARE(r.value("framed").toInt(), 1);
        const QColor highlight(r.value("highlight_colour").toString());
        QVERIFY(highlight.isValid());
        const QImage image(out);
        QCOMPARE(image.size(), QSize(640, 480));
        const int near = pixelsLike(image, highlight);
        QVERIFY2(near >= 200, qPrintable(QString::number(near)));

        // The next picture starts from the whole model again (no isolation or colours left over).
        const QString iso = m_tmp.filePath("iso-white.png");
        const QJsonObject w = request({{"op", "render3d"}, {"out", iso}, {"size", QJsonArray{400, 300}},
            {"camera", "iso-nw"}, {"style", "white"}});
        QVERIFY2(w.value("ok").toBool(), QJsonDocument(w).toJson().constData());
        QVERIFY(w.value("framed").toInt() > 10);
        // (a left-over highlighted wall would be thousands of pixels; glass and edges give a few)
        const int leftOver = pixelsLike(QImage(iso), highlight);
        QVERIFY2(leftOver < 100, qPrintable(QString::number(leftOver)));
    }

    void rendersAnExplicitPerspectiveCamera()
    {
        const QString out = m_tmp.filePath("camera.png");
        const QJsonObject cam{{"eye", QJsonArray{25, -20, 12}}, {"target", QJsonArray{5, 4, 3}},
            {"up", QJsonArray{0, 0, 1}}, {"fov", 45}};
        const QJsonObject r = request({{"op", "render3d"}, {"out", out}, {"size", QJsonArray{320, 200}},
            {"camera", cam}, {"style", "lines"}, {"cut", 1.5}});
        QVERIFY2(r.value("ok").toBool(), QJsonDocument(r).toJson().constData());
        const QJsonObject used = r.value("camera").toObject();
        QCOMPARE(used.value("fov").toDouble(), 45.0);
        QCOMPARE(used.value("eye").toArray()[0].toDouble(), 25.0);
        QCOMPARE(QImage(out).size(), QSize(320, 200));
        const QJsonObject bad = request({{"op", "render3d"}, {"out", out}, {"camera", "sideways"}});
        QCOMPARE(bad.value("error").toObject().value("code").toString(), QString("bad_request"));
        const QJsonObject purpose = request({{"op", "render3d"}, {"out", out}, {"purpose", "No such purpose"}});
        QCOMPARE(purpose.value("error").toObject().value("code").toString(), QString("unknown_purpose"));
    }

    void rasterisesAnSvg()
    {
        QFile svg(m_tmp.filePath("small.svg"));
        QVERIFY(svg.open(QIODevice::WriteOnly));
        svg.write("<svg xmlns='http://www.w3.org/2000/svg' width='100mm' height='50mm' viewBox='0 0 100 50'>"
                  "<rect x='10' y='10' width='80' height='30' fill='none' stroke='black'/></svg>");
        svg.close();
        const QString out = m_tmp.filePath("small.png");
        const QJsonObject r = request({{"op", "svg2png"}, {"svg", svg.fileName()}, {"out", out}, {"size", QJsonArray{300, 150}}});
        QVERIFY2(r.value("ok").toBool(), QJsonDocument(r).toJson().constData());
        const QImage image(out);
        QCOMPARE(image.size(), QSize(300, 150));
        QCOMPARE(image.pixelColor(2, 2), QColor(Qt::white));
        QVERIFY(pixelsNear(image, Qt::black, 90) > 0);
    }
};

QTEST_GUILESS_MAIN(TestSnapshotServer)
#include "test_snapshot_server.moc"

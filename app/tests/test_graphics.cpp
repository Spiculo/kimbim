// SPDX-License-Identifier: GPL-3.0-or-later
#include <QJsonArray>
#include <QJsonDocument>
#include <QtTest>

#include "Graphics.h"

class TestGraphics : public QObject {
    Q_OBJECT
private slots:
    void parsesStylesHiddenAndPens()
    {
        const QByteArray json = R"({"ok": true, "purpose": "Working", "current_pen": 26, "annotation_pen": 23,
            "pens": {"26": {"color": "#e02020", "weight": 0.5}},
            "styles": [{"cut": {"color": "#111111", "weight": 0.5, "dash": []},
                        "projection": {"color": "#222222", "weight": 0.18, "dash": [3.0, 1.5]},
                        "fill": "#333333", "surface": "#445566", "transparency": 0.5}],
            "elements": {"W1": 0}, "hidden": ["F1"]})";
        const auto g = kimcad::Graphics::fromJson(QJsonDocument::fromJson(json).object());
        QCOMPARE(g.purpose(), QString("Working"));
        QCOMPARE(g.currentPen(), 26);
        const kimcad::ElementStyle* s = g.styleOf("W1");
        QVERIFY(s);
        QCOMPARE(s->cut.color, QColor("#111111"));
        QCOMPARE(s->projection.dash, (QVector<double>{3.0, 1.5}));
        QCOMPARE(s->fill, QColor("#333333"));
        QCOMPARE(*s->surface, QColor("#445566"));
        QCOMPARE(*s->transparency, 0.5);
        QVERIFY(!g.styleOf("nope"));
        QVERIFY(g.isHidden("F1"));
        QCOMPARE(g.pen(26).color, QColor("#e02020"));
        QCOMPARE(g.pen(99).color, QColor(Qt::black)); // missing: fallback
        QCOMPARE(g.pen(99).weight, 0.18);
    }
    void badInputGivesAnEmptyState()
    {
        const auto g = kimcad::Graphics::fromJson(QJsonObject{{"ok", false}});
        QVERIFY(g.isEmpty());
        QCOMPARE(g.currentPen(), 23);
        const auto bad = kimcad::Graphics::fromJson(QJsonDocument::fromJson(
            R"({"ok": true, "styles": [], "elements": {"W1": 5}})").object());
        QVERIFY(!bad.styleOf("W1")); // index out of range is ignored
    }
    void pixelsAndPatterns()
    {
        QCOMPARE(kimcad::Graphics::pixels(0.5, false), 1.0f);
        QCOMPARE(kimcad::Graphics::pixels(0.5, true), 2.0f);
        QCOMPARE(kimcad::Graphics::pixels(0.13, true), 1.0f);
        QCOMPARE(kimcad::Graphics::pixels(5.0, true), 6.0f);
        QCOMPARE(kimcad::Graphics::pattern({}), uint16_t(0xFFFF));
        QVERIFY(kimcad::Graphics::pattern({3.0, 1.5}) != 0xFFFF);
        QVERIFY(kimcad::Graphics::pattern({3.0, 1.5}) != 0);
    }
};

QTEST_MAIN(TestGraphics)
#include "test_graphics.moc"

// SPDX-License-Identifier: GPL-3.0-or-later
// D96: the Materials dialog's edits (surfaces, building materials, composites) become one change.
#include <QtTest>

#include <QComboBox>
#include <QDoubleSpinBox>
#include <QJsonDocument>
#include <QLabel>
#include <QLineEdit>
#include <QListWidget>
#include <QPushButton>
#include <QSlider>
#include <QTableWidget>

#include "MaterialsDialog.h"

using kimbim::MaterialsEdits;

namespace {

QJsonObject state()
{
    return QJsonDocument::fromJson(R"({"ok":true,
        "surfaces":[{"key":1,"name":"Brick","colour":"#b5654a","transparency":0,"shine":0.1,"reflectance":"MATT","used_by":2},
                    {"key":2,"name":"Glass","colour":"#a9cde0","transparency":0.6,"shine":0.9,"reflectance":"GLASS","used_by":0}],
        "materials":[{"key":10,"name":"Brick","surface":"Brick","colour":"#b5654a","pen":12,"pattern":"Brick","priority":600,"used_by":2},
                     {"key":11,"name":"Block","surface":"","colour":"","pen":12,"pattern":"Solid","priority":600,"used_by":2},
                     {"key":12,"name":"Glass","surface":"Glass","colour":"#a9cde0","pen":12,"pattern":"Empty","priority":200,"used_by":0}],
        "composites":[{"key":20,"name":"Exterior 300","type":"IfcWallType","used_by":2,
                       "layers":[{"material":"Brick","thickness":0.1,"core":false},{"material":"Block","thickness":0.2,"core":true}]},
                      {"key":21,"name":"Generic 200","type":"IfcWallType","used_by":0,
                       "layers":[{"material":"Block","thickness":0.2,"core":true}]}],
        "patterns":["Solid","Empty","Brick"]})").object();
}

} // namespace

class TestMaterialsDialog : public QObject {
    Q_OBJECT
private slots:
    void unchangedMeansNoChanges()
    {
        MaterialsEdits e(state());
        QVERIFY(!e.modified());
        QVERIFY(e.changes().isEmpty());
    }

    void renamingASurfaceFollowsIntoMaterials()
    {
        MaterialsEdits e(state());
        e.setItem(MaterialsEdits::Surfaces, 0, {{"name", "Red brick"}});
        const QJsonObject c = e.changes();
        QCOMPARE(c.value("surfaces").toArray().at(0).toObject().value("key").toInt(), 1);
        const QJsonObject brick = c.value("materials").toArray().at(0).toObject();
        QCOMPARE(brick.value("surface").toString(), QString("Red brick"));
        QVERIFY(!brick.contains("colour")); // display only
        QVERIFY(!brick.contains("used_by"));
    }

    void renamingAMaterialFollowsIntoComposites()
    {
        MaterialsEdits e(state());
        e.setItem(MaterialsEdits::Materials, 1, {{"name", "Concrete block"}});
        const QJsonArray comps = e.changes().value("composites").toArray();
        QCOMPARE(comps.size(), 2); // both use Block
        QCOMPARE(comps.at(0).toObject().value("layers").toArray().at(1).toObject().value("material").toString(),
            QString("Concrete block"));
    }

    void namesStayUnique()
    {
        MaterialsEdits e(state());
        QVERIFY(!e.checkName(MaterialsEdits::Materials, 0, "Block").isEmpty());
        QVERIFY(!e.checkName(MaterialsEdits::Materials, 0, "  ").isEmpty());
        QVERIFY(e.checkName(MaterialsEdits::Materials, 0, "Brick").isEmpty()); // its own name
        const int i = e.duplicate(MaterialsEdits::Materials, 0);
        QCOMPARE(e.item(MaterialsEdits::Materials, i).value("name").toString(), QString("Brick 2"));
        QVERIFY(!e.item(MaterialsEdits::Materials, i).contains("key")); // created by the engine
    }

    void deletingSendsKeysAndReplacements()
    {
        MaterialsEdits e(state());
        e.remove(MaterialsEdits::Materials, 0, "Block");
        e.remove(MaterialsEdits::Surfaces, 1);
        const QJsonObject d = e.changes().value("deleted").toObject();
        QCOMPARE(d.value("materials").toArray().at(0).toObject().value("replace").toString(), QString("Block"));
        QCOMPARE(d.value("surfaces").toArray().at(0).toInt(), 2);
        // the Glass material no longer has a surface, and it is sent
        const QJsonArray mats = e.changes().value("materials").toArray();
        QCOMPARE(mats.size(), 1);
        QCOMPARE(mats.at(0).toObject().value("name").toString(), QString("Glass"));
        QCOMPARE(mats.at(0).toObject().value("surface").toString(), QString());
        // shown with the replacement
        QCOMPARE(e.item(MaterialsEdits::Composites, 0).value("layers").toArray().at(0).toObject().value("material").toString(),
            QString("Block"));
    }

    void deletingANewItemSendsNothing()
    {
        MaterialsEdits e(state());
        const int i = e.add(MaterialsEdits::Surfaces, {{"colour", "#ffffff"}}, "New surface");
        QVERIFY(e.modified());
        e.remove(MaterialsEdits::Surfaces, i);
        QVERIFY(e.changes().isEmpty());
    }

    void compositeNamesByType()
    {
        MaterialsEdits e(state());
        QCOMPARE(e.compositeNames("IfcWallType"), QStringList({"Exterior 300", "Generic 200"}));
        QVERIFY(e.compositeNames("IfcSlabType").isEmpty());
    }

    void dialogEditsAComposite()
    {
        kimbim::MaterialsDialog d(state(), {});
        d.showTab(MaterialsEdits::Composites);
        auto* list = d.findChild<QListWidget*>("materialsList2");
        QVERIFY(list);
        list->setCurrentRow(0);
        auto* table = d.findChild<QTableWidget*>("compositeLayers");
        QCOMPARE(table->rowCount(), 2);
        qobject_cast<QDoubleSpinBox*>(table->cellWidget(0, 1))->setValue(150.0); // mm
        d.findChild<QPushButton*>("compositeAddLayer")->click();
        QCOMPARE(table->rowCount(), 3);
        const QJsonArray layers = d.edits().changes().value("composites").toArray().at(0).toObject().value("layers").toArray();
        QCOMPARE(layers.size(), 3);
        QCOMPARE(layers.at(0).toObject().value("thickness").toDouble(), 0.15);
        QVERIFY(d.findChild<QLabel*>("compositeTotal")->text().contains("400.0"));
    }

    void dialogEditsAMaterial()
    {
        kimbim::MaterialsDialog d(state(), {});
        auto* list = d.findChild<QListWidget*>("materialsList1");
        list->setCurrentRow(1); // Block
        auto* surface = d.findChild<QComboBox*>("materialSurface");
        surface->setCurrentIndex(surface->findData("Brick"));
        d.findChild<QDoubleSpinBox*>("materialDensity")->setValue(1400);
        const QJsonObject block = d.edits().changes().value("materials").toArray().at(0).toObject();
        QCOMPARE(block.value("surface").toString(), QString("Brick"));
        QCOMPARE(block.value("density").toDouble(), 1400.0);
        QCOMPARE(block.value("key").toInt(), 11);
    }

    void dialogEditsASurface()
    {
        kimbim::MaterialsDialog d(state(), {});
        d.showTab(MaterialsEdits::Surfaces);
        d.findChild<QListWidget*>("materialsList0")->setCurrentRow(1); // Glass
        d.findChild<QSlider*>("surfaceTransparency")->setValue(30);
        const QJsonObject glass = d.edits().changes().value("surfaces").toArray().at(0).toObject();
        QCOMPARE(glass.value("transparency").toDouble(), 0.3);
        QCOMPARE(glass.value("reflectance").toString(), QString("GLASS"));
    }

    // D96: a surface's texture: a chosen picture travels as texture_path with its size; Remove clears it.
    void surfaceTextures()
    {
        kimbim::MaterialsDialog d(state(), {});
        d.showTab(MaterialsEdits::Surfaces);
        d.findChild<QListWidget*>("materialsList0")->setCurrentRow(0); // Brick
        d.findChild<QDoubleSpinBox*>("surfaceTextureWidth")->setValue(0.5);
        d.setSurfaceTexture(QStringLiteral("C:/pictures/brick.png"));
        QJsonObject brick = d.edits().changes().value("surfaces").toArray().at(0).toObject();
        QCOMPARE(brick.value("texture_path").toString(), QString("C:/pictures/brick.png"));
        QCOMPARE(brick.value("texture_size").toArray().at(0).toDouble(), 0.5);
        d.setSurfaceTexture(QString());
        brick = d.edits().changes().value("surfaces").toArray().at(0).toObject();
        QVERIFY(brick.value("texture_path").toString().isEmpty());
        QCOMPARE(brick.value("texture").toString(), QString());
    }

    void newCompositeIsAWallComposite()
    {
        kimbim::MaterialsDialog d(state(), {});
        d.findChild<QPushButton*>("materialsNew2")->click();
        const QJsonObject c = d.edits().changes().value("composites").toArray().at(0).toObject();
        QCOMPARE(c.value("type").toString(), QString("IfcWallType"));
        QCOMPARE(c.value("layers").toArray().size(), 1);
    }
};

QTEST_MAIN(TestMaterialsDialog)
#include "test_materials_dialog.moc"

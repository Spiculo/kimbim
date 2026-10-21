// SPDX-License-Identifier: GPL-3.0-or-later
#include "PreferencesDialog.h"

#include <QCheckBox>
#include <QComboBox>
#include <QDialogButtonBox>
#include <QFileDialog>
#include <QFormLayout>
#include <QHBoxLayout>
#include <QLabel>
#include <QLineEdit>
#include <QPushButton>
#include <QSpinBox>
#include <QVBoxLayout>

#include "Preferences.h"

namespace kimbim {

namespace {
QComboBox* choice(QWidget* parent, const char* name, const QList<QPair<QString, QString>>& items, const QString& current)
{
    auto* box = new QComboBox(parent);
    box->setObjectName(QLatin1String(name));
    for (const auto& [label, value] : items)
        box->addItem(label, value);
    box->setCurrentIndex(qMax(0, box->findData(current)));
    return box;
}
} // namespace

PreferencesDialog::PreferencesDialog(Preferences& prefs, QWidget* parent)
    : QDialog(parent)
    , m_prefs(prefs)
{
    setWindowTitle(tr("Preferences"));
    auto* layout = new QVBoxLayout(this);
    auto* form = new QFormLayout;

    m_language = choice(this, "language", {{tr("Automatic (system)"), "auto"}, {QStringLiteral("English"), "en"},
                                              {QStringLiteral("Español"), "es"}}, prefs.language());
    form->addRow(tr("Language:"), m_language);
    m_restartNote = new QLabel(tr("The language changes the next time KimBim starts."), this);
    m_restartNote->setObjectName(QStringLiteral("restartNote"));
    m_restartNote->setVisible(false);
    form->addRow(QString(), m_restartNote);
    connect(m_language, &QComboBox::currentIndexChanged, this,
        [this] { m_restartNote->setVisible(m_language->currentData().toString() != m_prefs.language()); });

    auto* templatesRow = new QHBoxLayout;
    m_templates = new QLineEdit(prefs.templatesFolder(), this);
    m_templates->setObjectName(QStringLiteral("templatesFolder"));
    auto* browse = new QPushButton(tr("Browse..."), this);
    connect(browse, &QPushButton::clicked, this, [this] {
        const QString folder = QFileDialog::getExistingDirectory(this, tr("Templates folder"), m_templates->text());
        if (!folder.isEmpty())
            m_templates->setText(folder);
    });
    templatesRow->addWidget(m_templates, 1);
    templatesRow->addWidget(browse);
    form->addRow(tr("Templates folder:"), templatesRow);

    // D86: the office library, another category of the Library panel (Python objects and IFC types).
    auto* officeRow = new QHBoxLayout;
    m_officeLibrary = new QLineEdit(prefs.value(QStringLiteral("office_library")).toString(), this);
    m_officeLibrary->setObjectName(QStringLiteral("officeLibrary"));
    m_officeLibrary->setPlaceholderText(tr("A shared folder of objects (.py) and IFC type libraries (.ifc)"));
    auto* browseOffice = new QPushButton(tr("Browse..."), this);
    connect(browseOffice, &QPushButton::clicked, this, [this] {
        const QString folder = QFileDialog::getExistingDirectory(this, tr("Office library"), m_officeLibrary->text());
        if (!folder.isEmpty())
            m_officeLibrary->setText(folder);
    });
    officeRow->addWidget(m_officeLibrary, 1);
    officeRow->addWidget(browseOffice);
    form->addRow(tr("Office library:"), officeRow);

    m_authorName = new QLineEdit(prefs.authorName(), this);
    m_authorName->setObjectName(QStringLiteral("authorName"));
    m_authorName->setPlaceholderText(tr("Shown on versions and to others opening your files"));
    form->addRow(tr("Your name:"), m_authorName);
    m_authorEmail = new QLineEdit(prefs.authorEmail(), this);
    m_authorEmail->setObjectName(QStringLiteral("authorEmail"));
    form->addRow(tr("Your email:"), m_authorEmail);

    m_newViews = choice(this, "newViews", {{tr("Tabs"), "tab"}, {tr("Free windows"), "window"}}, prefs.newViews());
    form->addRow(tr("New views open as:"), m_newViews);
    m_openIfc = choice(this, "openIfc", {{tr("Make a .kim beside it"), "make_kim"}, {tr("Edit the IFC directly"), "edit_ifc"}},
        prefs.openIfc());
    form->addRow(tr("Opening an IFC file:"), m_openIfc);
    m_largeIfc = new QSpinBox(this);
    m_largeIfc->setObjectName(QStringLiteral("largeIfcMb"));
    m_largeIfc->setRange(0, 10000);
    m_largeIfc->setSuffix(tr(" MB"));
    m_largeIfc->setSpecialValueText(tr("Never"));
    m_largeIfc->setValue(qRound(prefs.largeIfcMb()));
    m_largeIfc->setToolTip(tr("Making a .kim from a large IFC can take minutes; above this size KimBim asks first"));
    form->addRow(tr("Ask before converting IFC files over:"), m_largeIfc);

    auto* autoRow = new QHBoxLayout;
    m_autoVersion = choice(this, "autoVersion", {{tr("Off"), "off"}, {tr("Every N saves"), "saves"},
                                                    {tr("Every N minutes"), "minutes"}}, prefs.autoVersion());
    m_autoEvery = new QSpinBox(this);
    m_autoEvery->setObjectName(QStringLiteral("autoVersionEvery"));
    m_autoEvery->setRange(1, 999);
    m_autoEvery->setValue(prefs.autoVersionEvery());
    m_autoEvery->setEnabled(prefs.autoVersion() != QLatin1String("off"));
    connect(m_autoVersion, &QComboBox::currentIndexChanged, this,
        [this] { m_autoEvery->setEnabled(m_autoVersion->currentData().toString() != QLatin1String("off")); });
    autoRow->addWidget(m_autoVersion, 1);
    autoRow->addWidget(new QLabel(tr("N ="), this));
    autoRow->addWidget(m_autoEvery);
    form->addRow(tr("Automatic versions:"), autoRow);

    m_recovery = new QSpinBox(this);
    m_recovery->setObjectName(QStringLiteral("recoveryMinutes"));
    m_recovery->setRange(0, 120);
    m_recovery->setSuffix(tr(" min"));
    m_recovery->setSpecialValueText(tr("Off"));
    m_recovery->setValue(prefs.recoveryMinutes());
    form->addRow(tr("Recovery copy every:"), m_recovery);

    m_drawingTimeout = new QSpinBox(this);
    m_drawingTimeout->setObjectName(QStringLiteral("drawingTimeout"));
    m_drawingTimeout->setRange(0, 3600);
    m_drawingTimeout->setSuffix(tr(" s"));
    m_drawingTimeout->setSpecialValueText(tr("No limit"));
    m_drawingTimeout->setValue(prefs.drawingTimeout());
    m_drawingTimeout->setToolTip(tr("Give up on a drawing that takes longer: the hidden-line pass can be slow on a large model"));
    form->addRow(tr("Drawing generation timeout:"), m_drawingTimeout);
    m_drawingHlr = choice(this, "drawingHlr", {{tr("Exact (faster on detailed models)"), "exact"},
                                                  {tr("Polygon (faster on curved models)"), "poly"}}, prefs.drawingHlr());
    m_drawingHlr->setToolTip(tr("The serializer's hidden-line mode: try the other one if drawings are slow"));
    form->addRow(tr("Hidden-line mode:"), m_drawingHlr);
    // D89: touchpad or mouse wheel.
    m_scroll = choice(this, "scrollNavigation", {{tr("Automatic (touchpad scroll pans, mouse wheel zooms)"), "auto"},
        {tr("Mouse: the wheel zooms"), "zoom"}, {tr("Mac trackpad: two fingers pan"), "pan"},
        {tr("Precision touchpad: two fingers pan, finely"), "precision"}},
        prefs.scrollNavigation());
    m_scroll->setToolTip(tr("Two-finger scroll with Shift orbits the 3D view"));
    form->addRow(tr("Scroll and touchpad:"), m_scroll);
    m_tracker = choice(this, "tracker", {{tr("Always while drawing"), "always"}, {tr("While typing"), "typing"},
                                         {tr("Off") , "off"}}, prefs.trackerMode());
    m_tracker->setToolTip(tr("The tracker beside the cursor: always, only once something is typed, or not at all"));
    form->addRow(tr("Tracker:"), m_tracker);
    m_angleMode = choice(this, "angleMode", {{tr("Absolute (from east)"), "absolute"},
                                             {tr("Relative to the previous segment"), "relative"},
                                             {tr("Bearing (clockwise from north)"), "bearing"}}, prefs.angleMode());
    m_angleMode->setToolTip(tr("How typed and live angles are measured"));
    form->addRow(tr("Angle input:"), m_angleMode);
    m_typedLength = choice(this, "typedLengthUnit", {{tr("Metres"), "metres"}, {tr("Project unit"), "project"}},
        prefs.typedLengthUnit());
    m_typedLength->setToolTip(tr("The unit of lengths typed into the tracker and the length field"));
    form->addRow(tr("Typed lengths in:"), m_typedLength);
    m_tabAnnotations = new QCheckBox(tr("Tab also cycles through annotations and 2D drafting"), this);
    m_tabAnnotations->setObjectName(QStringLiteral("tabAnnotations"));
    m_tabAnnotations->setChecked(prefs.tabAnnotations());
    form->addRow(QString(), m_tabAnnotations);

    // D92: the perspective camera's field of view.
    m_fieldOfView = new QSpinBox(this);
    m_fieldOfView->setObjectName(QStringLiteral("fieldOfView"));
    m_fieldOfView->setRange(5, 120);
    m_fieldOfView->setSuffix(tr("°"));
    m_fieldOfView->setValue(qRound(prefs.fieldOfView()));
    m_fieldOfView->setToolTip(tr("How wide the perspective view sees: 45° is a normal lens"));
    form->addRow(tr("Perspective field of view:"), m_fieldOfView);

    // D92: the north indicator on plans (shown once true north is set).
    m_northArrow = new QCheckBox(tr("Show a north arrow on plans (once true north is set)"), this);
    m_northArrow->setObjectName(QStringLiteral("northArrow"));
    m_northArrow->setChecked(prefs.northArrowPlans());
    form->addRow(QString(), m_northArrow);

    // D92: which controls the title bar holds.
    auto* chromeRow = new QHBoxLayout;
    m_titleLevels = new QCheckBox(tr("Levels"), this);
    m_titleLevels->setObjectName(QStringLiteral("titleBarLevels"));
    m_titleLevels->setChecked(prefs.titleBarLevels());
    m_titleCut = new QCheckBox(tr("Plan cut"), this);
    m_titleCut->setObjectName(QStringLiteral("titleBarCut"));
    m_titleCut->setChecked(prefs.titleBarCut());
    m_titleVersions = new QCheckBox(tr("Versions"), this);
    m_titleVersions->setObjectName(QStringLiteral("titleBarVersions"));
    m_titleVersions->setChecked(prefs.titleBarVersions());
    chromeRow->addWidget(m_titleLevels);
    chromeRow->addWidget(m_titleCut);
    chromeRow->addWidget(m_titleVersions);
    chromeRow->addStretch(1);
    form->addRow(tr("Title bar shows:"), chromeRow);

    // D92: selection behaviour.
    m_selectSimilar = choice(this, "selectSimilarScope", {{tr("Same class and predefined type"), "class_predefined"},
        {tr("Same type object"), "type"}, {tr("Same class"), "class"}}, prefs.selectSimilarScope());
    m_selectSimilar->setToolTip(tr("What Select similar takes: elements sharing the selected element's class and predefined type, its type object, or its class"));
    form->addRow(tr("Select similar by:"), m_selectSimilar);
    m_boxSelection = choice(this, "boxSelection", {{tr("Drag direction (left window, right crossing)"), "direction"},
        {tr("Any touched element (partial)"), "partial"}, {tr("Only fully enclosed elements (entire)"), "entire"}},
        prefs.boxSelection());
    m_boxSelection->setToolTip(tr("How a box selects elements"));
    form->addRow(tr("Box selection:"), m_boxSelection);
    m_splitJoin = new QCheckBox(tr("Join split and trimmed pieces (hold Ctrl to leave them apart)"), this);
    m_splitJoin->setObjectName(QStringLiteral("splitJoin"));
    m_splitJoin->setChecked(prefs.splitJoin());
    form->addRow(QString(), m_splitJoin);

    m_objectEditScope = choice(this, "objectEditScope", {{tr("Change only the selection"), "selection"},
                                                         {tr("Ask when the object's type is shared"), "ask"}},
        prefs.objectEditScope());
    m_objectEditScope->setToolTip(tr("Editing a library object's parameters: change the selected placements only, "
                                     "or ask whether to change every placement of its type"));
    form->addRow(tr("Library object parameters:"), m_objectEditScope);
    m_mergeProps = choice(this, "mergeProps", {{tr("Keep the first element's properties"), "keep"},
        {tr("Refuse when their properties differ"), "refuse"}}, prefs.mergeProps());
    m_mergeProps->setToolTip(tr("Merging two collinear walls (Join): the result keeps the first wall's properties, or the merge is refused if they differ"));
    form->addRow(tr("Merging elements:"), m_mergeProps);

    // D92: snapping to element mesh vertices (slabs, roofs, ...), off by default.
    m_meshVertexSnaps = new QCheckBox(tr("Snap to element mesh vertices while drawing"), this);
    m_meshVertexSnaps->setObjectName(QStringLiteral("meshVertexSnaps"));
    m_meshVertexSnaps->setChecked(prefs.meshVertexSnaps());
    m_meshVertexSnaps->setToolTip(tr("Adds the corners of slabs, roofs and other elements to the snap points"));
    form->addRow(QString(), m_meshVertexSnaps);
    m_keepRectangles = new QCheckBox(tr("Keep rectangles rectangular when a corner is dragged"), this); // D92
    m_keepRectangles->setObjectName(QStringLiteral("keepRectangles"));
    m_keepRectangles->setChecked(prefs.keepRectanglesRectangular());
    m_keepRectangles->setToolTip(tr("On: the two sides next to the dragged corner follow it; off: the corner moves freely"));
    form->addRow(QString(), m_keepRectangles);

    // D92: the defaults a new underlay gets.
    m_underlayOpacity = new QSpinBox(this);
    m_underlayOpacity->setObjectName(QStringLiteral("underlayOpacity"));
    m_underlayOpacity->setRange(5, 100);
    m_underlayOpacity->setSuffix(tr(" %"));
    m_underlayOpacity->setValue(qRound(prefs.underlayOpacity() * 100));
    form->addRow(tr("New underlay opacity:"), m_underlayOpacity);
    m_underlayGrey = new QCheckBox(tr("Show new underlays in grey"), this);
    m_underlayGrey->setObjectName(QStringLiteral("underlayGrey"));
    m_underlayGrey->setChecked(prefs.underlayGreyscale());
    form->addRow(QString(), m_underlayGrey);
    m_underlayTint = new QLineEdit(prefs.underlayTint(), this);
    m_underlayTint->setObjectName(QStringLiteral("underlayTint"));
    m_underlayTint->setPlaceholderText(QStringLiteral("#rrggbb"));
    m_underlayTint->setToolTip(tr("Tint new underlays this colour (leave empty for none)"));
    form->addRow(tr("New underlay tint:"), m_underlayTint);
    m_underlayLayerPerFile = new QCheckBox(tr("Put each new underlay on its own layer, named after the file"), this);
    m_underlayLayerPerFile->setObjectName(QStringLiteral("underlayLayerPerFile"));
    m_underlayLayerPerFile->setChecked(prefs.underlayLayerPerFile());
    form->addRow(QString(), m_underlayLayerPerFile);

    layout->addLayout(form);
    auto* buttons = new QDialogButtonBox(QDialogButtonBox::Ok | QDialogButtonBox::Cancel, this);
    connect(buttons, &QDialogButtonBox::accepted, this, &QDialog::accept);
    connect(buttons, &QDialogButtonBox::rejected, this, &QDialog::reject);
    layout->addWidget(buttons);
}

void PreferencesDialog::apply()
{
    m_prefs.setValue(QStringLiteral("language"), m_language->currentData().toString());
    m_prefs.setValue(QStringLiteral("templates_folder"), m_templates->text().trimmed());
    m_prefs.setValue(QStringLiteral("office_library"), m_officeLibrary->text().trimmed());
    m_prefs.setValue(QStringLiteral("author_name"), m_authorName->text().trimmed());
    m_prefs.setValue(QStringLiteral("author_email"), m_authorEmail->text().trimmed());
    m_prefs.setValue(QStringLiteral("new_views"), m_newViews->currentData().toString());
    m_prefs.setValue(QStringLiteral("open_ifc"), m_openIfc->currentData().toString());
    m_prefs.setValue(QStringLiteral("large_ifc_mb"), m_largeIfc->value());
    m_prefs.setValue(QStringLiteral("auto_version"), m_autoVersion->currentData().toString());
    m_prefs.setValue(QStringLiteral("auto_version_every"), m_autoEvery->value());
    m_prefs.setValue(QStringLiteral("recovery_minutes"), m_recovery->value());
    m_prefs.setValue(QStringLiteral("drawing_timeout"), m_drawingTimeout->value());
    m_prefs.setValue(QStringLiteral("drawing_hlr"), m_drawingHlr->currentData().toString());
    m_prefs.setValue(QStringLiteral("scroll_navigation"), m_scroll->currentData().toString());
    m_prefs.setValue(QStringLiteral("tracker"), m_tracker->currentData().toString());
    m_prefs.setValue(QStringLiteral("angle_mode"), m_angleMode->currentData().toString());
    m_prefs.setValue(QStringLiteral("typed_length_unit"), m_typedLength->currentData().toString());
    m_prefs.setValue(QStringLiteral("tab_annotations"), m_tabAnnotations->isChecked());
    m_prefs.setValue(QStringLiteral("field_of_view"), double(m_fieldOfView->value()));
    m_prefs.setValue(QStringLiteral("north_arrow"), m_northArrow->isChecked());
    m_prefs.setValue(QStringLiteral("title_bar_levels"), m_titleLevels->isChecked());
    m_prefs.setValue(QStringLiteral("title_bar_cut"), m_titleCut->isChecked());
    m_prefs.setValue(QStringLiteral("title_bar_versions"), m_titleVersions->isChecked());
    m_prefs.setValue(QStringLiteral("select_similar_scope"), m_selectSimilar->currentData().toString());
    m_prefs.setValue(QStringLiteral("box_selection"), m_boxSelection->currentData().toString());
    m_prefs.setValue(QStringLiteral("split_join"), m_splitJoin->isChecked());
    m_prefs.setValue(QStringLiteral("merge_props"), m_mergeProps->currentData().toString());
    m_prefs.setValue(QStringLiteral("object_edit_scope"), m_objectEditScope->currentData().toString());
    m_prefs.setValue(QStringLiteral("mesh_vertex_snaps"), m_meshVertexSnaps->isChecked());
    m_prefs.setValue(QStringLiteral("keep_rectangles_rectangular"), m_keepRectangles->isChecked());
    m_prefs.setValue(QStringLiteral("underlay_opacity"), double(m_underlayOpacity->value()) / 100.0);
    m_prefs.setValue(QStringLiteral("underlay_greyscale"), m_underlayGrey->isChecked());
    m_prefs.setValue(QStringLiteral("underlay_tint"), m_underlayTint->text().trimmed());
    m_prefs.setValue(QStringLiteral("underlay_layer_per_file"), m_underlayLayerPerFile->isChecked());
}

void PreferencesDialog::accept()
{
    apply();
    QDialog::accept();
}

} // namespace kimbim

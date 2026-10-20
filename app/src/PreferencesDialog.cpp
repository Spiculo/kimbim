// SPDX-License-Identifier: GPL-3.0-or-later
#include "PreferencesDialog.h"

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
        {tr("Scrolling zooms (mouse wheel)"), "zoom"}, {tr("Scrolling pans, pinch or Ctrl+scroll zooms (touchpad)"), "pan"}},
        prefs.scrollNavigation());
    m_scroll->setToolTip(tr("Two-finger scroll with Shift orbits the 3D view"));
    form->addRow(tr("Scroll and touchpad:"), m_scroll);

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
}

void PreferencesDialog::accept()
{
    apply();
    QDialog::accept();
}

} // namespace kimbim

// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once

#include <QDialog>
#include <QStringList>

class QComboBox;
class QLineEdit;
class QListWidget;
class QPushButton;

namespace kimbim {

// M2: Uniclass, OmniClass and local classification systems. Make a system and its codes, assign the
// codes to the selection and remove them. The systems and codes live in the IFC model.
class ClassificationsDialog : public QDialog {
    Q_OBJECT
public:
    explicit ClassificationsDialog(const QStringList& selection, QWidget* parent = nullptr);
    void refresh();
    QComboBox* systems() const { return m_systems; }
    QListWidget* references() const { return m_references; }
    void setSystem(const QString& name);

signals:
    void changed();

private:
    void addSystem();
    void assign();
    void unassign();
    void removeReference();
    QString selectionJson() const;
    QString currentSystem() const;

    QStringList m_selection;
    QComboBox* m_systems;
    QListWidget* m_references;
    QLineEdit* m_identification;
    QLineEdit* m_name;
    QPushButton* m_assign;
    QPushButton* m_unassign;
    QPushButton* m_remove;
};

} // namespace kimbim

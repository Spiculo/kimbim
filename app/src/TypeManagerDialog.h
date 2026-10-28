// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once

#include <QDialog>
#include <QJsonObject>
#include <QStringList>

class QLineEdit;
class QPushButton;
class QTreeWidget;

namespace kimbim {

// M2: every type in the model with its element count; make a type from the selection, assign it,
// edit its name/description/tag, or push its values to every occurrence (update all).
class TypeManagerDialog : public QDialog {
    Q_OBJECT
public:
    explicit TypeManagerDialog(const QStringList& selection, QWidget* parent = nullptr);
    void refresh();
    QTreeWidget* types() const { return m_types; }
    QString selectedType() const;
    void setSelectedType(const QString& guid);

signals:
    void changed(); // an edit happened: the model and Properties panel should refresh

private:
    void applyEdits();
    QString selectionJson() const;

    QStringList m_selection;
    QTreeWidget* m_types;
    QLineEdit* m_name;
    QLineEdit* m_description;
    QLineEdit* m_tag;
    QPushButton* m_create;
    QPushButton* m_assign;
    QPushButton* m_updateAll;
    QPushButton* m_apply;
};

} // namespace kimbim

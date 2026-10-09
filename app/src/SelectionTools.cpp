// SPDX-License-Identifier: GPL-3.0-or-later
// Selection tools (D78): select similar, Find & Select and selection sets. MainWindow members kept in
// their own file; the queries themselves run in Python (kimcad.queries).
#include "MainWindow.h"

#include "DockLayout.h"
#include "FindSelectPanel.h"
#include "LevelsBar.h"
#include "ModelTreePanel.h"
#include "StatusStrip.h"
#include "Viewport.h"

#include <QJsonDocument>
#include <QSet>

namespace kimcad {

namespace {

QString compact(const QJsonValue& v)
{
    return QString::fromUtf8(v.isArray() ? QJsonDocument(v.toArray()).toJson(QJsonDocument::Compact)
                                         : QJsonDocument(v.toObject()).toJson(QJsonDocument::Compact));
}

QStringList toStrings(const QJsonValue& v)
{
    QStringList out;
    for (const auto& x : v.toArray())
        out << x.toString();
    return out;
}

QString howOf(FindSelectPanel::How how)
{
    return how == FindSelectPanel::How::Add      ? QStringLiteral("add")
        : how == FindSelectPanel::How::Remove    ? QStringLiteral("remove")
                                                 : QStringLiteral("replace");
}

} // namespace

QStringList MainWindow::unselectableLayers() const
{
    QSet<QString> layers = m_hiddenLayers;
    layers.unite(m_lockedLayers);
    QStringList out(layers.begin(), layers.end());
    out.sort();
    return out;
}

void MainWindow::applySelection(const QStringList& guids, const QString& how)
{
    // Hidden in the view (H/I, a model being edited, the purpose) or locked: not selectable.
    QStringList found;
    for (const QString& g : guids)
        if (!m_viewport->isElementHidden(g) && !m_viewport->isLocked(g))
            found << g;
    QStringList result;
    if (how == QLatin1String("add")) {
        result = m_selection;
        const QSet<QString> have(m_selection.begin(), m_selection.end());
        for (const QString& g : std::as_const(found))
            if (!have.contains(g))
                result << g;
    } else if (how == QLatin1String("remove")) {
        const QSet<QString> drop(found.begin(), found.end());
        for (const QString& g : std::as_const(m_selection))
            if (!drop.contains(g))
                result << g;
    } else {
        result = found;
    }
    m_viewport->selectGuids(result);
    m_tree->selectGuids(result);
    setSelection(result);
    if (result.isEmpty())
        m_status->showMessage(tr("Nothing selected"));
}

bool MainWindow::selectSimilar(const QString& mode)
{
    if (m_selection.isEmpty()) {
        m_status->showMessage(tr("Select an element first: Select similar takes others like it"));
        return false;
    }
    const QJsonObject r = bridge("similar_elements",
        {compact(QJsonArray::fromStringList(m_selection)), mode, compact(QJsonArray::fromStringList(unselectableLayers()))});
    if (!r.value("ok").toBool()) {
        m_status->showMessage(tr("Could not select similar elements: %1").arg(r.value("error").toString()));
        return false;
    }
    m_timings[QStringLiteral("select_similar")] += r.value("ms").toDouble();
    applySelection(toStrings(r.value("guids")), QStringLiteral("replace"));
    return true;
}

int MainWindow::findAndSelect(const QJsonObject& query, const QString& how)
{
    QJsonObject q = query;
    q.insert("skip_layers", QJsonArray::fromStringList(unselectableLayers()));
    if (q.value("scope").toString() == QLatin1String("level"))
        q.insert("level", m_levels->activeStorey());
    if (q.value("scope").toString() == QLatin1String("selection"))
        q.insert("selection", QJsonArray::fromStringList(m_selection));
    const QJsonObject r = bridge("find_elements", {compact(q)});
    if (!r.value("ok").toBool()) {
        const QString message = tr("Could not find elements: %1").arg(r.value("error").toString());
        m_status->showMessage(message);
        if (m_findSelect)
            m_findSelect->setResult(message);
        return -1;
    }
    m_timings[QStringLiteral("find_select")] += r.value("ms").toDouble();
    const QStringList guids = toStrings(r.value("guids"));
    applySelection(guids, how);
    if (m_findSelect)
        m_findSelect->setResult(tr("%n element(s) found", nullptr, int(guids.size()))
            + QStringLiteral(" · ") + tr("%n selected", nullptr, int(m_selection.size())));
    return int(guids.size());
}

bool MainWindow::saveSelectionCriteria(const QString& name, const QJsonObject& criteria)
{
    QJsonObject table = m_settings.value("selection_criteria").toObject();
    table.insert(name, criteria);
    const bool ok = setProjectSettings({{"selection_criteria", table}});
    if (ok)
        m_status->showMessage(tr("Criteria set %1 saved in the project").arg(name));
    refreshFindSelect();
    return ok;
}

bool MainWindow::deleteSelectionCriteria(const QString& name)
{
    QJsonObject table = m_settings.value("selection_criteria").toObject();
    if (!table.contains(name))
        return false;
    table.remove(name);
    const bool ok = setProjectSettings({{"selection_criteria", table}});
    refreshFindSelect();
    return ok;
}

bool MainWindow::saveSelectionSet(const QString& name)
{
    if (m_selection.isEmpty()) {
        m_status->showMessage(tr("Select the elements to save first"));
        return false;
    }
    QJsonObject table = m_settings.value("selection_sets").toObject();
    table.insert(name, QJsonArray::fromStringList(m_selection));
    const bool ok = setProjectSettings({{"selection_sets", table}});
    if (ok)
        m_status->showMessage(tr("Selection set %1 saved (%n element(s))", nullptr, int(m_selection.size())).arg(name));
    refreshFindSelect();
    return ok;
}

bool MainWindow::recallSelectionSet(const QString& name, const QString& how)
{
    const QJsonObject r = bridge("selection_set_members", {name});
    if (!r.value("ok").toBool()) {
        m_status->showMessage(r.value("error").toString());
        return false;
    }
    applySelection(toStrings(r.value("guids")), how);
    if (const int missing = r.value("missing").toInt(); missing > 0)
        m_status->showMessage(tr("%n element(s) of the set are no longer in the model", nullptr, missing));
    return true;
}

bool MainWindow::deleteSelectionSet(const QString& name)
{
    QJsonObject table = m_settings.value("selection_sets").toObject();
    if (!table.contains(name))
        return false;
    table.remove(name);
    const bool ok = setProjectSettings({{"selection_sets", table}});
    refreshFindSelect();
    return ok;
}

void MainWindow::refreshFindSelect()
{
    if (!m_findSelect)
        return;
    m_findSelect->setChoices(bridge("query_choices"));
    m_findSelect->setSaved(m_settings.value("selection_criteria").toObject(), m_settings.value("selection_sets").toObject());
}

FindSelectPanel* MainWindow::findSelectPanel()
{
    if (m_findSelect)
        return m_findSelect;
    m_findSelect = new FindSelectPanel(this);
    m_dock->addPanel(QStringLiteral("findselect"), tr("Find & Select"), m_findSelect);
    connect(m_findSelect, &FindSelectPanel::refreshRequested, this, &MainWindow::refreshFindSelect);
    connect(m_findSelect, &FindSelectPanel::findRequested, this,
        [this](const QJsonObject& query, FindSelectPanel::How how) { findAndSelect(query, howOf(how)); });
    connect(m_findSelect, &FindSelectPanel::saveCriteriaRequested, this, &MainWindow::saveSelectionCriteria);
    connect(m_findSelect, &FindSelectPanel::deleteCriteriaRequested, this, &MainWindow::deleteSelectionCriteria);
    connect(m_findSelect, &FindSelectPanel::saveSetRequested, this, &MainWindow::saveSelectionSet);
    connect(m_findSelect, &FindSelectPanel::recallSetRequested, this,
        [this](const QString& name, FindSelectPanel::How how) { recallSelectionSet(name, howOf(how)); });
    connect(m_findSelect, &FindSelectPanel::deleteSetRequested, this, &MainWindow::deleteSelectionSet);
    refreshFindSelect();
    return m_findSelect;
}

} // namespace kimcad

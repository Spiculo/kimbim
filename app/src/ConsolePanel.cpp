// SPDX-License-Identifier: GPL-3.0-or-later
#include "ConsolePanel.h"

#include <QFontDatabase>
#include <QHBoxLayout>
#include <QKeyEvent>
#include <QPushButton>
#include <QRegularExpression>
#include <QScrollBar>
#include <QSplitter>
#include <QSyntaxHighlighter>
#include <QTextBlock>
#include <QVBoxLayout>

namespace kimcad {

namespace {

class PythonHighlighter : public QSyntaxHighlighter {
public:
    explicit PythonHighlighter(QTextDocument* doc)
        : QSyntaxHighlighter(doc)
    {
        const bool dark = QPalette().color(QPalette::Base).lightness() < 128;
        m_keyword.setForeground(dark ? QColor(0x56, 0x9c, 0xd6) : QColor(0x00, 0x33, 0xb3));
        m_keyword.setFontWeight(QFont::Bold);
        m_string.setForeground(dark ? QColor(0xce, 0x91, 0x78) : QColor(0x06, 0x7d, 0x17));
        m_comment.setForeground(dark ? QColor(0x6a, 0x99, 0x55) : QColor(0x8c, 0x8c, 0x8c));
        m_comment.setFontItalic(true);
        m_number.setForeground(dark ? QColor(0xb5, 0xce, 0xa8) : QColor(0x17, 0x50, 0xeb));
    }

protected:
    void highlightBlock(const QString& text) override
    {
        static const QRegularExpression keywords(QStringLiteral(
            "\\b(and|as|assert|async|await|break|class|continue|def|del|elif|else|except|False|finally|for|from|"
            "global|if|import|in|is|lambda|None|nonlocal|not|or|pass|raise|return|True|try|while|with|yield)\\b"));
        static const QRegularExpression numbers(QStringLiteral("\\b\\d+(\\.\\d*)?([eE][-+]?\\d+)?\\b"));
        static const QRegularExpression strings(QStringLiteral("'[^'\\\\]*(\\\\.[^'\\\\]*)*'|\"[^\"\\\\]*(\\\\.[^\"\\\\]*)*\""));
        static const QRegularExpression comment(QStringLiteral("#[^\\n]*"));
        auto paint = [&](const QRegularExpression& re, const QTextCharFormat& format) {
            for (auto it = re.globalMatch(text); it.hasNext();) {
                const auto m = it.next();
                setFormat(int(m.capturedStart()), int(m.capturedLength()), format);
            }
        };
        paint(keywords, m_keyword);
        paint(numbers, m_number);
        paint(strings, m_string);
        // A # outside strings starts a comment.
        for (auto it = comment.globalMatch(text); it.hasNext();) {
            const auto m = it.next();
            if (format(int(m.capturedStart())) != m_string) {
                setFormat(int(m.capturedStart()), int(text.size() - m.capturedStart()), m_comment);
                break;
            }
        }
    }

private:
    QTextCharFormat m_keyword, m_string, m_comment, m_number;
};

QFont monospace()
{
    QFont f = QFontDatabase::systemFont(QFontDatabase::FixedFont);
    f.setPointSizeF(std::max(9.0, f.pointSizeF()));
    return f;
}

} // namespace

ConsoleInput::ConsoleInput(QWidget* parent)
    : QPlainTextEdit(parent)
{
    setFont(monospace());
    setTabStopDistance(QFontMetricsF(font()).horizontalAdvance(QLatin1Char(' ')) * 4);
    setPlaceholderText(tr("Python: ifc, selection(), select(...), with edit(): ..., refresh(), help_kimcad()\n"
                          "Enter runs, Shift+Enter adds a line, Up/Down recall earlier input"));
    new PythonHighlighter(document());
}

void ConsoleInput::addHistory(const QString& code)
{
    if (!code.trimmed().isEmpty() && (m_history.isEmpty() || m_history.last() != code))
        m_history << code;
    m_index = int(m_history.size());
    m_draft.clear();
}

void ConsoleInput::historyUp()
{
    if (m_index == 0)
        return;
    if (m_index == m_history.size())
        m_draft = toPlainText();
    setPlainText(m_history.at(--m_index));
    moveCursor(QTextCursor::End);
}

void ConsoleInput::historyDown()
{
    if (m_index >= m_history.size())
        return;
    ++m_index;
    setPlainText(m_index == m_history.size() ? m_draft : m_history.at(m_index));
    moveCursor(QTextCursor::End);
}

void ConsoleInput::keyPressEvent(QKeyEvent* event)
{
    const bool enter = event->key() == Qt::Key_Return || event->key() == Qt::Key_Enter;
    if (enter && !(event->modifiers() & Qt::ShiftModifier)) {
        emit runRequested();
        return;
    }
    if (enter) { // Shift+Enter: a new line, keeping the indentation (and one more after a colon)
        const QString line = textCursor().block().text();
        QString indent = line.left(int(line.size() - QString(line).remove(QRegularExpression(QStringLiteral("^\\s+"))).size()));
        if (line.trimmed().endsWith(QLatin1Char(':')))
            indent += QStringLiteral("    ");
        textCursor().insertText(QStringLiteral("\n") + indent);
        return;
    }
    if (event->key() == Qt::Key_Tab && !(event->modifiers() & Qt::ControlModifier)) {
        textCursor().insertText(QStringLiteral("    "));
        return;
    }
    const QTextCursor c = textCursor();
    if (event->key() == Qt::Key_Up && c.blockNumber() == 0 && event->modifiers() == Qt::NoModifier) {
        historyUp();
        return;
    }
    if (event->key() == Qt::Key_Down && c.blockNumber() == document()->blockCount() - 1 && event->modifiers() == Qt::NoModifier) {
        historyDown();
        return;
    }
    QPlainTextEdit::keyPressEvent(event);
}

ConsolePanel::ConsolePanel(QWidget* parent)
    : QWidget(parent)
{
    setObjectName(QStringLiteral("consolePanel"));
    m_output = new QPlainTextEdit(this);
    m_output->setObjectName(QStringLiteral("consoleOutput"));
    m_output->setReadOnly(true);
    m_output->setFont(monospace());
    m_output->setMaximumBlockCount(5000);
    m_output->setPlaceholderText(tr("Output. Type help_kimcad() below for the console's names."));
    m_input = new ConsoleInput(this);
    m_input->setObjectName(QStringLiteral("consoleInput"));
    connect(m_input, &ConsoleInput::runRequested, this, &ConsolePanel::run);

    auto* split = new QSplitter(Qt::Vertical, this);
    split->addWidget(m_output);
    split->addWidget(m_input);
    split->setStretchFactor(0, 3);
    split->setStretchFactor(1, 1);

    auto* runButton = new QPushButton(tr("Run"), this);
    runButton->setObjectName(QStringLiteral("consoleRun"));
    runButton->setToolTip(tr("Run the input (Enter)"));
    connect(runButton, &QPushButton::clicked, this, &ConsolePanel::run);
    auto* fileButton = new QPushButton(tr("Run script..."), this);
    fileButton->setToolTip(tr("Run a Python file in the console"));
    connect(fileButton, &QPushButton::clicked, this, &ConsolePanel::runFileRequested);
    auto* clearButton = new QPushButton(tr("Clear"), this);
    connect(clearButton, &QPushButton::clicked, this, &ConsolePanel::clearOutput);

    auto* buttons = new QHBoxLayout;
    buttons->addWidget(runButton);
    buttons->addWidget(fileButton);
    buttons->addStretch();
    buttons->addWidget(clearButton);
    auto* layout = new QVBoxLayout(this);
    layout->setContentsMargins(4, 4, 4, 4);
    layout->addWidget(split, 1);
    layout->addLayout(buttons);
}

QString ConsolePanel::outputText() const
{
    return m_output->toPlainText();
}

void ConsolePanel::append(const QString& text, const QColor& color)
{
    QTextCursor c(m_output->document());
    c.movePosition(QTextCursor::End);
    QTextCharFormat format;
    format.setForeground(color);
    c.insertText(text, format);
    m_output->verticalScrollBar()->setValue(m_output->verticalScrollBar()->maximum());
}

void ConsolePanel::appendInput(const QString& code)
{
    QStringList lines = code.split(QLatin1Char('\n'));
    for (int i = 0; i < lines.size(); ++i)
        lines[i] = (i == 0 ? QStringLiteral(">>> ") : QStringLiteral("... ")) + lines[i];
    append(lines.join(QLatin1Char('\n')) + QLatin1Char('\n'), palette().color(QPalette::PlaceholderText));
}

void ConsolePanel::appendOutput(const QString& text, bool error)
{
    if (text.isEmpty())
        return;
    // Tracebacks in red; the rest in the text colour.
    append(text.endsWith(QLatin1Char('\n')) ? text : text + QLatin1Char('\n'),
        error ? QColor(0xd3, 0x2f, 0x2f) : palette().color(QPalette::Text));
}

void ConsolePanel::clearOutput()
{
    m_output->clear();
}

void ConsolePanel::run()
{
    const QString code = m_input->toPlainText();
    if (code.trimmed().isEmpty())
        return;
    m_input->addHistory(code);
    m_input->clear();
    appendInput(code);
    emit runRequested(code);
}

} // namespace kimcad

const vscode = require('vscode');
const { exec, spawn } = require('child_process');
const path = require('path');
const os = require('os');

/**
 * Clow VS Code Extension v0.2.0
 * Integra o agente Clow diretamente no editor.
 * Features: inline edit, commit inteligente, code review, diff view,
 *           test generation, plan mode.
 */

const CLOW_HOME = path.join(os.homedir(), '.clow');
const CLOW_BIN = path.join(CLOW_HOME, 'bin', 'clow');
const CLOW_PYTHON = path.join(CLOW_HOME, 'app', '.venv', 'bin', 'python');

let outputChannel;
let clowTerminal;

function activate(context) {
    outputChannel = vscode.window.createOutputChannel('Clow');
    outputChannel.appendLine('Clow v0.2.0 extension ativada');

    // ── Terminal Commands ──

    context.subscriptions.push(
        vscode.commands.registerCommand('clow.openInTerminal', () => {
            openClowTerminal();
        })
    );

    context.subscriptions.push(
        vscode.commands.registerCommand('clow.open', () => {
            openClowTerminal();
        })
    );

    context.subscriptions.push(
        vscode.commands.registerCommand('clow.ask', async () => {
            const question = await vscode.window.showInputBox({
                prompt: '🃏 Pergunte ao Clow',
                placeHolder: 'O que você quer fazer?',
            });
            if (question) {
                runClowCommand(question);
            }
        })
    );

    // ── Selection Commands ──

    context.subscriptions.push(
        vscode.commands.registerCommand('clow.explainSelection', () => {
            handleSelection('Explique este código em detalhes:');
        })
    );

    context.subscriptions.push(
        vscode.commands.registerCommand('clow.fixSelection', () => {
            handleSelection('Encontre e corrija bugs neste código:');
        })
    );

    context.subscriptions.push(
        vscode.commands.registerCommand('clow.refactorSelection', () => {
            handleSelection('Refatore este código para melhor legibilidade e performance:');
        })
    );

    // ── Inline Edit ──
    context.subscriptions.push(
        vscode.commands.registerCommand('clow.inlineEdit', async () => {
            const editor = vscode.window.activeTextEditor;
            if (!editor) {
                vscode.window.showWarningMessage('Nenhum editor ativo.');
                return;
            }

            const selection = editor.selection;
            const selectedText = editor.document.getText(selection);
            if (!selectedText) {
                vscode.window.showWarningMessage('Selecione o código a editar.');
                return;
            }

            const instruction = await vscode.window.showInputBox({
                prompt: '🃏 Como editar este código?',
                placeHolder: 'Ex: adicionar tratamento de erro, converter para async...',
            });
            if (!instruction) return;

            const filePath = editor.document.uri.fsPath;
            const lang = editor.document.languageId;
            const lineStart = selection.start.line + 1;
            const lineEnd = selection.end.line + 1;

            const prompt = `Edite o seguinte código no arquivo ${filePath} (linhas ${lineStart}-${lineEnd}).
Instrução: ${instruction}

Use a ferramenta edit com:
- file_path: "${filePath}"
- old_string: o código selecionado
- new_string: o código modificado

Código atual:
\`\`\`${lang}
${selectedText}
\`\`\``;

            runClowCommand(prompt);
        })
    );

    // ── Commit Inteligente ──
    context.subscriptions.push(
        vscode.commands.registerCommand('clow.commit', () => {
            const workspaceFolder = vscode.workspace.workspaceFolders?.[0]?.uri.fsPath;
            if (!workspaceFolder) {
                vscode.window.showWarningMessage('Nenhum workspace aberto.');
                return;
            }
            runClowSkill('/commit', workspaceFolder);
        })
    );

    // ── Code Review ──
    context.subscriptions.push(
        vscode.commands.registerCommand('clow.review', () => {
            const editor = vscode.window.activeTextEditor;
            if (editor) {
                const filePath = editor.document.uri.fsPath;
                runClowSkill(`/review ${filePath}`);
            } else {
                runClowSkill('/review');
            }
        })
    );

    // ── Generate Tests ──
    context.subscriptions.push(
        vscode.commands.registerCommand('clow.generateTests', () => {
            const editor = vscode.window.activeTextEditor;
            if (!editor) {
                vscode.window.showWarningMessage('Nenhum editor ativo.');
                return;
            }

            const selection = editor.selection;
            const selectedText = editor.document.getText(selection);
            const filePath = editor.document.uri.fsPath;
            const lang = editor.document.languageId;

            let target;
            if (selectedText) {
                target = `este código de ${filePath}:\n\`\`\`${lang}\n${selectedText}\n\`\`\``;
            } else {
                target = filePath;
            }

            runClowSkill(`/test ${target}`);
        })
    );

    // ── Diff View ──
    context.subscriptions.push(
        vscode.commands.registerCommand('clow.diffView', () => {
            const workspaceFolder = vscode.workspace.workspaceFolders?.[0]?.uri.fsPath;
            if (!workspaceFolder) return;
            runClowCommand('Mostre o git diff completo das mudanças atuais com explicação de cada alteração.');
        })
    );

    // ── Plan Mode ──
    context.subscriptions.push(
        vscode.commands.registerCommand('clow.planMode', async () => {
            const choice = await vscode.window.showQuickPick(
                ['Ativar Plan Mode', 'Desativar Plan Mode'],
                { placeHolder: '🃏 Plan Mode — somente leitura' }
            );
            if (choice === 'Ativar Plan Mode') {
                runClowCommand('/plan');
                vscode.window.showInformationMessage('🃏 Plan Mode ativado — somente leitura');
            } else if (choice === 'Desativar Plan Mode') {
                runClowCommand('/plan off');
                vscode.window.showInformationMessage('🃏 Plan Mode desativado');
            }
        })
    );
}

/**
 * Abre o Clow em um terminal integrado.
 */
function openClowTerminal() {
    const workspaceFolder = vscode.workspace.workspaceFolders?.[0]?.uri.fsPath || os.homedir();
    const config = vscode.workspace.getConfiguration('clow');
    const model = config.get('model', 'gpt-4.1');
    const autoApprove = config.get('autoApprove', false);
    const planMode = config.get('planModeDefault', false);

    const clowCmd = getClowCommand();

    let args = [...clowCmd.args];
    if (model) args.push('-m', model);
    if (autoApprove) args.push('-y');

    if (clowTerminal && clowTerminal.exitStatus === undefined) {
        clowTerminal.show();
        return;
    }

    clowTerminal = vscode.window.createTerminal({
        name: '🃏 Clow',
        cwd: workspaceFolder,
        shellPath: clowCmd.shell,
        shellArgs: args,
        iconPath: new vscode.ThemeIcon('hubot'),
    });

    clowTerminal.show();

    if (planMode) {
        setTimeout(() => {
            clowTerminal.sendText('/plan');
        }, 2000);
    }
}

/**
 * Roda um comando no Clow via terminal.
 */
function runClowCommand(prompt, cwd) {
    const workspaceFolder = cwd || vscode.workspace.workspaceFolders?.[0]?.uri.fsPath || os.homedir();
    const clowCmd = getClowCommand();
    const config = vscode.workspace.getConfiguration('clow');
    const model = config.get('model', 'gpt-4.1');

    const terminal = vscode.window.createTerminal({
        name: `🃏 ${prompt.substring(0, 30)}...`,
        cwd: workspaceFolder,
        shellPath: clowCmd.shell,
        shellArgs: [...clowCmd.args, prompt],
        iconPath: new vscode.ThemeIcon('hubot'),
    });

    terminal.show();
}

/**
 * Roda um skill do Clow.
 */
function runClowSkill(skillCommand, cwd) {
    // Para skills, enviamos o comando via terminal existente ou novo
    if (clowTerminal && clowTerminal.exitStatus === undefined) {
        clowTerminal.show();
        clowTerminal.sendText(skillCommand);
    } else {
        openClowTerminal();
        // Aguarda terminal iniciar e envia o skill
        setTimeout(() => {
            if (clowTerminal) {
                clowTerminal.sendText(skillCommand);
            }
        }, 3000);
    }
}

/**
 * Pega código selecionado e envia ao Clow.
 */
function handleSelection(prefix) {
    const editor = vscode.window.activeTextEditor;
    if (!editor) {
        vscode.window.showWarningMessage('Nenhum editor ativo.');
        return;
    }

    const selection = editor.selection;
    const selectedText = editor.document.getText(selection);

    if (!selectedText) {
        vscode.window.showWarningMessage('Nenhum texto selecionado.');
        return;
    }

    const filePath = editor.document.uri.fsPath;
    const lang = editor.document.languageId;
    const lineStart = selection.start.line + 1;
    const lineEnd = selection.end.line + 1;

    const prompt = `${prefix}\n\nArquivo: ${filePath} (linhas ${lineStart}-${lineEnd})\nLinguagem: ${lang}\n\n\`\`\`${lang}\n${selectedText}\n\`\`\``;

    runClowCommand(prompt);
}

/**
 * Detecta como executar o Clow.
 */
function getClowCommand() {
    const config = vscode.workspace.getConfiguration('clow');
    const customPython = config.get('pythonPath', '');

    if (customPython) {
        return { shell: customPython, args: ['-m', 'clow'] };
    }

    const fs = require('fs');
    if (fs.existsSync(CLOW_BIN)) {
        return { shell: CLOW_BIN, args: [] };
    }

    if (fs.existsSync(CLOW_PYTHON)) {
        return { shell: CLOW_PYTHON, args: ['-m', 'clow'] };
    }

    return { shell: 'python3', args: ['-m', 'clow'] };
}

function deactivate() {
    if (outputChannel) {
        outputChannel.dispose();
    }
}

module.exports = { activate, deactivate };

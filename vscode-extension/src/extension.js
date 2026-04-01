const vscode = require('vscode');
const { exec, spawn } = require('child_process');
const path = require('path');
const os = require('os');

/**
 * Batmam VS Code Extension v0.2.0
 * Integra o agente Batmam diretamente no editor.
 * Features: inline edit, commit inteligente, code review, diff view,
 *           test generation, plan mode.
 */

const BATMAM_HOME = path.join(os.homedir(), '.batmam');
const BATMAM_BIN = path.join(BATMAM_HOME, 'bin', 'batmam');
const BATMAM_PYTHON = path.join(BATMAM_HOME, 'app', '.venv', 'bin', 'python');

let outputChannel;
let batmamTerminal;

function activate(context) {
    outputChannel = vscode.window.createOutputChannel('Batmam');
    outputChannel.appendLine('Batmam v0.2.0 extension ativada');

    // ── Terminal Commands ──

    context.subscriptions.push(
        vscode.commands.registerCommand('batmam.openInTerminal', () => {
            openBatmamTerminal();
        })
    );

    context.subscriptions.push(
        vscode.commands.registerCommand('batmam.open', () => {
            openBatmamTerminal();
        })
    );

    context.subscriptions.push(
        vscode.commands.registerCommand('batmam.ask', async () => {
            const question = await vscode.window.showInputBox({
                prompt: '🦇 Pergunte ao Batmam',
                placeHolder: 'O que você quer fazer?',
            });
            if (question) {
                runBatmamCommand(question);
            }
        })
    );

    // ── Selection Commands ──

    context.subscriptions.push(
        vscode.commands.registerCommand('batmam.explainSelection', () => {
            handleSelection('Explique este código em detalhes:');
        })
    );

    context.subscriptions.push(
        vscode.commands.registerCommand('batmam.fixSelection', () => {
            handleSelection('Encontre e corrija bugs neste código:');
        })
    );

    context.subscriptions.push(
        vscode.commands.registerCommand('batmam.refactorSelection', () => {
            handleSelection('Refatore este código para melhor legibilidade e performance:');
        })
    );

    // ── Inline Edit ──
    context.subscriptions.push(
        vscode.commands.registerCommand('batmam.inlineEdit', async () => {
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
                prompt: '🦇 Como editar este código?',
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

            runBatmamCommand(prompt);
        })
    );

    // ── Commit Inteligente ──
    context.subscriptions.push(
        vscode.commands.registerCommand('batmam.commit', () => {
            const workspaceFolder = vscode.workspace.workspaceFolders?.[0]?.uri.fsPath;
            if (!workspaceFolder) {
                vscode.window.showWarningMessage('Nenhum workspace aberto.');
                return;
            }
            runBatmamSkill('/commit', workspaceFolder);
        })
    );

    // ── Code Review ──
    context.subscriptions.push(
        vscode.commands.registerCommand('batmam.review', () => {
            const editor = vscode.window.activeTextEditor;
            if (editor) {
                const filePath = editor.document.uri.fsPath;
                runBatmamSkill(`/review ${filePath}`);
            } else {
                runBatmamSkill('/review');
            }
        })
    );

    // ── Generate Tests ──
    context.subscriptions.push(
        vscode.commands.registerCommand('batmam.generateTests', () => {
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

            runBatmamSkill(`/test ${target}`);
        })
    );

    // ── Diff View ──
    context.subscriptions.push(
        vscode.commands.registerCommand('batmam.diffView', () => {
            const workspaceFolder = vscode.workspace.workspaceFolders?.[0]?.uri.fsPath;
            if (!workspaceFolder) return;
            runBatmamCommand('Mostre o git diff completo das mudanças atuais com explicação de cada alteração.');
        })
    );

    // ── Plan Mode ──
    context.subscriptions.push(
        vscode.commands.registerCommand('batmam.planMode', async () => {
            const choice = await vscode.window.showQuickPick(
                ['Ativar Plan Mode', 'Desativar Plan Mode'],
                { placeHolder: '🦇 Plan Mode — somente leitura' }
            );
            if (choice === 'Ativar Plan Mode') {
                runBatmamCommand('/plan');
                vscode.window.showInformationMessage('🦇 Plan Mode ativado — somente leitura');
            } else if (choice === 'Desativar Plan Mode') {
                runBatmamCommand('/plan off');
                vscode.window.showInformationMessage('🦇 Plan Mode desativado');
            }
        })
    );
}

/**
 * Abre o Batmam em um terminal integrado.
 */
function openBatmamTerminal() {
    const workspaceFolder = vscode.workspace.workspaceFolders?.[0]?.uri.fsPath || os.homedir();
    const config = vscode.workspace.getConfiguration('batmam');
    const model = config.get('model', 'gpt-4.1');
    const autoApprove = config.get('autoApprove', false);
    const planMode = config.get('planModeDefault', false);

    const batmamCmd = getBatmamCommand();

    let args = [...batmamCmd.args];
    if (model) args.push('-m', model);
    if (autoApprove) args.push('-y');

    if (batmamTerminal && batmamTerminal.exitStatus === undefined) {
        batmamTerminal.show();
        return;
    }

    batmamTerminal = vscode.window.createTerminal({
        name: '🦇 Batmam',
        cwd: workspaceFolder,
        shellPath: batmamCmd.shell,
        shellArgs: args,
        iconPath: new vscode.ThemeIcon('hubot'),
    });

    batmamTerminal.show();

    if (planMode) {
        setTimeout(() => {
            batmamTerminal.sendText('/plan');
        }, 2000);
    }
}

/**
 * Roda um comando no Batmam via terminal.
 */
function runBatmamCommand(prompt, cwd) {
    const workspaceFolder = cwd || vscode.workspace.workspaceFolders?.[0]?.uri.fsPath || os.homedir();
    const batmamCmd = getBatmamCommand();
    const config = vscode.workspace.getConfiguration('batmam');
    const model = config.get('model', 'gpt-4.1');

    const terminal = vscode.window.createTerminal({
        name: `🦇 ${prompt.substring(0, 30)}...`,
        cwd: workspaceFolder,
        shellPath: batmamCmd.shell,
        shellArgs: [...batmamCmd.args, prompt],
        iconPath: new vscode.ThemeIcon('hubot'),
    });

    terminal.show();
}

/**
 * Roda um skill do Batmam.
 */
function runBatmamSkill(skillCommand, cwd) {
    // Para skills, enviamos o comando via terminal existente ou novo
    if (batmamTerminal && batmamTerminal.exitStatus === undefined) {
        batmamTerminal.show();
        batmamTerminal.sendText(skillCommand);
    } else {
        openBatmamTerminal();
        // Aguarda terminal iniciar e envia o skill
        setTimeout(() => {
            if (batmamTerminal) {
                batmamTerminal.sendText(skillCommand);
            }
        }, 3000);
    }
}

/**
 * Pega código selecionado e envia ao Batmam.
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

    runBatmamCommand(prompt);
}

/**
 * Detecta como executar o Batmam.
 */
function getBatmamCommand() {
    const config = vscode.workspace.getConfiguration('batmam');
    const customPython = config.get('pythonPath', '');

    if (customPython) {
        return { shell: customPython, args: ['-m', 'batmam'] };
    }

    const fs = require('fs');
    if (fs.existsSync(BATMAM_BIN)) {
        return { shell: BATMAM_BIN, args: [] };
    }

    if (fs.existsSync(BATMAM_PYTHON)) {
        return { shell: BATMAM_PYTHON, args: ['-m', 'batmam'] };
    }

    return { shell: 'python3', args: ['-m', 'batmam'] };
}

function deactivate() {
    if (outputChannel) {
        outputChannel.dispose();
    }
}

module.exports = { activate, deactivate };

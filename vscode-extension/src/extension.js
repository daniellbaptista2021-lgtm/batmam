const vscode = require('vscode');
const { exec, spawn } = require('child_process');
const path = require('path');
const os = require('os');

/**
 * Batmam VS Code Extension
 * Integra o agente Batmam diretamente no editor.
 */

const BATMAM_HOME = path.join(os.homedir(), '.batmam');
const BATMAM_BIN = path.join(BATMAM_HOME, 'bin', 'batmam');
const BATMAM_PYTHON = path.join(BATMAM_HOME, 'app', '.venv', 'bin', 'python');

let outputChannel;
let batmamTerminal;

function activate(context) {
    outputChannel = vscode.window.createOutputChannel('Batmam');
    outputChannel.appendLine('Batmam extension ativada');

    // Comando: Abrir Batmam no Terminal
    context.subscriptions.push(
        vscode.commands.registerCommand('batmam.openInTerminal', () => {
            openBatmamTerminal();
        })
    );

    // Comando: Abrir Painel (abre terminal integrado)
    context.subscriptions.push(
        vscode.commands.registerCommand('batmam.open', () => {
            openBatmamTerminal();
        })
    );

    // Comando: Perguntar ao Batmam
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

    // Comando: Explicar seleção
    context.subscriptions.push(
        vscode.commands.registerCommand('batmam.explainSelection', () => {
            handleSelection('Explique este código em detalhes:');
        })
    );

    // Comando: Corrigir seleção
    context.subscriptions.push(
        vscode.commands.registerCommand('batmam.fixSelection', () => {
            handleSelection('Encontre e corrija bugs neste código:');
        })
    );

    // Comando: Refatorar seleção
    context.subscriptions.push(
        vscode.commands.registerCommand('batmam.refactorSelection', () => {
            handleSelection('Refatore este código para melhor legibilidade e performance:');
        })
    );
}

/**
 * Abre o Batmam em um terminal integrado do VS Code.
 */
function openBatmamTerminal() {
    const workspaceFolder = vscode.workspace.workspaceFolders?.[0]?.uri.fsPath || os.homedir();
    const config = vscode.workspace.getConfiguration('batmam');
    const model = config.get('model', 'gpt-4.1');
    const autoApprove = config.get('autoApprove', false);

    // Detecta o executável
    const batmamCmd = getBatmamCommand();

    let args = ['-m', 'batmam'];
    if (model) args.push('-m', model);
    if (autoApprove) args.push('-y');

    // Reutiliza terminal existente ou cria novo
    if (batmamTerminal && batmamTerminal.exitStatus === undefined) {
        batmamTerminal.show();
        return;
    }

    batmamTerminal = vscode.window.createTerminal({
        name: '🦇 Batmam',
        cwd: workspaceFolder,
        shellPath: batmamCmd.shell,
        shellArgs: batmamCmd.args,
        iconPath: new vscode.ThemeIcon('hubot'),
    });

    batmamTerminal.show();
}

/**
 * Roda um comando no Batmam via terminal.
 */
function runBatmamCommand(prompt) {
    const workspaceFolder = vscode.workspace.workspaceFolders?.[0]?.uri.fsPath || os.homedir();
    const config = vscode.workspace.getConfiguration('batmam');
    const model = config.get('model', 'gpt-4.1');

    const batmamCmd = getBatmamCommand();

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

    // Prioridade: config > ~/.batmam/bin/batmam > python -m batmam
    if (customPython) {
        return { shell: customPython, args: ['-m', 'batmam'] };
    }

    // Tenta usar o wrapper instalado
    const fs = require('fs');
    if (fs.existsSync(BATMAM_BIN)) {
        return { shell: BATMAM_BIN, args: [] };
    }

    // Fallback: usa python do venv do batmam
    if (fs.existsSync(BATMAM_PYTHON)) {
        return { shell: BATMAM_PYTHON, args: ['-m', 'batmam'] };
    }

    // Último recurso: python3 do sistema
    return { shell: 'python3', args: ['-m', 'batmam'] };
}

function deactivate() {
    if (outputChannel) {
        outputChannel.dispose();
    }
}

module.exports = { activate, deactivate };

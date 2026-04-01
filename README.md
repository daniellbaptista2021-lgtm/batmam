# 🦇 Batmam

**Agente de código AI no terminal** — similar ao Claude Code, open-source, powered by OpenAI.

Lê, escreve, edita código, executa comandos, busca na web, gerencia projetos — tudo direto do terminal.

## Instalação

### Rápida (recomendada)

```bash
git clone https://github.com/daniel/batmam.git
cd batmam
./install.sh
```

O instalador automaticamente:
- Instala Python 3 e dependências se necessário
- Cria ambiente virtual isolado
- Configura o comando `batmam` globalmente
- Pede sua API key da OpenAI

### Manual

```bash
git clone https://github.com/daniel/batmam.git
cd batmam
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
```

### VPS (Hostinger, DigitalOcean, AWS, etc.)

```bash
ssh usuario@seu-servidor
git clone https://github.com/daniel/batmam.git
cd batmam
./install.sh
```

### Configuração

```bash
# Defina sua API key
echo 'OPENAI_API_KEY=sk-...' > ~/.batmam/app/.env
echo 'BATMAM_MODEL=gpt-4.1' >> ~/.batmam/app/.env
```

## Uso

```bash
# REPL interativo
batmam

# Prompt direto
batmam "crie um servidor Flask com autenticação JWT"

# Escolher modelo
batmam -m gpt-4.1-mini

# Auto-approve (sem confirmações)
batmam -y

# Em um diretório específico
batmam -C /caminho/do/projeto
```

## Comandos Internos

| Comando | Descrição |
|---------|-----------|
| `/help` | Mostra ajuda |
| `/cd <dir>` | Muda diretório |
| `/status` | git status |
| `/diff` | git diff |
| `/sessions` | Lista sessões salvas |
| `/resume <id>` | Retoma sessão |
| `/save` | Salva sessão |
| `/clear` | Limpa histórico |
| `/model [nome]` | Mostra/altera modelo |
| `/tokens` | Mostra uso de tokens |
| `/memory` | Gerencia memórias |
| `/tools` | Lista ferramentas |
| `/hooks` | Lista hooks |
| `/plugins` | Lista plugins |
| `/mcp` | Lista servidores MCP |
| `/init` | Cria BATMAM.md no projeto |
| `/approve` | Auto-approve na sessão |
| `!comando` | Executa bash direto |

## Ferramentas

| Tool | Descrição |
|------|-----------|
| `bash` | Executa comandos no terminal |
| `read` | Lê arquivos com números de linha |
| `write` | Cria/sobrescreve arquivos |
| `edit` | Edição cirúrgica por substituição |
| `glob` | Busca arquivos por padrão |
| `grep` | Busca conteúdo com regex |
| `web_search` | Busca na web |
| `web_fetch` | Fetch de URLs |
| `notebook_edit` | Edita Jupyter notebooks |
| `agent` | Lança sub-agentes |

## BATMAM.md

Crie um arquivo `BATMAM.md` na raiz do seu projeto com instruções específicas. O Batmam lê automaticamente, similar ao `CLAUDE.md`:

```markdown
# Instruções do Projeto

- Este projeto usa Django 5.0 com PostgreSQL
- Rode testes com: pytest
- Siga o padrão de código do projeto
```

## Extensões

### Hooks

Configure em `~/.batmam/settings.json`:

```json
{
  "hooks": {
    "post_tool_call": [
      {
        "tool": "bash",
        "command": "echo 'Comando executado: $tool_args'",
        "enabled": true
      }
    ]
  }
}
```

### MCP Servers

```json
{
  "mcp_servers": {
    "filesystem": {
      "command": "npx",
      "args": ["-y", "@modelcontextprotocol/server-filesystem", "/home/user"]
    }
  }
}
```

### Plugins

Coloque plugins Python em `~/.batmam/plugins/`:

```python
# ~/.batmam/plugins/meu_plugin.py
from batmam.tools.base import BaseTool

class MeuTool(BaseTool):
    name = "meu_tool"
    description = "Minha ferramenta customizada"

    def get_schema(self):
        return {"type": "object", "properties": {}}

    def execute(self, **kwargs):
        return "Resultado!"

def register(registry, hook_runner):
    registry.register(MeuTool())
```

### VS Code

1. Copie `vscode-extension/` para seus extensions
2. Ou instale via: `cd vscode-extension && npx vsce package && code --install-extension batmam-0.1.0.vsix`

Atalhos:
- `Ctrl+Shift+B` — Abre o Batmam
- `Ctrl+Shift+I` — Pergunta rápida
- Clique direito → Batmam: Explicar/Corrigir/Refatorar

## Estrutura

```
~/.batmam/
├── app/            # Código do Batmam
├── bin/batmam      # CLI global
├── sessions/       # Sessões salvas
├── memory/         # Memória persistente
├── plugins/        # Plugins customizados
└── settings.json   # Configurações
```

## Modelos Suportados

| Modelo | Uso |
|--------|-----|
| `gpt-4.1` | Melhor para código (padrão) |
| `gpt-4.1-mini` | Mais rápido, mais barato |
| `gpt-4.1-nano` | Ultra-rápido |
| `gpt-4o` | Multimodal |
| `o3` | Reasoning avançado |
| `o4-mini` | Reasoning rápido |

Troque em runtime: `/model gpt-4.1-mini`

## Desinstalar

```bash
./install.sh --uninstall
# Para remover tudo (incluindo sessões):
rm -rf ~/.batmam
```

## Licença

MIT — Criado por Daniel

"""Template estruturado para CLOW.md — instrucoes do projeto.

Gera CLOW.md automaticamente baseado no tipo de projeto detectado.
Usado pelo /init e sugerido no primeiro acesso a um projeto.
"""

from __future__ import annotations

import subprocess
import time
from pathlib import Path

CLOW_MD_TEMPLATE = '''# Instrucoes do Projeto

## Sobre
- **Projeto:** {project_name}
- **Tipo:** {project_type}
- **Linguagem:** {language}
- **Gerado em:** {date}

## Regras Gerais
- Sempre escrever codigo limpo e comentado
- Seguir convencoes da linguagem ({language})
- Nunca commitar secrets ou credenciais (use .env)
- Testes sao obrigatorios para features novas
- Commits seguem Conventional Commits (feat/fix/docs/refactor)

## Seguranca
- NUNCA incluir API keys, tokens ou senhas no codigo
- Usar variaveis de ambiente (.env) para credenciais
- Validar TODA entrada de usuario
- Sanitizar dados antes de queries SQL
- Usar HTTPS em producao
- Habilitar CORS apenas para dominios necessarios
- Senhas com bcrypt/PBKDF2, tokens com secrets.token_urlsafe
- Nunca logar dados sensiveis

## Estrutura do Projeto
{project_structure}

## Convencoes de Codigo
{code_conventions}

## Como Rodar
{how_to_run}

## Como Testar
{how_to_test}

## Deploy
{deploy_instructions}

## Erros Comuns e Solucoes
{common_issues}

## Emergency Rollback
Se algo der errado em producao:
1. `git log --oneline -5` — identifica o ultimo commit bom
2. `git revert HEAD` — reverte o ultimo commit
3. Roda os testes: `{test_command}`
4. Se passar, faz deploy: `{deploy_command}`
5. Se nao passar, volta mais um: `git revert HEAD~1`

Alternativa rapida:
```bash
git stash && git checkout {main_branch} && {deploy_command}
```

## Dependencias Importantes
{dependencies}

## Notas
- Este arquivo e lido pelo Clow automaticamente
- Edite conforme o projeto evolui
- Quanto mais detalhado, melhor o Clow trabalha
'''

# ── Templates por tipo de projeto ─────────────────────────────

PROJECT_TEMPLATES = {
    "python": {
        "language": "Python",
        "code_conventions": (
            "- PEP 8 para formatacao\n"
            "- Type hints em funcoes publicas\n"
            "- Docstrings em todas as classes e funcoes publicas\n"
            "- Imports organizados: stdlib, terceiros, locais\n"
            "- f-strings em vez de .format() ou %\n"
            "- Excecoes especificas, nunca except Exception generico"
        ),
        "how_to_run": (
            "```bash\n"
            "python -m venv .venv\n"
            "source .venv/bin/activate  # Linux/Mac\n"
            ".venv\\Scripts\\activate     # Windows\n"
            "pip install -r requirements.txt\n"
            "python main.py\n"
            "```"
        ),
        "how_to_test": "```bash\npytest tests/ -v\npytest tests/ -v --cov=src --cov-report=html\n```",
        "test_command": "pytest tests/ -v",
        "deploy_command": "git push origin main",
        "dependencies": "Ver requirements.txt ou pyproject.toml",
    },
    "node": {
        "language": "JavaScript/TypeScript",
        "code_conventions": (
            "- ESLint + Prettier para formatacao\n"
            "- TypeScript quando possivel\n"
            "- Async/await em vez de callbacks\n"
            "- Destructuring para imports\n"
            "- Const por padrao, let quando necessario, nunca var"
        ),
        "how_to_run": "```bash\nnpm install\nnpm run dev\n```",
        "how_to_test": "```bash\nnpm test\nnpm run test:coverage\n```",
        "test_command": "npm test",
        "deploy_command": "npm run build && npm run deploy",
        "dependencies": "Ver package.json",
    },
    "react": {
        "language": "React/TypeScript",
        "code_conventions": (
            "- Componentes funcionais com hooks\n"
            "- Props tipadas com TypeScript interfaces\n"
            "- Estado global com Context ou Zustand\n"
            "- CSS Modules ou Tailwind\n"
            "- Componentes pequenos e reutilizaveis"
        ),
        "how_to_run": "```bash\nnpm install\nnpm run dev\n```",
        "how_to_test": "```bash\nnpm test\n```",
        "test_command": "npm test",
        "deploy_command": "npm run build && vercel --prod",
        "dependencies": "Ver package.json",
    },
    "generic": {
        "language": "Detectar automaticamente",
        "code_conventions": "Seguir convencoes padrao da linguagem do projeto",
        "how_to_run": "Documentar aqui como rodar o projeto",
        "how_to_test": "Documentar aqui como rodar testes",
        "test_command": "echo 'configurar comando de teste'",
        "deploy_command": "echo 'configurar comando de deploy'",
        "dependencies": "Listar dependencias principais",
    },
}

COMMON_ISSUES = {
    "python": (
        "- **ImportError:** Verifique se o venv esta ativado e dependencias instaladas\n"
        "- **ModuleNotFoundError:** `pip install {modulo}` ou verificar pyproject.toml\n"
        "- **PermissionError:** Verificar permissoes do arquivo/diretorio\n"
        "- **ConnectionError:** Verificar se o servico (DB, Redis, API) esta rodando\n"
        "- **SQLAlchemy/DB errors:** Verificar se migrations estao atualizadas"
    ),
    "node": (
        "- **Module not found:** `npm install` ou verificar package.json\n"
        "- **EADDRINUSE:** Porta ja em uso, matar processo: `lsof -i :PORT`\n"
        "- **CORS errors:** Verificar config de CORS no backend\n"
        "- **Build errors:** Limpar cache: `rm -rf node_modules && npm install`"
    ),
    "react": (
        "- **Hydration mismatch:** Verificar se server e client renderizam igual\n"
        "- **Hook errors:** Hooks so dentro de componentes, na ordem, sem condicionais\n"
        "- **Build errors:** `rm -rf .next && npm run build`\n"
        "- **Type errors:** Verificar interfaces TypeScript"
    ),
    "generic": "Documentar erros comuns do projeto aqui",
}


# ── Funcoes de deteccao ───────────────────────────────────────

def detect_project_type(cwd: str) -> str:
    """Detecta tipo do projeto baseado nos arquivos presentes."""
    path = Path(cwd)
    if (path / "pyproject.toml").exists() or (path / "requirements.txt").exists() or (path / "setup.py").exists():
        return "python"
    if (path / "package.json").exists():
        try:
            pkg = (path / "package.json").read_text(encoding="utf-8")
            if "react" in pkg or "next" in pkg:
                return "react"
        except OSError:
            pass
        return "node"
    return "generic"


def detect_project_structure(cwd: str) -> str:
    """Gera descricao da estrutura do projeto."""
    path = Path(cwd)
    lines = []
    ignore = {
        ".git", "node_modules", "__pycache__", ".venv", "venv",
        ".mypy_cache", ".pytest_cache", "dist", "build", ".next", ".cache",
        ".tox", "htmlcov", ".eggs",
    }

    try:
        items = sorted(path.iterdir())
    except PermissionError:
        return "Sem permissao para ler diretorio"

    for item in items:
        if item.name.startswith(".") and item.name not in (".env.example", ".gitignore"):
            continue
        if item.name in ignore:
            continue
        if item.is_dir():
            lines.append(f"- `{item.name}/` — descrever proposito")
            try:
                subs = sorted(item.iterdir())[:5]
                for sub in subs:
                    if sub.name not in ignore and not sub.name.startswith("."):
                        lines.append(f"  - `{sub.name}`")
                total = sum(1 for _ in item.iterdir())
                if total > 5:
                    lines.append(f"  - ... (+{total - 5} itens)")
            except PermissionError:
                pass
        else:
            lines.append(f"- `{item.name}`")

    return "\n".join(lines) if lines else "Documentar estrutura do projeto"


def detect_main_branch(cwd: str) -> str:
    """Detecta branch principal do repositorio."""
    try:
        r = subprocess.run(
            ["git", "branch", "--show-current"],
            cwd=cwd, capture_output=True, text=True,
        )
        if r.returncode == 0 and r.stdout.strip():
            return r.stdout.strip()
    except Exception:
        pass
    return "main"


def generate_clow_md(cwd: str, project_name: str = "") -> str:
    """Gera CLOW.md completo baseado no projeto detectado."""
    project_type = detect_project_type(cwd)
    tpl = PROJECT_TEMPLATES[project_type]

    if not project_name:
        project_name = Path(cwd).name

    return CLOW_MD_TEMPLATE.format(
        project_name=project_name,
        project_type=project_type,
        language=tpl["language"],
        date=time.strftime("%d/%m/%Y"),
        project_structure=detect_project_structure(cwd),
        code_conventions=tpl["code_conventions"],
        how_to_run=tpl["how_to_run"],
        how_to_test=tpl["how_to_test"],
        deploy_instructions=tpl.get("deploy_command", "Configurar deploy"),
        common_issues=COMMON_ISSUES.get(project_type, COMMON_ISSUES["generic"]),
        test_command=tpl["test_command"],
        deploy_command=tpl["deploy_command"],
        main_branch=detect_main_branch(cwd),
        dependencies=tpl["dependencies"],
    )


def should_suggest_init(cwd: str) -> bool:
    """Retorna True se o diretorio parece um projeto sem CLOW.md."""
    path = Path(cwd)
    if (path / "CLOW.md").exists():
        return False
    project_markers = [
        "pyproject.toml", "requirements.txt", "setup.py", "package.json",
        "Cargo.toml", "go.mod", "Gemfile", "composer.json", "pom.xml",
    ]
    return any((path / m).exists() for m in project_markers)

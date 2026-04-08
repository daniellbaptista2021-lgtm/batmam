"""Sistema de Skills do Batmam.

Skills sao prompts especializados invocaveis via /comando.
Similar ao Skill system do Claude Code (/commit, /review-pr, /simplify).
"""

from __future__ import annotations
import importlib.util
from pathlib import Path
from dataclasses import dataclass, field
from typing import Any
from . import config


@dataclass
class Skill:
    """Definicao de uma skill."""
    name: str
    description: str
    prompt_template: str
    aliases: list[str] = field(default_factory=list)
    requires_args: bool = False
    args_description: str = ""


# Skills built-in
BUILTIN_SKILLS: list[Skill] = [
    Skill(
        name="commit",
        description="Analisa mudancas e cria um commit git com mensagem adequada",
        aliases=["ci"],
        prompt_template="""Analise as mudancas no repositorio git atual e crie um commit.

Passos:
1. Rode `git status` e `git diff --staged` para ver as mudancas
2. Se nao houver nada staged, rode `git diff` para ver unstaged changes
3. Analise as mudancas e crie uma mensagem de commit concisa e descritiva
4. Formate: tipo(escopo): descricao curta
   Tipos: feat, fix, refactor, docs, test, chore, style
5. Faca o commit (git add dos arquivos relevantes se necessario + git commit)
6. NAO faca push a menos que explicitamente pedido

{args}""",
    ),
    Skill(
        name="review-pr",
        description="Revisa codigo da PR atual ou especificada",
        aliases=["review", "pr"],
        requires_args=False,
        args_description="Numero da PR (opcional)",
        prompt_template="""Revise o codigo das mudancas atuais (ou da PR especificada).

{args}

Passos:
1. Rode `git diff main...HEAD` (ou `git diff` se nao tem branch)
2. Analise CADA arquivo modificado:
   - Bugs potenciais
   - Problemas de seguranca (injection, XSS, etc)
   - Performance
   - Legibilidade e manutencao
   - Testes faltando
3. De feedback construtivo com sugestoes especificas
4. Classifique: APROVADO, APROVADO COM RESSALVAS, ou MUDANCAS NECESSARIAS""",
    ),
    Skill(
        name="simplify",
        description="Revisa codigo alterado buscando simplificacoes e melhorias",
        aliases=["clean", "refactor"],
        prompt_template="""Revise o codigo que foi alterado recentemente e simplifique.

{args}

Passos:
1. Rode `git diff` para ver mudancas recentes
2. Analise o codigo alterado buscando:
   - Codigo duplicado que pode ser reutilizado
   - Abstrações desnecessarias
   - Complexidade que pode ser reduzida
   - Nomes que podem ser melhorados
3. Aplique as simplificacoes usando edit
4. NAO mude comportamento, apenas simplifique""",
    ),
    Skill(
        name="test",
        description="Roda os testes do projeto e corrige falhas",
        aliases=["tests"],
        prompt_template="""Rode os testes do projeto e corrija qualquer falha.

{args}

Passos:
1. Identifique o framework de testes (pytest, jest, go test, etc)
2. Rode os testes
3. Se houver falhas, analise e corrija
4. Re-rode para confirmar que passam""",
    ),
    Skill(
        name="explain",
        description="Explica o codigo ou arquivo especificado em detalhe",
        aliases=["doc"],
        requires_args=True,
        args_description="Arquivo ou funcao para explicar",
        prompt_template="""Explique o codigo especificado em detalhe.

{args}

Passos:
1. Leia o arquivo/funcao mencionado
2. Explique:
   - O que faz (visao geral)
   - Como funciona (passo a passo)
   - Dependencias e relacoes com outros modulos
   - Pontos de atencao ou complexidade
3. Use linguagem clara e acessivel""",
    ),
    Skill(
        name="init",
        description="Inicializa BATMAM.md no projeto com contexto detectado automaticamente",
        aliases=["setup"],
        prompt_template="""Crie um arquivo BATMAM.md na raiz do projeto atual.

{args}

Passos:
1. Analise o projeto: leia package.json, requirements.txt, Cargo.toml, go.mod, etc
2. Identifique: linguagem, framework, estrutura, comandos de build/test
3. Crie BATMAM.md com:
   - Descricao do projeto
   - Stack tecnologica
   - Comandos uteis (build, test, lint)
   - Convencoes de codigo
   - Instrucoes especificas para o agente""",
    ),
    Skill(
        name="fix",
        description="Analisa e corrige erros/bugs no codigo",
        aliases=["debug"],
        requires_args=True,
        args_description="Descricao do erro ou arquivo com problema",
        prompt_template="""Analise e corrija o erro descrito.

{args}

Passos:
1. Entenda o erro descrito
2. Localize o codigo relevante
3. Identifique a causa raiz
4. Aplique a correcao minima necessaria
5. Verifique se a correcao nao quebra nada""",
    ),
    Skill(
        name="deploy",
        description="Prepara e executa deploy do projeto",
        aliases=[],
        prompt_template="""Prepare e execute o deploy do projeto.

{args}

Passos:
1. Identifique o metodo de deploy (docker, vercel, aws, etc)
2. Verifique se o build funciona
3. Verifique se os testes passam
4. Execute o deploy
5. Verifique se deu certo""",
    ),
]


class SkillManager:
    """Gerencia skills disponiveis."""

    def __init__(self) -> None:
        self._skills: dict[str, Skill] = {}
        self._alias_map: dict[str, str] = {}
        # Registra built-ins
        for skill in BUILTIN_SKILLS:
            self.register(skill)
        # Carrega skills customizadas
        self._load_custom_skills()

    def register(self, skill: Skill) -> None:
        """Registra uma skill."""
        self._skills[skill.name] = skill
        for alias in skill.aliases:
            self._alias_map[alias] = skill.name

    def get(self, name: str) -> Skill | None:
        """Busca skill por nome ou alias."""
        resolved = self._alias_map.get(name, name)
        return self._skills.get(resolved)

    def list_all(self) -> list[Skill]:
        return list(self._skills.values())

    def expand(self, name: str, args: str = "") -> str | None:
        """Expande uma skill em prompt completo."""
        skill = self.get(name)
        if not skill:
            return None
        return skill.prompt_template.format(args=args if args else "")

    def _load_custom_skills(self) -> None:
        """Carrega skills customizadas de ~/.batmam/skills/"""
        skills_dir = config.BATMAM_HOME / "skills"
        if not skills_dir.exists():
            return

        for skill_file in skills_dir.glob("*.py"):
            if skill_file.name.startswith("_"):
                continue
            try:
                spec = importlib.util.spec_from_file_location(
                    f"batmam_skill_{skill_file.stem}", skill_file
                )
                if spec and spec.loader:
                    module = importlib.util.module_from_spec(spec)
                    spec.loader.exec_module(module)
                    if hasattr(module, "skill"):
                        self.register(module.skill)
                    elif hasattr(module, "skills"):
                        for s in module.skills:
                            self.register(s)
            except Exception:
                continue

        # Carrega skills .md (prompt-only)
        for md_file in skills_dir.glob("*.md"):
            if md_file.name.startswith("_"):
                continue
            try:
                content = md_file.read_text(encoding="utf-8")
                name = md_file.stem
                # Primeira linha eh a descricao
                lines = content.strip().splitlines()
                desc = lines[0].lstrip("# ").strip() if lines else name
                prompt = "\n".join(lines[1:]).strip() if len(lines) > 1 else content
                self.register(Skill(
                    name=name,
                    description=desc,
                    prompt_template=prompt + "\n{args}",
                ))
            except Exception:
                continue

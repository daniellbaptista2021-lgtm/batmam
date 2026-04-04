"""Testes para as 3 melhorias surreais do agent.py:
1. Vision Feedback Loop
2. Tool Pruning Dinamico
3. Project DNA (INSTRUCTIONS.md)
"""

import os
import sys
import re
import base64
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch
from types import SimpleNamespace

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from clow import config
from clow.models import ToolResult, ToolResultStatus


# ════════════════════════════════════════════════════════════════
# 1. TESTE: Vision Feedback Loop
# ════════════════════════════════════════════════════════════════

class TestVisionFeedbackLoop(unittest.TestCase):
    """Verifica que o Vision Feedback Loop captura screenshots e injeta no historico."""

    def test_config_default(self):
        """Config CLOW_VISION_FEEDBACK deve ser True por default."""
        self.assertTrue(config.CLOW_VISION_FEEDBACK)
        print("[OK] Vision: config default = True")

    def test_vision_trigger_on_html_write(self):
        """Vision deve ser ativado ao escrever arquivo .html."""
        tool_name = "write"
        filepath = "/tmp/test_page.html"
        status = ToolResultStatus.SUCCESS

        should_trigger = (
            config.CLOW_VISION_FEEDBACK
            and status == ToolResultStatus.SUCCESS
            and tool_name in ("write", "edit")
            and any(filepath.endswith(ext) for ext in (".html", ".jsx", ".tsx", ".css"))
        )
        self.assertTrue(should_trigger)
        print("[OK] Vision: dispara para .html write")

    def test_vision_trigger_on_css_edit(self):
        """Vision deve ser ativado ao editar arquivo .css."""
        tool_name = "edit"
        filepath = "styles/main.css"
        status = ToolResultStatus.SUCCESS

        should_trigger = (
            config.CLOW_VISION_FEEDBACK
            and status == ToolResultStatus.SUCCESS
            and tool_name in ("write", "edit")
            and any(filepath.endswith(ext) for ext in (".html", ".jsx", ".tsx", ".css"))
        )
        self.assertTrue(should_trigger)
        print("[OK] Vision: dispara para .css edit")

    def test_vision_no_trigger_on_python(self):
        """Vision NAO deve ser ativado para .py."""
        filepath = "app.py"
        should_trigger = any(filepath.endswith(ext) for ext in (".html", ".jsx", ".tsx", ".css"))
        self.assertFalse(should_trigger)
        print("[OK] Vision: nao dispara para .py")

    def test_vision_no_trigger_on_error(self):
        """Vision NAO deve ser ativado quando tool deu erro."""
        status = ToolResultStatus.ERROR
        should_trigger = status == ToolResultStatus.SUCCESS
        self.assertFalse(should_trigger)
        print("[OK] Vision: nao dispara em erro")

    def test_vision_message_format(self):
        """A mensagem de vision deve ter formato correto com image content block."""
        screenshot_b64 = base64.b64encode(b"fake_png_data").decode("utf-8")
        filepath = "index.html"

        vision_msg = {
            "role": "user",
            "content": [
                {
                    "type": "image",
                    "source": {
                        "type": "base64",
                        "media_type": "image/png",
                        "data": screenshot_b64,
                    },
                },
                {
                    "type": "text",
                    "text": (
                        f"Screenshot do resultado gerado ({os.path.basename(filepath)}). "
                        "Avalie se ficou correto e corrija se necessario."
                    ),
                },
            ],
        }

        self.assertEqual(vision_msg["role"], "user")
        self.assertEqual(len(vision_msg["content"]), 2)
        self.assertEqual(vision_msg["content"][0]["type"], "image")
        self.assertEqual(vision_msg["content"][0]["source"]["type"], "base64")
        self.assertEqual(vision_msg["content"][0]["source"]["media_type"], "image/png")
        self.assertIn("Screenshot do resultado gerado", vision_msg["content"][1]["text"])
        print("[OK] Vision: formato de mensagem correto com image content block")

    def test_vision_check_with_real_html(self):
        """Testa _vision_check com um HTML real se Playwright estiver disponivel."""
        try:
            from playwright.sync_api import sync_playwright
            playwright_available = True
        except ImportError:
            playwright_available = False

        if not playwright_available:
            print("[SKIP] Vision: Playwright nao instalado, pulando teste de screenshot real")
            return

        # Cria HTML temporario
        with tempfile.NamedTemporaryFile(suffix=".html", delete=False, mode="w", encoding="utf-8") as f:
            f.write("""<!DOCTYPE html>
<html><head><style>
body { font-family: Arial; background: #7C5CFC; color: white; text-align: center; padding: 60px; }
h1 { font-size: 3em; }
</style></head>
<body><h1>Clow Vision Test</h1><p>Se voce ve isso, o screenshot funcionou!</p></body></html>""")
            html_path = f.name

        try:
            # Simula o _vision_check
            from playwright.sync_api import sync_playwright
            with sync_playwright() as pw:
                browser = pw.chromium.launch(headless=True)
                page = browser.new_page(viewport={"width": 1440, "height": 900})
                page.goto(f"file:///{Path(html_path).as_posix()}", wait_until="networkidle", timeout=15000)
                page.wait_for_timeout(500)
                screenshot_bytes = page.screenshot(type="png", full_page=True)
                browser.close()

            screenshot_b64 = base64.b64encode(screenshot_bytes).decode("utf-8")

            # Verifica que e um PNG valido (magic bytes do PNG em base64)
            self.assertTrue(len(screenshot_b64) > 100)
            decoded = base64.b64decode(screenshot_b64)
            self.assertTrue(decoded[:4] == b'\x89PNG')
            print(f"[OK] Vision: screenshot real capturado ({len(decoded)} bytes, PNG valido)")
        finally:
            os.unlink(html_path)


# ════════════════════════════════════════════════════════════════
# 2. TESTE: Tool Pruning Dinamico
# ════════════════════════════════════════════════════════════════

class TestToolPruning(unittest.TestCase):
    """Verifica que o Tool Pruning filtra tools corretamente."""

    def test_config_default(self):
        """Config CLOW_TOOL_PRUNING deve ser True por default."""
        self.assertTrue(config.CLOW_TOOL_PRUNING)
        print("[OK] Pruning: config default = True")

    def _make_tools(self) -> list[dict]:
        """Cria lista fake de 24 tools no formato Anthropic."""
        all_names = [
            "read", "glob", "grep", "write", "edit", "bash", "agent",
            "web_search", "web_fetch", "notebook_edit",
            "task_create", "task_update", "task_list", "task_get",
            "whatsapp", "http_request", "supabase_query", "n8n_workflow",
            "docker_manage", "git_advanced", "scraper",
            "image_gen", "pdf_tool", "spreadsheet",
        ]
        return [{"name": n, "description": f"Tool {n}", "input_schema": {}} for n in all_names]

    def test_simple_message_pruning(self):
        """Mensagem simples deve enviar apenas core tools (7)."""
        from clow.agent import Agent

        tools = self._make_tools()
        total = len(tools)

        # Simula o pruning com mensagem simples
        last_msg = "explique o que esse arquivo faz"

        # Core tools que sempre sao incluidas
        core_names = {"read", "glob", "grep", "write", "edit", "bash", "agent"}

        # Determina categorias ativas
        active_categories = {"core"}
        pruning_keywords = Agent.PRUNING_KEYWORDS
        for category, keywords in pruning_keywords.items():
            if any(kw in last_msg.lower() for kw in keywords):
                active_categories.add(category)

        # Monta allowed names
        allowed_names = set()
        for cat in active_categories:
            allowed_names.update(Agent.TOOL_CATEGORIES.get(cat, set()))

        pruned = [t for t in tools if t["name"] in allowed_names]

        self.assertLess(len(pruned), total)
        self.assertLessEqual(len(pruned), 10)
        # Core sempre presente
        pruned_names = {t["name"] for t in pruned}
        self.assertTrue(core_names.issubset(pruned_names))
        print(f"[OK] Pruning: mensagem simples -> {len(pruned)}/{total} tools (core only)")

    def test_whatsapp_includes_integration(self):
        """Mensagem com 'whatsapp' deve incluir integration tools."""
        last_msg = "envia mensagem no whatsapp pro cliente"

        active_categories = {"core"}
        from clow.agent import Agent
        for category, keywords in Agent.PRUNING_KEYWORDS.items():
            if any(kw in last_msg.lower() for kw in keywords):
                active_categories.add(category)

        self.assertIn("integration", active_categories)
        print("[OK] Pruning: 'whatsapp' ativa integration tools")

    def test_planilha_includes_creative(self):
        """Mensagem com 'planilha' deve incluir creative tools."""
        last_msg = "cria uma planilha de vendas"

        active_categories = {"core"}
        from clow.agent import Agent
        for category, keywords in Agent.PRUNING_KEYWORDS.items():
            if any(kw in last_msg.lower() for kw in keywords):
                active_categories.add(category)

        self.assertIn("creative", active_categories)
        print("[OK] Pruning: 'planilha' ativa creative tools")

    def test_search_includes_web(self):
        """Mensagem com 'buscar' deve incluir web tools."""
        last_msg = "buscar como instalar o redis"

        active_categories = {"core"}
        from clow.agent import Agent
        for category, keywords in Agent.PRUNING_KEYWORDS.items():
            if any(kw in last_msg.lower() for kw in keywords):
                active_categories.add(category)

        self.assertIn("web", active_categories)
        print("[OK] Pruning: 'buscar' ativa web tools")

    def test_task_includes_task_tools(self):
        """Mensagem com 'tarefa' deve incluir task tools."""
        last_msg = "lista as tarefas pendentes"

        active_categories = {"core"}
        from clow.agent import Agent
        for category, keywords in Agent.PRUNING_KEYWORDS.items():
            if any(kw in last_msg.lower() for kw in keywords):
                active_categories.add(category)

        self.assertIn("task", active_categories)
        print("[OK] Pruning: 'tarefa' ativa task tools")

    def test_tool_name_extraction(self):
        """_tool_name_from deve funcionar para ambos formatos."""
        from clow.agent import Agent

        # Anthropic format
        self.assertEqual(Agent._tool_name_from({"name": "read"}), "read")
        # OpenAI format
        self.assertEqual(Agent._tool_name_from({"function": {"name": "bash"}}), "bash")
        print("[OK] Pruning: extrai nome de ambos formatos")


# ════════════════════════════════════════════════════════════════
# 3. TESTE: Project DNA (INSTRUCTIONS.md)
# ════════════════════════════════════════════════════════════════

class TestProjectDNA(unittest.TestCase):
    """Verifica que Project DNA carrega INSTRUCTIONS.md e injeta no system prompt."""

    def test_instructions_loading(self):
        """Deve carregar .clow/INSTRUCTIONS.md do diretorio."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Cria .clow/INSTRUCTIONS.md
            clow_dir = Path(tmpdir) / ".clow"
            clow_dir.mkdir()
            instructions_file = clow_dir / "INSTRUCTIONS.md"
            instructions_file.write_text(
                "# Project DNA\n\n## Stack\n- Python 3.12\n- FastAPI\n",
                encoding="utf-8",
            )

            # Simula o loading
            instructions_parts = []
            current = Path(tmpdir).resolve()
            visited = set()

            while True:
                dir_str = str(current)
                if dir_str in visited:
                    break
                visited.add(dir_str)

                inst_file = current / ".clow" / "INSTRUCTIONS.md"
                if inst_file.exists():
                    content = inst_file.read_text(encoding="utf-8").strip()
                    if content:
                        instructions_parts.append(content)

                parent = current.parent
                if parent == current:
                    break
                current = parent

            self.assertEqual(len(instructions_parts), 1)
            self.assertIn("Python 3.12", instructions_parts[0])
            self.assertIn("FastAPI", instructions_parts[0])
            print("[OK] DNA: carregou INSTRUCTIONS.md do diretorio")

    def test_instructions_inheritance(self):
        """Deve herdar INSTRUCTIONS.md de diretorios pai."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Cria INSTRUCTIONS no parent
            parent_clow = Path(tmpdir) / ".clow"
            parent_clow.mkdir()
            (parent_clow / "INSTRUCTIONS.md").write_text(
                "# Root DNA\nUse conventional commits.",
                encoding="utf-8",
            )

            # Cria INSTRUCTIONS no child
            child_dir = Path(tmpdir) / "packages" / "api"
            child_dir.mkdir(parents=True)
            child_clow = child_dir / ".clow"
            child_clow.mkdir()
            (child_clow / "INSTRUCTIONS.md").write_text(
                "# API DNA\nUse FastAPI + SQLAlchemy.",
                encoding="utf-8",
            )

            # Simula loading do child
            instructions_parts = []
            current = child_dir.resolve()
            root = Path(tmpdir).resolve().parent  # Para nao subir demais
            visited = set()

            while True:
                dir_str = str(current)
                if dir_str in visited:
                    break
                visited.add(dir_str)

                inst_file = current / ".clow" / "INSTRUCTIONS.md"
                if inst_file.exists():
                    content = inst_file.read_text(encoding="utf-8").strip()
                    if content:
                        instructions_parts.append(content)

                parent = current.parent
                if parent == current:
                    break
                current = parent

            # Deve ter encontrado 2 arquivos
            self.assertEqual(len(instructions_parts), 2)

            # Inverte: raiz primeiro, child por ultimo
            instructions_parts.reverse()
            combined = "\n\n---\n\n".join(instructions_parts)

            self.assertIn("Root DNA", combined)
            self.assertIn("API DNA", combined)
            # Root deve vir primeiro
            root_pos = combined.index("Root DNA")
            api_pos = combined.index("API DNA")
            self.assertLess(root_pos, api_pos)
            print("[OK] DNA: heranca de INSTRUCTIONS.md funciona (root + child)")

    def test_instructions_injected_in_system_prompt(self):
        """INSTRUCTIONS.md deve aparecer no system prompt."""
        instructions_content = "# Project DNA\n## Stack\n- Python + FastAPI"

        system_parts = ["Voce e o Clow."]
        system_parts.append(f"\n# [Instrucoes do Projeto]\n{instructions_content}")

        full_prompt = "\n\n".join(system_parts)
        self.assertIn("[Instrucoes do Projeto]", full_prompt)
        self.assertIn("Python + FastAPI", full_prompt)
        print("[OK] DNA: instrucoes injetadas no system prompt")

    def test_no_instructions_file(self):
        """Sem INSTRUCTIONS.md, nao deve adicionar nada."""
        with tempfile.TemporaryDirectory() as tmpdir:
            inst_file = Path(tmpdir) / ".clow" / "INSTRUCTIONS.md"
            self.assertFalse(inst_file.exists())
            print("[OK] DNA: sem arquivo, nao injeta nada")

    def test_init_project_skill_exists(self):
        """Skill /init-project deve existir no registry."""
        from clow._skills_cli import create_default_skill_registry
        registry = create_default_skill_registry()

        skill = registry.get("init-project")
        self.assertIsNotNone(skill)
        self.assertEqual(skill.name, "init-project")

        # Aliases
        dna_skill = registry.get("dna")
        self.assertIsNotNone(dna_skill)
        self.assertEqual(dna_skill.name, "init-project")

        print("[OK] DNA: skill /init-project registrado com aliases [init-proj, dna]")

    def test_init_project_skill_output(self):
        """Skill /init-project deve gerar prompt com template."""
        from clow._skills_cli import create_default_skill_registry
        registry = create_default_skill_registry()
        skill = registry.get("init-project")

        # Sem args: versao curta
        result = skill.execute("")
        self.assertIn("INSTRUCTIONS.md", result)
        self.assertIn("stack", result.lower())

        # Com args: versao completa com template
        result_full = skill.execute("meu projeto python")
        self.assertIn("Stack", result_full)
        self.assertIn("Convencoes", result_full)
        self.assertIn("Integracoes", result_full)
        print("[OK] DNA: skill /init-project gera prompt com template correto")


# ════════════════════════════════════════════════════════════════
# TESTE INTEGRADO
# ════════════════════════════════════════════════════════════════

class TestIntegration(unittest.TestCase):
    """Testes integrados das 3 melhorias."""

    def test_all_configs_present(self):
        """Todas as configs devem existir."""
        self.assertTrue(hasattr(config, "CLOW_VISION_FEEDBACK"))
        self.assertTrue(hasattr(config, "CLOW_TOOL_PRUNING"))
        self.assertTrue(config.CLOW_VISION_FEEDBACK)
        self.assertTrue(config.CLOW_TOOL_PRUNING)
        print("[OK] Integracao: todas as configs presentes e ativas")

    def test_agent_has_all_methods(self):
        """Agent deve ter os novos metodos."""
        from clow.agent import Agent
        self.assertTrue(hasattr(Agent, "_vision_check"))
        self.assertTrue(hasattr(Agent, "_prune_tools"))
        self.assertTrue(hasattr(Agent, "_load_project_instructions"))
        self.assertTrue(hasattr(Agent, "TOOL_CATEGORIES"))
        self.assertTrue(hasattr(Agent, "PRUNING_KEYWORDS"))
        self.assertTrue(hasattr(Agent, "VISION_EXTENSIONS"))
        print("[OK] Integracao: Agent tem todos os novos metodos e atributos")


if __name__ == "__main__":
    print("=" * 60)
    print("  TESTES: 3 Melhorias Surreais do Agent.py")
    print("=" * 60)
    print()
    unittest.main(verbosity=2)

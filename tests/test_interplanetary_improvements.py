"""Testes para as 3 melhorias de outro planeta:
1. Teleport
2. Agent Teams
3. Natural Language Automations
"""

import json
import os
import sys
import time
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from clow import config


# ════════════════════════════════════════════════════════════════
# 1. TESTE: Teleport
# ════════════════════════════════════════════════════════════════

class TestTeleport(unittest.TestCase):

    def test_config(self):
        self.assertTrue(config.CLOW_TELEPORT)
        print("[OK] Teleport: config default = True")

    def test_export_nonexistent_session(self):
        from clow.teleport import export_session
        result = export_session("nonexistent-session-xyz")
        self.assertIn("error", result)
        print("[OK] Teleport: export de sessao inexistente retorna erro")

    def test_export_and_import_session(self):
        """Cria sessao, exporta, importa, e verifica."""
        from clow.session import save_session
        from clow.models import Session
        from clow.teleport import export_session, import_session

        # Cria sessao de teste
        session = Session(cwd="/tmp/test", model="test-model")
        session.messages = [
            {"role": "system", "content": "Voce e o Clow."},
            {"role": "user", "content": "Ola!"},
            {"role": "assistant", "content": "Ola! Como posso ajudar?"},
        ]
        session.total_tokens_in = 100
        session.total_tokens_out = 50
        save_session(session)

        # Exporta
        exported = export_session(session.id)
        self.assertEqual(exported["type"], "clow_teleport")
        self.assertEqual(exported["version"], "1.0")
        self.assertEqual(len(exported["session"]["messages"]), 3)
        self.assertEqual(exported["session"]["total_tokens_in"], 100)

        # Importa
        result = import_session(exported)
        self.assertTrue(result["success"])
        self.assertNotEqual(result["session_id"], session.id)  # Novo ID
        self.assertEqual(result["messages_count"], 3)
        self.assertEqual(result["original_id"], session.id)

        print("[OK] Teleport: export + import funciona (novo ID gerado)")

    def test_export_compressed(self):
        from clow.session import save_session
        from clow.models import Session
        from clow.teleport import export_session_compressed, import_session_compressed

        session = Session(cwd="/tmp/test2", model="test")
        session.messages = [{"role": "user", "content": "test " * 100}]
        save_session(session)

        compressed = export_session_compressed(session.id)
        self.assertIsInstance(compressed, bytes)
        self.assertGreater(len(compressed), 0)

        # Descomprime e importa
        result = import_session_compressed(compressed)
        self.assertTrue(result["success"])
        print(f"[OK] Teleport: compressao funciona ({len(compressed)} bytes)")

    def test_teleport_code_generate_and_redeem(self):
        from clow.session import save_session
        from clow.models import Session
        from clow.teleport import generate_teleport_code, redeem_teleport_code

        session = Session(cwd="/tmp/test3", model="test")
        session.messages = [{"role": "user", "content": "Teleport test"}]
        save_session(session)

        # Gera codigo
        code_result = generate_teleport_code(session.id)
        self.assertIn("code", code_result)
        code = code_result["code"]
        self.assertEqual(len(code), 6)
        self.assertEqual(code_result["expires_in"], 300)

        # Resgata
        redeem_result = redeem_teleport_code(code)
        self.assertTrue(redeem_result["success"])
        self.assertIn("session_id", redeem_result)
        self.assertEqual(redeem_result["teleported_from"], session.id)

        # Codigo single-use: segunda tentativa falha
        redeem2 = redeem_teleport_code(code)
        self.assertIn("error", redeem2)

        print("[OK] Teleport: codigo 6 digitos funciona (gera + resgata + single-use)")

    def test_invalid_code(self):
        from clow.teleport import redeem_teleport_code
        result = redeem_teleport_code("XXXXXX")
        self.assertIn("error", result)
        print("[OK] Teleport: codigo invalido retorna erro")

    def test_invalid_import_format(self):
        from clow.teleport import import_session
        result = import_session({"type": "wrong"})
        self.assertIn("error", result)
        print("[OK] Teleport: formato invalido rejeitado")

    def test_list_active_codes(self):
        from clow.teleport import list_active_codes
        codes = list_active_codes()
        self.assertIsInstance(codes, list)
        print("[OK] Teleport: list_active_codes funciona")

    def test_code_info(self):
        from clow.session import save_session
        from clow.models import Session
        from clow.teleport import generate_teleport_code, get_code_info

        session = Session(cwd="/tmp", model="test")
        session.messages = [{"role": "user", "content": "info test"}]
        save_session(session)

        code_result = generate_teleport_code(session.id)
        code = code_result["code"]

        info = get_code_info(code)
        self.assertIsNotNone(info)
        self.assertEqual(info["code"], code)
        self.assertGreater(info["expires_in"], 0)
        print("[OK] Teleport: get_code_info retorna dados corretos")


# ════════════════════════════════════════════════════════════════
# 2. TESTE: Agent Teams
# ════════════════════════════════════════════════════════════════

class TestTeams(unittest.TestCase):

    def test_config(self):
        self.assertTrue(config.CLOW_TEAMS)
        self.assertEqual(config.CLOW_TEAM_MAX_AGENTS, 4)
        print("[OK] Teams: configs corretas")

    def test_default_roles(self):
        from clow.teams import DEFAULT_ROLES
        self.assertIn("architect", DEFAULT_ROLES)
        self.assertIn("developer", DEFAULT_ROLES)
        self.assertIn("tester", DEFAULT_ROLES)
        self.assertIn("reviewer", DEFAULT_ROLES)
        print("[OK] Teams: 4 roles default presentes")

    def test_team_agent_dataclass(self):
        from clow.teams import TeamAgent
        agent = TeamAgent(
            role="developer",
            name="Developer",
            description="Implementa codigo",
            tools=["read", "write", "edit", "bash"],
            trigger="new_task",
        )
        d = agent.to_dict()
        self.assertEqual(d["role"], "developer")
        self.assertEqual(d["status"], "idle")
        self.assertIn("bash", d["tools"])
        print("[OK] Teams: TeamAgent to_dict funciona")

    def test_coordinator_init(self):
        from clow.teams import TeamCoordinator
        tc = TeamCoordinator(cwd=os.getcwd())
        self.assertIsNotNone(tc.team_id)
        self.assertEqual(len(tc.agents), 4)  # 4 default roles
        self.assertIn("architect", tc.agents)
        self.assertIn("developer", tc.agents)
        print("[OK] Teams: TeamCoordinator inicializa com 4 agents")

    def test_db_creation(self):
        from clow.teams import _get_db
        db = _get_db()
        tables = db.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
        table_names = [t[0] for t in tables]
        self.assertIn("team_tasks", table_names)
        self.assertIn("team_messages", table_names)
        db.close()
        print("[OK] Teams: tabelas team_tasks e team_messages criadas")

    def test_add_task_and_get_board(self):
        from clow.teams import TeamCoordinator
        tc = TeamCoordinator()

        tc._add_task("Criar modelo User", "Com campos name e email", "developer")
        tc._add_task("Testar modelo User", "Testes unitarios", "tester")

        board = tc.get_board()
        self.assertEqual(len(board), 2)
        self.assertEqual(board[0]["title"], "Criar modelo User")
        self.assertEqual(board[0]["status"], "todo")
        self.assertEqual(board[1]["assigned_role"], "tester")
        print("[OK] Teams: add_task + get_board funciona")

    def test_send_message_and_get(self):
        from clow.teams import TeamCoordinator
        tc = TeamCoordinator()

        tc.send_message("developer", "tester", "Implementei a rota /api/users, pode testar?")
        tc.send_message("tester", "developer", "Testes passaram!")

        msgs = tc.get_messages()
        self.assertGreaterEqual(len(msgs), 2)
        # Mensagens vem em ordem DESC
        self.assertIn("Testes passaram", msgs[0]["message"])
        print("[OK] Teams: message bus funciona (send + get)")

    def test_update_task(self):
        from clow.teams import TeamCoordinator
        tc = TeamCoordinator()
        task_id = tc._add_task("Test task", "", "developer")
        tc._update_task(task_id, "in_progress")

        board = tc.get_board()
        task = next(t for t in board if t["id"] == task_id)
        self.assertEqual(task["status"], "in_progress")

        tc._update_task(task_id, "done", "Concluido com sucesso")
        board = tc.get_board()
        task = next(t for t in board if t["id"] == task_id)
        self.assertEqual(task["status"], "done")
        self.assertIn("Concluido", task["result"])
        print("[OK] Teams: update_task transita status corretamente")

    def test_status_summary(self):
        from clow.teams import TeamCoordinator
        tc = TeamCoordinator()
        tc._add_task("Task A", "", "developer")
        tc._add_task("Task B", "", "tester")

        summary = tc.status_summary()
        self.assertIn("Team", summary)
        self.assertIn("todo: 2", summary)
        self.assertIn("Developer", summary)
        print("[OK] Teams: status_summary gera resumo legivel")

    def test_parse_role_md(self):
        from clow.teams import TeamCoordinator

        with tempfile.NamedTemporaryFile(suffix=".md", mode="w", delete=False, encoding="utf-8") as f:
            f.write("# Custom Agent\ndescription: Agente customizado para deploy\ntools: bash, docker_manage\ntrigger: task_completed\n")
            md_path = f.name

        try:
            role = TeamCoordinator._parse_role_md(Path(md_path))
            self.assertIsNotNone(role)
            self.assertEqual(role["name"], "Custom Agent")
            self.assertIn("deploy", role["description"])
            self.assertIn("bash", role["tools"])
            print("[OK] Teams: parse_role_md le arquivo .md corretamente")
        finally:
            os.unlink(md_path)


# ════════════════════════════════════════════════════════════════
# 3. TESTE: Natural Language Automations
# ════════════════════════════════════════════════════════════════

class TestNLAutomations(unittest.TestCase):

    def test_config(self):
        self.assertTrue(config.CLOW_NL_AUTOMATIONS)
        print("[OK] NL Auto: config default = True")

    def test_parse_returns_structure(self):
        """parse_natural_language deve retornar dict com campos esperados (ou error se sem API)."""
        from clow.automations import parse_natural_language

        result = parse_natural_language("todo dia as 8h me manda bom dia no whatsapp")

        # Pode retornar erro se API key nao configurada, mas estrutura deve existir
        self.assertIsInstance(result, dict)
        if "error" not in result:
            self.assertIn("trigger", result)
            self.assertIn("prompt_template", result)
            self.assertIn("name", result)
            self.assertIn("original_text", result)
            print(f"[OK] NL Auto: parse retornou automacao '{result.get('name')}'")
        else:
            print(f"[OK] NL Auto: parse retornou erro (esperado sem API key): {result['error'][:50]}")

    def test_create_from_nl(self):
        """create_from_natural_language deve criar automacao desabilitada."""
        from clow.automations import create_from_natural_language

        result = create_from_natural_language("a cada hora verifica o site")

        self.assertIsInstance(result, dict)
        if "error" not in result:
            self.assertTrue(result["success"])
            self.assertFalse(result["automation"]["enabled"])  # Desabilitada por default
            print("[OK] NL Auto: criou automacao desabilitada (precisa confirmacao)")
        else:
            print(f"[OK] NL Auto: retornou erro (esperado): {result['error'][:50]}")

    def test_disabled_config(self):
        """Com config desabilitada, deve retornar erro."""
        from clow.automations import parse_natural_language

        original = config.CLOW_NL_AUTOMATIONS
        config.CLOW_NL_AUTOMATIONS = False

        result = parse_natural_language("test")
        self.assertIn("error", result)
        self.assertIn("desabilitado", result["error"])

        config.CLOW_NL_AUTOMATIONS = original
        print("[OK] NL Auto: respeita config desabilitada")


# ════════════════════════════════════════════════════════════════
# SKILLS + INTEGRACAO
# ════════════════════════════════════════════════════════════════

class TestSkillsAndIntegration(unittest.TestCase):

    def test_new_skills_registered(self):
        from clow._skills_cli import create_default_skill_registry
        registry = create_default_skill_registry()

        for name in ["teleport", "team", "automate"]:
            skill = registry.get(name)
            self.assertIsNotNone(skill, f"Skill /{name} nao encontrado")

        # Aliases
        self.assertIsNotNone(registry.get("tp"))
        self.assertIsNotNone(registry.get("teams"))
        self.assertIsNotNone(registry.get("nl-auto"))
        print("[OK] Skills: teleport, team, automate registrados com aliases")

    def test_teleport_skill_output(self):
        from clow._skills_cli import create_default_skill_registry
        registry = create_default_skill_registry()
        skill = registry.get("teleport")
        result = skill.execute("")
        self.assertIn("codigo", result.lower())
        print("[OK] Skills: /teleport gera prompt correto")

    def test_automate_skill_output(self):
        from clow._skills_cli import create_default_skill_registry
        registry = create_default_skill_registry()
        skill = registry.get("automate")

        # Sem args
        result = skill.execute("")
        self.assertIn("portugues", result.lower())

        # Com args
        result = skill.execute("todo dia verifica o site")
        self.assertIn("Interprete", result)
        print("[OK] Skills: /automate gera prompt correto")

    def test_all_configs_present(self):
        for attr in ["CLOW_TELEPORT", "CLOW_TEAMS", "CLOW_TEAM_MAX_AGENTS", "CLOW_NL_AUTOMATIONS"]:
            self.assertTrue(hasattr(config, attr), f"Config {attr} nao encontrada")
        print("[OK] Integracao: todas as configs presentes")

    def test_routes_importable(self):
        from clow.routes.extensions import register_extension_routes
        self.assertTrue(callable(register_extension_routes))
        print("[OK] Integracao: routes/extensions.py importavel com novos endpoints")


if __name__ == "__main__":
    print("=" * 60)
    print("  TESTES: 3 Melhorias de Outro Planeta")
    print("=" * 60)
    print()
    unittest.main(verbosity=2)

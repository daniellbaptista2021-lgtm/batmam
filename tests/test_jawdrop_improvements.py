"""Testes para as 3 melhorias de cair o queixo:
1. Time Travel (Checkpoints)
2. Agent Swarm
3. Self-Learning
"""

import json
import os
import shutil
import sys
import tempfile
import time
import unittest
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from clow import config


# ════════════════════════════════════════════════════════════════
# 1. TESTE: Time Travel (Checkpoints)
# ════════════════════════════════════════════════════════════════

class TestTimeTravel(unittest.TestCase):
    """Verifica sistema de checkpoints para undo de mudancas."""

    def test_config_defaults(self):
        self.assertTrue(config.CLOW_CHECKPOINTS)
        self.assertEqual(config.CLOW_MAX_CHECKPOINTS, 50)
        print("[OK] TimeTravel: configs default corretas")

    def test_save_and_restore_checkpoint(self):
        """Salva checkpoint, modifica arquivo, restaura e verifica."""
        from clow.checkpoints import save_checkpoint, restore_checkpoint

        with tempfile.TemporaryDirectory() as tmpdir:
            # Cria arquivo original
            test_file = Path(tmpdir) / "test.py"
            test_file.write_text("# Original content\nx = 1\n", encoding="utf-8")

            # Salva checkpoint
            meta = save_checkpoint(
                session_id="test-session",
                turn_number=1,
                files_list=[str(test_file)],
                summary="test checkpoint",
            )

            self.assertIn("files", meta)
            self.assertEqual(len(meta["files"]), 1)
            self.assertEqual(meta["turn_number"], 1)

            # Modifica o arquivo
            test_file.write_text("# Modified content\nx = 999\ny = 2\n", encoding="utf-8")
            self.assertIn("999", test_file.read_text())

            # Restaura checkpoint
            result = restore_checkpoint("test-session", 1)
            self.assertTrue(result["success"])
            self.assertEqual(len(result["restored"]), 1)

            # Verifica que voltou ao original
            restored_content = test_file.read_text()
            self.assertIn("Original content", restored_content)
            self.assertIn("x = 1", restored_content)
            self.assertNotIn("999", restored_content)

            # Cleanup
            cp_dir = config.CLOW_HOME / "checkpoints" / "test-session"
            if cp_dir.exists():
                shutil.rmtree(cp_dir)

            print("[OK] TimeTravel: save + modify + restore funciona corretamente")

    def test_list_checkpoints(self):
        """Lista checkpoints de uma sessao."""
        from clow.checkpoints import save_checkpoint, list_checkpoints

        with tempfile.TemporaryDirectory() as tmpdir:
            test_file = Path(tmpdir) / "app.py"
            test_file.write_text("v1", encoding="utf-8")

            save_checkpoint("test-list", 1, [str(test_file)], "primeiro")
            test_file.write_text("v2", encoding="utf-8")
            save_checkpoint("test-list", 2, [str(test_file)], "segundo")
            test_file.write_text("v3", encoding="utf-8")
            save_checkpoint("test-list", 3, [str(test_file)], "terceiro")

            cps = list_checkpoints("test-list")
            self.assertEqual(len(cps), 3)
            self.assertEqual(cps[0]["turn_number"], 1)
            self.assertEqual(cps[2]["turn_number"], 3)

            # Cleanup
            cp_dir = config.CLOW_HOME / "checkpoints" / "test-list"
            if cp_dir.exists():
                shutil.rmtree(cp_dir)

            print("[OK] TimeTravel: list_checkpoints retorna 3 checkpoints ordenados")

    def test_diff_checkpoint(self):
        """Diff entre checkpoint e estado atual."""
        from clow.checkpoints import save_checkpoint, diff_checkpoint

        with tempfile.TemporaryDirectory() as tmpdir:
            test_file = Path(tmpdir) / "data.txt"
            test_file.write_text("linha1\nlinha2\n", encoding="utf-8")

            save_checkpoint("test-diff", 1, [str(test_file)])

            # Modifica
            test_file.write_text("linha1\nlinha2\nlinha3\nlinha4\n", encoding="utf-8")

            diffs = diff_checkpoint("test-diff", 1)
            self.assertEqual(len(diffs), 1)
            self.assertEqual(diffs[0]["status"], "modified")
            self.assertEqual(diffs[0]["backup_lines"], 2)
            self.assertEqual(diffs[0]["current_lines"], 4)

            # Cleanup
            cp_dir = config.CLOW_HOME / "checkpoints" / "test-diff"
            if cp_dir.exists():
                shutil.rmtree(cp_dir)

            print("[OK] TimeTravel: diff detecta modificacao (2 -> 4 linhas)")

    def test_is_write_tool_call(self):
        """Detecta tool calls de escrita."""
        from clow.checkpoints import is_write_tool_call

        self.assertTrue(is_write_tool_call("write", {"file_path": "x.py"}))
        self.assertTrue(is_write_tool_call("edit", {"file_path": "x.py"}))
        self.assertTrue(is_write_tool_call("bash", {"command": "rm -rf /tmp/test"}))
        self.assertTrue(is_write_tool_call("bash", {"command": "echo 'x' > file.txt"}))
        self.assertFalse(is_write_tool_call("read", {"file_path": "x.py"}))
        self.assertFalse(is_write_tool_call("bash", {"command": "ls -la"}))
        self.assertFalse(is_write_tool_call("grep", {"pattern": "test"}))
        print("[OK] TimeTravel: is_write_tool_call detecta corretamente")

    def test_extract_target_files(self):
        """Extrai arquivos alvo de tool calls."""
        from clow.checkpoints import extract_target_files

        tc_data = [
            {"name": "write", "arguments": json.dumps({"file_path": "/tmp/a.py"})},
            {"name": "edit", "arguments": json.dumps({"file_path": "/tmp/b.py"})},
            {"name": "read", "arguments": json.dumps({"file_path": "/tmp/c.py"})},
        ]
        files = extract_target_files(tc_data)
        self.assertEqual(len(files), 2)
        self.assertIn("/tmp/a.py", files)
        self.assertIn("/tmp/b.py", files)
        print("[OK] TimeTravel: extract_target_files pega write+edit, ignora read")

    def test_nonexistent_checkpoint_restore(self):
        """Restaurar checkpoint inexistente deve falhar graciosamente."""
        from clow.checkpoints import restore_checkpoint

        result = restore_checkpoint("nonexistent-session", 999)
        self.assertFalse(result["success"])
        self.assertIn("nao encontrado", result["error"])
        print("[OK] TimeTravel: checkpoint inexistente falha graciosamente")


# ════════════════════════════════════════════════════════════════
# 2. TESTE: Agent Swarm
# ════════════════════════════════════════════════════════════════

class TestAgentSwarm(unittest.TestCase):
    """Verifica sistema de swarm com agentes paralelos."""

    def test_config_defaults(self):
        self.assertTrue(config.CLOW_SWARM)
        self.assertEqual(config.CLOW_SWARM_MAX_AGENTS, 5)
        print("[OK] Swarm: configs default corretas")

    def test_swarm_agent_dataclass(self):
        """SwarmAgent deve ter todos os campos necessarios."""
        from clow.swarm import SwarmAgent

        agent = SwarmAgent(
            agent_id="test-1",
            subtask="Criar arquivo README.md",
        )

        self.assertEqual(agent.status, "pending")
        self.assertEqual(agent.agent_id, "test-1")
        self.assertEqual(agent.result, "")

        d = agent.to_dict()
        self.assertIn("agent_id", d)
        self.assertIn("subtask", d)
        self.assertIn("status", d)
        print("[OK] Swarm: SwarmAgent com todos os campos")

    def test_swarm_coordinator_init(self):
        """SwarmCoordinator deve inicializar corretamente."""
        from clow.swarm import SwarmCoordinator

        progress_msgs = []
        sc = SwarmCoordinator(
            cwd=os.getcwd(),
            on_progress=lambda msg: progress_msgs.append(msg),
        )

        self.assertEqual(sc.max_agents, 5)
        self.assertIsNotNone(sc.swarm_id)
        self.assertEqual(len(sc.agents), 0)
        print("[OK] Swarm: SwarmCoordinator inicializa corretamente")

    def test_swarm_agent_status_transitions(self):
        """Status do agente deve transitar corretamente."""
        from clow.swarm import SwarmAgent

        agent = SwarmAgent(agent_id="t1", subtask="test")
        self.assertEqual(agent.status, "pending")

        agent.status = "running"
        agent.started_at = time.time() - 1.5  # Simula 1.5s atras
        self.assertEqual(agent.status, "running")

        agent.status = "completed"
        agent.completed_at = time.time()
        agent.result = "done"
        d = agent.to_dict()
        self.assertEqual(d["status"], "completed")
        self.assertGreater(d["duration"], 0)
        print("[OK] Swarm: transicoes de status funcionam")

    def test_swarm_sequential_fallback(self):
        """Sem git worktree, deve rodar sequencial."""
        from clow.swarm import SwarmCoordinator

        with tempfile.TemporaryDirectory() as tmpdir:
            # Diretorio sem git
            sc = SwarmCoordinator(cwd=tmpdir)
            result = sc._run_sequential(
                "test task",
                ["subtask 1"],
            )

            # Pode falhar por falta de API key, mas a estrutura deve existir
            self.assertIn("swarm_id", result)
            self.assertIn("agents", result)
            self.assertEqual(result["mode"], "sequential")
            print("[OK] Swarm: fallback sequencial funciona")


# ════════════════════════════════════════════════════════════════
# 3. TESTE: Self-Learning
# ════════════════════════════════════════════════════════════════

class TestSelfLearning(unittest.TestCase):
    """Verifica sistema de self-learning a partir de logs."""

    def test_config_default(self):
        self.assertTrue(config.CLOW_SELF_LEARN)
        print("[OK] Learn: config default = True")

    def test_analyze_with_simulated_logs(self):
        """Analisa logs simulados e verifica extracoes."""
        from clow.learner import _extract_tool_sequences, _extract_recurring_errors, _extract_skill_usage

        # Simula entradas de log
        entries = []

        # Tool calls (cria sequencia repetitiva: read -> edit -> bash)
        for _ in range(10):
            entries.append({"action": "tool_exec", "tool_name": "read", "level": "info", "message": ""})
            entries.append({"action": "tool_exec", "tool_name": "edit", "level": "info", "message": ""})
            entries.append({"action": "tool_exec", "tool_name": "bash", "level": "info", "message": ""})

        # Erros recorrentes
        for _ in range(5):
            entries.append({
                "action": "turn_error", "level": "error",
                "message": "FileNotFoundError: No such file or directory: 'missing.py'"
            })
        for _ in range(3):
            entries.append({
                "action": "on_error", "level": "error",
                "message": "SyntaxError: invalid syntax in test.py"
            })

        # Skill usage
        for _ in range(7):
            entries.append({"action": "turn_start", "level": "info", "message": "/commit fix: bug corrigido"})
        for _ in range(4):
            entries.append({"action": "turn_start", "level": "info", "message": "/review app.py"})

        # Testa tool sequences
        seqs = _extract_tool_sequences(entries)
        self.assertGreater(len(seqs), 0)
        # Deve detectar read -> edit -> bash como trigram
        trigram_found = any(
            s["sequence"] == ["read", "edit", "bash"] for s in seqs
        )
        self.assertTrue(trigram_found)
        print(f"[OK] Learn: detectou {len(seqs)} sequencias de tools (incluindo read->edit->bash)")

        # Testa recurring errors
        errors = _extract_recurring_errors(entries)
        self.assertGreater(len(errors), 0)
        error_types = [e["error_type"] for e in errors]
        self.assertIn("file_not_found", error_types)
        self.assertIn("syntax_error", error_types)
        # Verifica sugestoes
        fnf = next(e for e in errors if e["error_type"] == "file_not_found")
        self.assertIn("glob", fnf["suggestion"].lower())
        print(f"[OK] Learn: detectou {len(errors)} tipos de erros recorrentes com sugestoes")

        # Testa skill usage
        skills = _extract_skill_usage(entries)
        self.assertGreater(len(skills), 0)
        skill_names = [s["name"] for s in skills]
        self.assertIn("commit", skill_names)
        self.assertIn("review", skill_names)
        commit_skill = next(s for s in skills if s["name"] == "commit")
        self.assertEqual(commit_skill["count"], 7)
        print(f"[OK] Learn: detectou {len(skills)} skills usados (/commit=7x, /review=4x)")

    def test_generate_learned_md(self):
        """Gera learned.md a partir de analise simulada."""
        from clow.learner import generate_learned_md

        analysis = {
            "total_entries": 100,
            "analyzed_at": "2026-04-04 12:00:00",
            "corrections": [
                "Nao faca commits sem rodar testes",
                "Prefiro mensagens de commit em portugues",
            ],
            "tool_sequences": [
                {"sequence": ["read", "edit", "bash"], "count": 15, "type": "trigram"},
                {"sequence": ["glob", "read"], "count": 20, "type": "bigram"},
            ],
            "recurring_errors": [
                {"error_type": "file_not_found", "count": 5, "sample": "", "suggestion": "Use glob antes"},
            ],
            "skill_usage": [
                {"name": "commit", "count": 12},
                {"name": "review", "count": 8},
            ],
        }

        content = generate_learned_md(analysis)

        self.assertIn("Self-Learning", content)
        self.assertIn("Regras Aprendidas", content)
        self.assertIn("Nao faca commits", content)
        self.assertIn("Sequencias de Tools", content)
        self.assertIn("read -> edit -> bash", content)
        self.assertIn("Erros Recorrentes", content)
        self.assertIn("file_not_found", content)
        self.assertIn("Skills Mais Usados", content)
        self.assertIn("/commit", content)

        # Verifica que o arquivo foi salvo
        from clow.learner import LEARNED_FILE
        self.assertTrue(LEARNED_FILE.exists())
        saved = LEARNED_FILE.read_text(encoding="utf-8")
        self.assertEqual(saved, content)

        print("[OK] Learn: learned.md gerado com todas as secoes corretas")

    def test_load_learned_context(self):
        """Deve carregar learned.md para injecao no system prompt."""
        from clow.learner import LEARNED_FILE, load_learned_context

        # Escreve conteudo de teste
        LEARNED_FILE.write_text("# Test learned\nRegra: sempre rode testes", encoding="utf-8")

        ctx = load_learned_context()
        self.assertIn("Test learned", ctx)
        self.assertIn("sempre rode testes", ctx)
        print("[OK] Learn: load_learned_context carrega conteudo")

    def test_error_classification(self):
        """Classifica tipos de erro corretamente."""
        from clow.learner import _classify_error

        self.assertEqual(_classify_error("FileNotFoundError: no such file"), "file_not_found")
        self.assertEqual(_classify_error("SyntaxError: invalid syntax"), "syntax_error")
        self.assertEqual(_classify_error("429 Too Many Requests"), "rate_limit")
        self.assertEqual(_classify_error("ImportError: No module named foo"), "import_error")
        self.assertEqual(_classify_error("TimeoutError: timed out"), "timeout")
        self.assertEqual(_classify_error("TypeError: expected str"), "type_error")
        self.assertEqual(_classify_error("tudo ok"), "")
        print("[OK] Learn: classificacao de erros funciona para todos os tipos")


# ════════════════════════════════════════════════════════════════
# TESTES INTEGRADOS + SKILLS
# ════════════════════════════════════════════════════════════════

class TestSkillsRegistration(unittest.TestCase):
    """Verifica que os novos skills estao registrados."""

    def test_all_new_skills_exist(self):
        from clow._skills_cli import create_default_skill_registry
        registry = create_default_skill_registry()

        for name in ["undo", "history", "swarm", "learn"]:
            skill = registry.get(name)
            self.assertIsNotNone(skill, f"Skill /{name} nao encontrado")

        # Aliases
        self.assertIsNotNone(registry.get("revert"))
        self.assertIsNotNone(registry.get("rollback"))
        self.assertIsNotNone(registry.get("timeline"))
        self.assertIsNotNone(registry.get("checkpoints"))
        self.assertIsNotNone(registry.get("self-learn"))

        print("[OK] Skills: todos os novos skills registrados com aliases")

    def test_undo_skill_output(self):
        from clow._skills_cli import create_default_skill_registry
        registry = create_default_skill_registry()
        skill = registry.get("undo")
        result = skill.execute("2")
        self.assertIn("2", result)
        self.assertIn("checkpoint", result.lower())
        print("[OK] Skills: /undo 2 gera prompt correto")

    def test_learn_report_skill(self):
        from clow._skills_cli import create_default_skill_registry
        registry = create_default_skill_registry()
        skill = registry.get("learn")
        result = skill.execute("report")
        self.assertIn("report", result.lower())
        print("[OK] Skills: /learn report gera prompt correto")


class TestAgentIntegration(unittest.TestCase):
    """Verifica que o agent.py importa e usa os novos modulos."""

    def test_imports(self):
        from clow.agent import save_checkpoint, extract_target_files, is_write_tool_call
        from clow.agent import load_learned_context
        self.assertTrue(callable(save_checkpoint))
        self.assertTrue(callable(load_learned_context))
        print("[OK] Integracao: agent.py importa checkpoints e learner")

    def test_agent_has_all_configs(self):
        self.assertTrue(hasattr(config, "CLOW_CHECKPOINTS"))
        self.assertTrue(hasattr(config, "CLOW_MAX_CHECKPOINTS"))
        self.assertTrue(hasattr(config, "CLOW_SWARM"))
        self.assertTrue(hasattr(config, "CLOW_SWARM_MAX_AGENTS"))
        self.assertTrue(hasattr(config, "CLOW_SELF_LEARN"))
        print("[OK] Integracao: todas as configs presentes")


if __name__ == "__main__":
    print("=" * 60)
    print("  TESTES: 3 Melhorias de Cair o Queixo")
    print("=" * 60)
    print()
    unittest.main(verbosity=2)

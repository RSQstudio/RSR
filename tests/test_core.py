"""Regression tests for routing core safety and supported entry points."""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from unittest.mock import patch

from src import agent_detector, cron, indexer, skill_router_cli, vault_manager
from src.matcher import SkillMatcher


class CoreSafetyTests(unittest.TestCase):
    def _skill(self, parent: Path, name: str) -> Path:
        skill = parent / name
        skill.mkdir(parents=True)
        (skill / "SKILL.md").write_text("---\nname: demo\ndescription: demo\n---\n", encoding="utf-8")
        return skill

    def test_activate_does_not_replace_real_active_skill(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            vault = root / "vault"
            active = root / "active"
            self._skill(vault / "_inbox", "demo")
            active_demo = self._skill(active, "demo")

            result = vault_manager.activate_skills(vault, active, ["demo"])

            self.assertEqual(result["activated"], [])
            self.assertEqual(result["conflicts"], ["demo"])
            self.assertTrue(active_demo.is_dir())
            self.assertFalse(active_demo.is_symlink())

    def test_activate_rejects_path_traversal_skill_name(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            vault = root / "vault"
            active = root / "active"
            self._skill(vault, "outside")

            result = vault_manager.activate_skills(vault, active, ["../outside"])

            self.assertEqual(result["activated"], [])
            self.assertEqual(result["invalid"], ["../outside"])
            self.assertFalse((root / "outside").is_symlink())

    def test_deactivate_preserves_unmanaged_symlink(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            active = root / "active"
            external = self._skill(root / "external", "demo")
            active.mkdir()
            (active / "demo").symlink_to(external, target_is_directory=True)

            result = vault_manager.deactivate_skills(active, ["demo"], vault_path=root / "vault")

            self.assertEqual(result["deactivated"], [])
            self.assertEqual(result["unmanaged"], ["demo"])
            self.assertTrue((active / "demo").is_symlink())

    def test_index_uses_directory_name_for_activation_identity(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            vault = Path(temp_dir) / "vault"
            skill = vault / "_inbox" / "vendor__network-ops"
            skill.mkdir(parents=True)
            (skill / "SKILL.md").write_text(
                "---\nname: network-operations\ndescription: diagnose network incidents\n---\n",
                encoding="utf-8",
            )

            result = SkillMatcher(indexer.build_index(vault), min_confidence=0.1).match("diagnose network")

            self.assertEqual(result[0][1], "vendor__network-ops")

    def test_reconcile_preserves_real_always_on_skill(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            active = root / "active"
            vault = root / "vault"
            self._skill(active, "caveman")

            result = vault_manager.reconcile(vault, active, [], always_keep=["caveman"])

            self.assertEqual(result["activated"], [])
            self.assertEqual(result["protected"], ["caveman"])
            self.assertEqual(vault_manager.get_active_skills(active), ["caveman"])

    def test_status_uses_vault_path_when_auto_resolved(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            active = root / "active"
            vault = root / "vault"
            self._skill(active, "caveman")
            self._skill(vault / "_inbox", "demo")
            config = {
                "paths": {"active": str(active), "vault": str(vault), "index_cache": str(root / "missing.json")},
                "always_keep": ["caveman"],
            }

            output = StringIO()
            with redirect_stdout(output):
                skill_router_cli.cmd_status(config)

            self.assertIn(f"Vault:     {vault} → 1 skills available", output.getvalue())
            self.assertIn("Active:    ", output.getvalue())
            self.assertIn("→ 1 skills loaded", output.getvalue())

    def test_sweep_creates_inbox_before_first_move(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            active = root / "active"
            vault = root / "vault"
            self._skill(active, "demo")
            config = {
                "paths": {
                    "active": str(active),
                    "vault": str(vault),
                    "index_cache": str(root / "cache" / "index.json"),
                }
            }

            result = cron.sweep(config)

            self.assertEqual(result["errors"], [])
            self.assertEqual(result["moved"], ["demo"])
            self.assertTrue((vault / "_inbox" / "demo" / "SKILL.md").is_file())

    def test_sweep_does_not_vault_always_on_real_skill(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            active = root / "active"
            vault = root / "vault"
            self._skill(active, "caveman")
            self._skill(active, "demo")
            (vault / "_inbox").mkdir(parents=True)
            config = {
                "paths": {
                    "active": str(active),
                    "vault": str(vault),
                    "index_cache": str(root / "cache" / "index.json"),
                },
                "always_keep": ["caveman"],
            }

            result = cron.sweep(config)

            self.assertEqual(result["errors"], [])
            self.assertEqual(result["moved"], ["demo"])
            self.assertTrue((active / "caveman" / "SKILL.md").is_file())
            self.assertTrue((vault / "_inbox" / "demo" / "SKILL.md").is_file())


class AgentDetectorTests(unittest.TestCase):
    def test_list_agents_does_not_retain_stale_global_state(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            hermes = agent_detector.AgentInfo("Hermes Agent", root / "hermes-skills", root / "hermes-config", "hermes", 100)
            claude_config = root / "claude-config"
            claude = agent_detector.AgentInfo("Claude Code", root / "claude-skills", claude_config, "claude", 95)
            claude_config.mkdir()

            with patch.object(agent_detector, "AGENTS", [hermes, claude]), patch.object(
                agent_detector, "_is_hermes_running", return_value=False
            ):
                first = {agent.name: agent for agent in agent_detector.list_agents()}
                self.assertTrue(first["Claude Code"].detected)
                claude_config.rmdir()
                second = {agent.name: agent for agent in agent_detector.list_agents()}
                self.assertFalse(second["Claude Code"].detected)


class CliEntrypointTests(unittest.TestCase):
    def test_load_config_merges_supported_defaults(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "config.json"
            path.write_text(json.dumps({"paths": {"vault": "/tmp/vault"}}), encoding="utf-8")

            config = skill_router_cli.load_config(path)

            self.assertEqual(config["paths"]["vault"], "/tmp/vault")
            self.assertEqual(config["matching"]["strategy"], "keyword")
            self.assertEqual(config["always_keep"], [])

    def test_module_cli_index_runs_from_package_imports(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            vault = root / "vault"
            skill = vault / "_inbox" / "demo"
            skill.mkdir(parents=True)
            (skill / "SKILL.md").write_text("---\nname: demo\ndescription: demo\n---\n", encoding="utf-8")
            cache = root / "cache" / "index.json"
            config = root / "config.yaml"
            config.write_text(json.dumps({
                "paths": {"vault": str(vault), "active": str(root / "active"), "index_cache": str(cache)},
                "matching": {"strategy": "keyword", "max_active_skills": 15, "min_confidence": 0.3},
                "always_keep": [],
            }), encoding="utf-8")

            commands = [
                [sys.executable, "-m", "src.skill_router_cli", "--config", str(config), "index"],
                [sys.executable, str(Path(__file__).parents[1] / "src" / "skill_router_cli.py"), "--config", str(config), "index"],
            ]
            for command in commands:
                result = subprocess.run(
                    command,
                    cwd=Path(__file__).parents[1],
                    capture_output=True,
                    text=True,
                    check=False,
                )
                self.assertEqual(result.returncode, 0, result.stderr)
            self.assertTrue(cache.is_file())


if __name__ == "__main__":
    unittest.main()

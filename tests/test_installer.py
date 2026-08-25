import os
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

import src.installer as installer
from src.installer import choose_router_skill_installation, install_router_skill


class InstallRouterSkillTests(unittest.TestCase):
    def test_copies_router_skill_to_active_directory(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "router-source.md"
            active = root / "active"
            source.write_text("router instructions\n", encoding="utf-8")

            destination = install_router_skill(source, active)

            self.assertEqual(destination, active / "rsq-skill-router" / "SKILL.md")
            self.assertEqual(destination.read_text(encoding="utf-8"), "router instructions\n")

    def test_preserves_existing_router_skill(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "router-source.md"
            active = root / "active"
            destination = active / "rsq-skill-router" / "SKILL.md"
            source.write_text("new router instructions\n", encoding="utf-8")
            destination.parent.mkdir(parents=True)
            destination.write_text("custom router instructions\n", encoding="utf-8")

            returned = install_router_skill(source, active)

            self.assertEqual(returned, destination)
            self.assertEqual(destination.read_text(encoding="utf-8"), "custom router instructions\n")

    def test_prompts_to_install_router_skill_by_default(self) -> None:
        with patch("src.installer._yesno", return_value=False) as ask:
            install = choose_router_skill_installation(non_interactive=False)

        self.assertFalse(install)
        ask.assert_called_once_with(
            "Install RSQ Skill Router as an always-on agent skill?",
            default=True,
        )

    def test_noninteractive_wizard_installs_router_skill(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            active = root / "active"
            vault = root / "vault"
            skill = active / "demo-skill"
            skill.mkdir(parents=True)
            (skill / "SKILL.md").write_text(
                "---\nname: demo-skill\ndescription: demo\n---\n",
                encoding="utf-8",
            )
            detected = type(
                "DetectedAgent",
                (),
                {"detected": True, "name": "Test Agent", "cli_name": "test", "skills_dir": active, "evidence": []},
            )()
            config = {
                "paths": {"index_cache": str(root / "cache" / "index.json")},
                "matching": {"strategy": "keyword", "max_active_skills": 15, "min_confidence": 0.3},
                "always_keep": [],
                "index": {},
                "logging": {},
            }

            with patch.dict(os.environ, {"HOME": str(root)}), patch.object(
                installer.agent_detector, "detect_agent", return_value=detected
            ), patch.object(installer.agent_detector, "resolve_vault_dir", return_value=vault), patch.object(
                installer.agent_detector, "AGENTS", []
            ):
                installer.run_install(config, non_interactive=True)

            destination = active / "rsq-skill-router" / "SKILL.md"
            self.assertTrue(destination.is_file())
            self.assertEqual(destination.read_text(encoding="utf-8"), (Path.cwd() / "SKILL.md").read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()

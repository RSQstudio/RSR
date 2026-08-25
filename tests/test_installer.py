import json
import os
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from src import installer
from src.installer import (
    choose_router_skill_installation,
    configured_always_keep,
    install_router_skill,
    recommended_always_keep,
)


class InstallRouterSkillTests(unittest.TestCase):
    def test_always_on_defaults_are_empty(self) -> None:
        selected, missing = recommended_always_keep(
            ["caveman", "anti-slop", "un-slop", "other-skill"],
            {
                "anti-slop": "Self-correction for all prose output before delivery.",
                "caveman": "Concise, low-overhead agent responses.",
            },
        )

        self.assertEqual(selected, [])
        self.assertEqual(missing, [])

    def test_configured_always_keep_uses_only_explicit_available_choices(self) -> None:
        selected = configured_always_keep(
            ["caveman", "anti-slop", "un-slop", "caveman-help"],
            ["caveman", "anti-slop", "un-slop", "missing-skill"],
        )

        self.assertEqual(selected, ["caveman", "anti-slop", "un-slop"])

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

    def test_router_skill_installation_is_opt_in(self) -> None:
        with patch("src.installer._yesno", return_value=False) as ask:
            install = choose_router_skill_installation(non_interactive=False)

        self.assertFalse(install)
        ask.assert_called_once_with(
            "Install RSQ Skill Router instructions in the active skills directory?",
            default=False,
        )

    def test_noninteractive_mode_skips_router_skill_installation(self) -> None:
        self.assertFalse(choose_router_skill_installation(non_interactive=True))

    def test_interactive_wizard_requires_explicit_always_on_and_router_choices(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            active = root / "active"
            vault = root / "vault"
            skills = {
                "caveman": "Concise, low-overhead agent responses.",
                "anti-slop": "Self-correction for all prose output before delivering.",
                "un-slop": "Analyze a domain and generate a reusable skill file.",
                "demo-skill": "demo",
            }
            for name, description in skills.items():
                skill = active / name
                skill.mkdir(parents=True)
                (skill / "SKILL.md").write_text(
                    f"---\nname: {name}\ndescription: {description}\n---\n",
                    encoding="utf-8",
                )
            detected = type(
                "DetectedAgent",
                (),
                {"detected": True, "name": "Test Agent", "cli_name": "test", "skills_dir": active, "evidence": []},
            )()
            config = {
                "paths": {"index_cache": str(root / "cache" / "index.json")},
                "matching": {},
                "always_keep": [],
                "index": {},
                "logging": {},
            }
            responses = ["", str(active), str(vault), "", "n", "y", "n"]

            with patch.dict(os.environ, {"HOME": str(root)}), patch.object(
                installer.agent_detector, "detect_agent", return_value=detected
            ), patch.object(installer.agent_detector, "AGENTS", []), patch(
                "builtins.input", side_effect=responses
            ):
                installer.run_install(config)

            self.assertFalse((active / "caveman" / "SKILL.md").exists())
            self.assertFalse((active / "anti-slop" / "SKILL.md").exists())
            self.assertFalse((active / "rsq-skill-router" / "SKILL.md").exists())
            self.assertTrue((vault / "_inbox" / "caveman" / "SKILL.md").is_file())
            self.assertTrue((vault / "_inbox" / "anti-slop" / "SKILL.md").is_file())
            self.assertTrue((vault / "_inbox" / "un-slop" / "SKILL.md").is_file())
            written_config = json.loads((root / ".config" / "skill-router" / "config.json").read_text(encoding="utf-8"))
            self.assertEqual(written_config["always_keep"], [])

    def test_noninteractive_wizard_does_not_install_optional_skills(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            active = root / "active"
            vault = root / "vault"
            for name in ("demo-skill", "caveman", "un-slop"):
                skill = active / name
                skill.mkdir(parents=True)
                description = "Self-correction for all prose output before delivering." if name == "un-slop" else "demo"
                (skill / "SKILL.md").write_text(
                    f"---\nname: {name}\ndescription: {description}\n---\n",
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
            self.assertFalse(destination.exists())
            self.assertFalse((active / "caveman" / "SKILL.md").exists())
            self.assertTrue((vault / "_inbox" / "caveman" / "SKILL.md").is_file())
            self.assertTrue((vault / "_inbox" / "un-slop" / "SKILL.md").is_file())
            self.assertTrue((vault / "_inbox" / "demo-skill" / "SKILL.md").is_file())
            config_path = root / ".config" / "skill-router" / "config.json"
            written_config = json.loads(config_path.read_text(encoding="utf-8"))
            self.assertEqual(config_path.stat().st_mode & 0o777, 0o600)
            self.assertEqual(written_config["always_keep"], [])


if __name__ == "__main__":
    unittest.main()

import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

import src.installer as installer
from src.installer import (
    choose_router_skill_installation,
    configured_always_keep,
    install_router_skill,
    recommended_always_keep,
)


class InstallRouterSkillTests(unittest.TestCase):
    def test_prefers_direct_anti_slop_over_meta_unslop(self) -> None:
        selected, missing = recommended_always_keep(
            ["caveman", "anti-slop", "un-slop", "other-skill"],
            {
                "un-slop": "Analyze a domain and generate a reusable skill file.",
                "anti-slop": "Self-correction for all prose output before delivering.",
            },
        )

        self.assertEqual(selected, ["caveman", "anti-slop"])
        self.assertEqual(missing, [])

    def test_prefers_anti_slop_when_both_skills_are_available(self) -> None:
        selected, missing = recommended_always_keep(
            ["caveman", "anti-slop", "un-slop"],
            {
                "un-slop": "Writing and editing output.",
                "anti-slop": "Writing and editing output.",
            },
        )

        self.assertEqual(selected, ["caveman", "anti-slop"])
        self.assertEqual(missing, [])

    def test_preselects_anti_slop_when_installed(self) -> None:
        selected, missing = recommended_always_keep(
            ["caveman", "anti-slop"],
            {"anti-slop": "Analyze a domain and generate a reusable skill file."},
        )

        self.assertEqual(selected, ["caveman", "anti-slop"])
        self.assertEqual(missing, [])

    def test_recommends_anti_slop_when_only_unslop_is_available(self) -> None:
        selected, missing = recommended_always_keep(
            ["caveman", "un-slop"],
            {"un-slop": "Analyze a domain and generate a reusable skill file."},
        )

        self.assertEqual(selected, ["caveman"])
        self.assertEqual(missing, ["anti-slop"])

    def test_uses_direct_anti_slop_when_un_slop_is_not_available(self) -> None:
        selected, missing = recommended_always_keep(
            ["caveman", "anti-slop"],
            {"anti-slop": "Self-correction for all prose output before delivering."},
        )

        self.assertEqual(selected, ["caveman", "anti-slop"])
        self.assertEqual(missing, [])

    def test_suggests_beneficial_skills_when_missing(self) -> None:
        selected, missing = recommended_always_keep(["other-skill"])

        self.assertEqual(selected, [])
        self.assertEqual(missing, ["caveman", "anti-slop"])

    def test_keeps_configured_extras_without_duplicate_anti_slop_skill(self) -> None:
        selected = configured_always_keep(
            ["caveman", "anti-slop", "un-slop", "caveman-help"],
            ["caveman", "un-slop", "anti-slop", "caveman-help"],
            {
                "un-slop": "Analyze a domain and generate a reusable skill file.",
                "anti-slop": "Self-correction for all prose output before delivering.",
            },
        )

        self.assertEqual(selected, ["caveman", "anti-slop", "caveman-help"])

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

    def test_interactive_wizard_keeps_direct_anti_slop_default(self) -> None:
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
            responses = ["", str(active), str(vault), "", "y", "y", "n"]

            with patch.dict(os.environ, {"HOME": str(root)}), patch.object(
                installer.agent_detector, "detect_agent", return_value=detected
            ), patch.object(installer.agent_detector, "AGENTS", []), patch(
                "builtins.input", side_effect=responses
            ):
                installer.run_install(config)

            self.assertTrue((active / "caveman" / "SKILL.md").is_file())
            self.assertTrue((active / "anti-slop" / "SKILL.md").is_file())
            self.assertTrue((vault / "_inbox" / "un-slop" / "SKILL.md").is_file())
            written_config = json.loads((root / ".config" / "skill-router" / "config.yaml").read_text(encoding="utf-8"))
            self.assertEqual(written_config["always_keep"], ["caveman", "anti-slop"])

    def test_noninteractive_wizard_installs_router_skill(self) -> None:
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
            self.assertTrue(destination.is_file())
            self.assertEqual(destination.read_text(encoding="utf-8"), (Path.cwd() / "SKILL.md").read_text(encoding="utf-8"))
            self.assertTrue((active / "caveman" / "SKILL.md").is_file())
            self.assertTrue((vault / "_inbox" / "un-slop" / "SKILL.md").is_file())
            self.assertTrue((vault / "_inbox" / "demo-skill" / "SKILL.md").is_file())
            written_config = json.loads((root / ".config" / "skill-router" / "config.yaml").read_text(encoding="utf-8"))
            self.assertEqual(written_config["always_keep"], ["caveman"])


if __name__ == "__main__":
    unittest.main()

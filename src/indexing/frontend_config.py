#!/usr/bin/env python3
"""
Frontend indexing configuration.
Loads defaults and optional overrides from .raggie/frontend_config.json.
"""

import json
from pathlib import Path
from typing import List, Optional


# Default configuration
DEFAULT_CONFIG = {
    "enabled_languages": ["html", "css", "javascript", "tsx"],
    "generated_dir_exclusions": ["dist", "build", "node_modules", ".next", ".nuxt", "out"],
    "parse_inline_scripts": True,
    "parse_inline_styles": True,
    "include_text_nodes": False,
    "css_module_resolution": True,
    "framework_detection_overrides": {},
    "generated_css_threshold": 100_000,
    "max_frontend_file_size": 500_000,
}


class FrontendConfig:
    """Configuration for frontend indexing behavior."""

    def __init__(self, config_dict: Optional[dict] = None):
        merged = dict(DEFAULT_CONFIG)
        if config_dict:
            merged.update(config_dict)
        self.enabled_languages: List[str] = merged["enabled_languages"]
        self.generated_dir_exclusions: List[str] = merged["generated_dir_exclusions"]
        self.parse_inline_scripts: bool = merged["parse_inline_scripts"]
        self.parse_inline_styles: bool = merged["parse_inline_styles"]
        self.include_text_nodes: bool = merged["include_text_nodes"]
        self.css_module_resolution: bool = merged["css_module_resolution"]
        self.framework_detection_overrides: dict = merged["framework_detection_overrides"]
        self.generated_css_threshold: int = merged["generated_css_threshold"]
        self.max_frontend_file_size: int = merged["max_frontend_file_size"]

    def is_language_enabled(self, language: str) -> bool:
        return language in self.enabled_languages

    def is_dir_excluded(self, dir_name: str) -> bool:
        return dir_name in self.generated_dir_exclusions


def load_frontend_config(root_dir) -> FrontendConfig:
    """Load frontend config from .raggie/frontend_config.json, or fall back to defaults.

    Args:
        root_dir: Project root directory path.

    Returns:
        FrontendConfig instance.
    """
    root_path = Path(root_dir)
    config_path = root_path / ".raggie" / "frontend_config.json"

    if config_path.exists():
        try:
            with open(config_path, "r", encoding="utf-8") as f:
                config_dict = json.load(f)
            return FrontendConfig(config_dict)
        except json.JSONDecodeError as e:
            print(f"Warning: Invalid JSON in {config_path}: {e}")
            print("Falling back to default frontend config.")
            return FrontendConfig()

    return FrontendConfig()

from __future__ import annotations

from pathlib import Path

import yaml


DEFAULT_CONFIG = Path("config/profit.yaml")


def load_config(path: str | Path = DEFAULT_CONFIG) -> dict:
    config_path = Path(path)
    if not config_path.exists():
        raise FileNotFoundError(
            f"收益配置不存在：{config_path}；请复制 config/profit.example.yaml "
            "为 config/profit.yaml 并填写 Cookie"
        )
    with config_path.open(encoding="utf-8") as handle:
        return yaml.safe_load(handle) or {}

from __future__ import annotations
import os
from .mock import MockEnvironment
from .epm_automate import LiveEpmConnector


def build_connector(env_cfg: dict, project_id: int, side: str, state_dir: str | None = None):
    kind = env_cfg.get("connector", "mock")
    if kind == "mock":
        return MockEnvironment(env_cfg, state_dir or os.environ.get("EPM_MOCK_STATE_DIR", ".mock_state"),
                               f"p{project_id}_{side}")
    if kind == "live":
        return LiveEpmConnector(env_cfg)
    raise ValueError(f"Unknown connector: {kind}")

"""Connector contract. The orchestrator only ever talks to this interface, so the
simulated environment and the live EPM Automate / REST connectors are interchangeable."""
from __future__ import annotations
from abc import ABC, abstractmethod
from dataclasses import dataclass


class ConnectorError(Exception):
    """kind: CONNECTIVITY | AUTH | TIMEOUT | ORACLE_ERROR | NOT_FOUND | UNSUPPORTED | UNKNOWN"""
    def __init__(self, kind: str, message: str):
        super().__init__(message)
        self.kind = kind


@dataclass
class CheckResult:
    name: str
    status: str  # PASS | FAIL
    detail: str = ""


class EpmConnector(ABC):
    @abstractmethod
    def check_connectivity(self) -> list[CheckResult]: ...

    @abstractmethod
    def get_inventory(self) -> dict:
        """Schema: product, version, application, application_exists, counts{}, control_totals{},
        integrations[{name,owner,type}], custom_items[{type,name}], extraction_errors[], capacity{}"""

    @abstractmethod
    def export_snapshot(self, name: str) -> dict: ...

    @abstractmethod
    def download_snapshot(self, name: str, dest_dir: str) -> str: ...

    @abstractmethod
    def upload_snapshot(self, path: str) -> dict: ...

    @abstractmethod
    def import_snapshot(self, name: str) -> dict: ...

    @abstractmethod
    def check_target_ready(self) -> dict: ...

"""Simulated Oracle EPM environment with fault injection.
Used for demos and automated testing when no real EPM instance is available."""
from __future__ import annotations
import copy, json, os, shutil
from pathlib import Path
from .base import EpmConnector, CheckResult, ConnectorError

PROFILES = {
    "clean": {
        "product": "Planning", "version": "25.09", "application": "FinPlan", "application_exists": True,
        "counts": {"dimensions": 12, "members": 48210, "smart_lists": 23, "substitution_variables": 31,
                   "forms": 85, "business_rules": 142, "dashboards": 18, "reports": 64, "menus": 9,
                   "users": 240, "groups": 28, "data_intersections": 15_400_000},
        "control_totals": {"Revenue": 1_250_000_000.50, "Expense": 980_000_000.25,
                           "Assets": 3_400_000_000.00, "Liabilities": 2_100_000_000.75},
        "integrations": [{"name": "ERP_GL_Load", "owner": "j.rao", "type": "data_integration"},
                         {"name": "HR_Headcount", "owner": "a.khan", "type": "data_integration"}],
        "custom_items": [], "extraction_errors": [], "capacity": {"max_intersections": 50_000_000},
    },
}
PROFILES["issues"] = copy.deepcopy(PROFILES["clean"])
PROFILES["issues"]["custom_items"] = [{"type": "custom_java_integration", "name": "LegacyERPBridge"},
                                      {"type": "legacy_report_format", "name": "OldBookPack"}]
PROFILES["issues"]["integrations"].append({"name": "Treasury_FileDrop", "owner": "", "type": "file_based_integration"})
PROFILES["issues"]["custom_items"].append({"type": "file_based_integration", "name": "Treasury_FileDrop"})


def empty_target(version="25.10"):
    t = copy.deepcopy(PROFILES["clean"])
    t["version"] = version
    t["counts"] = {k: 0 for k in t["counts"]}
    t["control_totals"] = {k: 0.0 for k in t["control_totals"]}
    t["integrations"], t["custom_items"] = [], []
    return t


class MockEnvironment(EpmConnector):
    """cfg keys: profile (clean|issues|empty_target), version, faults{}.
    faults: auth_fail, unreachable, fail_once:[op,...], fail_always:[op,...],
            drop_on_import:{counts_key: n}, skew_control_total:{name: delta}, target_version"""

    def __init__(self, cfg: dict, state_dir: str, key: str):
        self.cfg, self.key = cfg, key
        self.dir = Path(state_dir) / key
        self.dir.mkdir(parents=True, exist_ok=True)
        self.state_file = self.dir / "state.json"
        self.faults = cfg.get("faults", {})
        if self.state_file.exists():
            self.state = json.loads(self.state_file.read_text())
        else:
            prof = cfg.get("profile", "clean")
            self.state = empty_target(cfg.get("version", "25.10")) if prof == "empty_target" \
                else copy.deepcopy(PROFILES[prof])
            if "version" in cfg:
                self.state["version"] = cfg["version"]
            self._save()

    # -- helpers
    def _save(self): self.state_file.write_text(json.dumps(self.state, indent=1))

    def _fault_once_key(self, op): return self.dir / f".fired_{op}"

    def _maybe_fail(self, op: str):
        if self.faults.get("unreachable"):
            raise ConnectorError("CONNECTIVITY", "Simulated: host unreachable")
        if op in self.faults.get("fail_always", []):
            raise ConnectorError("ORACLE_ERROR", f"Simulated failure in {op}")
        if op in self.faults.get("fail_once", []):
            marker = self._fault_once_key(op)
            if not marker.exists():
                marker.write_text("1")
                raise ConnectorError("TIMEOUT", f"Simulated transient failure in {op}")

    # -- interface
    def check_connectivity(self):
        if self.faults.get("unreachable"):
            return [CheckResult("network", "FAIL", "host unreachable"), CheckResult("https", "FAIL", "n/a"),
                    CheckResult("authentication", "FAIL", "n/a"), CheckResult("epm_api", "FAIL", "n/a"),
                    CheckResult("epm_automate", "FAIL", "n/a")]
        auth_ok = not self.faults.get("auth_fail")
        return [CheckResult("network", "PASS"), CheckResult("https", "PASS"),
                CheckResult("authentication", "PASS" if auth_ok else "FAIL", "" if auth_ok else "invalid credentials"),
                CheckResult("epm_api", "PASS" if auth_ok else "FAIL"),
                CheckResult("epm_automate", "PASS" if auth_ok else "FAIL")]

    def get_inventory(self):
        self._maybe_fail("get_inventory")
        return copy.deepcopy(self.state)

    def export_snapshot(self, name):
        self._maybe_fail("export_snapshot")
        (self.dir / f"{name}.snapshot.json").write_text(json.dumps(self.state))
        return {"snapshot": name, "size_items": sum(self.state["counts"].values())}

    def download_snapshot(self, name, dest_dir):
        self._maybe_fail("download_snapshot")
        src = self.dir / f"{name}.snapshot.json"
        if not src.exists():
            raise ConnectorError("NOT_FOUND", f"Snapshot {name} not found")
        Path(dest_dir).mkdir(parents=True, exist_ok=True)
        dest = Path(dest_dir) / src.name
        shutil.copy(src, dest)
        return str(dest)

    def upload_snapshot(self, path):
        self._maybe_fail("upload_snapshot")
        shutil.copy(path, self.dir / Path(path).name)
        return {"uploaded": Path(path).name}

    def import_snapshot(self, name):
        self._maybe_fail("import_snapshot")
        f = self.dir / f"{name}.snapshot.json"
        if not f.exists():
            raise ConnectorError("NOT_FOUND", f"Snapshot {name} not uploaded")
        snap = json.loads(f.read_text())
        keep = {k: self.state[k] for k in ("version", "capacity")}  # target keeps its own version/capacity
        self.state = snap
        self.state.update(keep)
        for k, n in self.faults.get("drop_on_import", {}).items():
            self.state["counts"][k] = max(0, self.state["counts"].get(k, 0) - n)
        for k, d in self.faults.get("skew_control_total", {}).items():
            self.state["control_totals"][k] = self.state["control_totals"].get(k, 0) + d
        self._save()
        return {"imported": name}

    def check_target_ready(self):
        self._maybe_fail("check_target_ready")
        return {"application_exists": self.state.get("application_exists", False),
                "version": self.state["version"], "capacity": self.state.get("capacity", {})}

"""Live connector skeleton: EPM Automate for snapshot operations + REST for connectivity/inventory.

STATUS: written from Oracle's documented command set but NOT exercised against a real
Oracle EPM instance. Pilot it against a non-production environment and adjust before use.
Credentials: only references (password-file path, env var names) are accepted; raw passwords are not."""
from __future__ import annotations
import os, subprocess
from pathlib import Path
from typing import Callable
from .base import EpmConnector, CheckResult, ConnectorError

Runner = Callable[[list[str]], tuple[int, str, str]]


def default_runner(cmd: list[str]) -> tuple[int, str, str]:
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=3600)
    except subprocess.TimeoutExpired as e:
        raise ConnectorError("TIMEOUT", f"Command timed out: {cmd[1] if len(cmd) > 1 else cmd}") from e
    except FileNotFoundError as e:
        raise ConnectorError("UNSUPPORTED", f"EPM Automate not found: {cmd[0]}") from e
    return p.returncode, p.stdout, p.stderr


class EpmAutomateClient:
    def __init__(self, url: str, user: str, password_file: str, identity_domain: str = "",
                 binary: str | None = None, runner: Runner = default_runner):
        self.url, self.user, self.pwf, self.domain = url, user, password_file, identity_domain
        self.bin = binary or os.environ.get("EPMAUTOMATE_BIN", "epmautomate")
        self.run = runner

    def _cmd(self, *args: str) -> str:
        rc, out, err = self.run([self.bin, *args])
        if rc != 0:
            kind = "AUTH" if "login" in args[0].lower() else "ORACLE_ERROR"
            raise ConnectorError(kind, (err or out).strip()[:500] or f"{args[0]} failed (rc={rc})")
        return out

    def login(self):
        args = ["login", self.user, self.pwf, self.url]
        if self.domain:
            args.append(self.domain)
        return self._cmd(*args)

    def logout(self): return self._cmd("logout")
    def export_snapshot(self, name): return self._cmd("exportsnapshot", name)
    def download_file(self, name): return self._cmd("downloadfile", name)
    def upload_file(self, path): return self._cmd("uploadfile", path)
    def import_snapshot(self, name): return self._cmd("importsnapshot", name)


class LiveEpmConnector(EpmConnector):
    """cfg: url, user, password_file_env, identity_domain, rest_base (optional)."""

    def __init__(self, cfg: dict, runner: Runner = default_runner, http=None):
        pwf = os.environ.get(cfg.get("password_file_env", ""), "")
        self.cfg = cfg
        self.client = EpmAutomateClient(cfg["url"], cfg["user"], pwf, cfg.get("identity_domain", ""), runner=runner)
        self.http = http  # injectable requests-like session for tests

    def _session(self):
        if self.http is None:
            import requests
            self.http = requests.Session()
        return self.http

    def check_connectivity(self):
        res = []
        try:
            r = self._session().get(self.cfg["url"], timeout=15)
            res += [CheckResult("network", "PASS"), CheckResult("https", "PASS" if self.cfg["url"].startswith("https") else "FAIL")]
        except Exception as e:  # noqa: BLE001
            return [CheckResult("network", "FAIL", str(e)[:200])]
        try:
            self.client.login()
            res += [CheckResult("authentication", "PASS"), CheckResult("epm_automate", "PASS")]
            self.client.logout()
        except ConnectorError as e:
            res += [CheckResult("authentication", "FAIL", str(e)), CheckResult("epm_automate", "FAIL", str(e))]
        res.append(CheckResult("epm_api", "FAIL", "REST API probe not implemented in MVP skeleton"))
        return res

    def get_inventory(self):
        raise ConnectorError("UNSUPPORTED", "Live inventory (REST) is not implemented in the MVP skeleton; "
                             "use the simulated connector or extend LiveEpmConnector.get_inventory().")

    def _with_login(self, fn, *a):
        self.client.login()
        try:
            return fn(*a)
        finally:
            try: self.client.logout()
            except ConnectorError: pass

    def export_snapshot(self, name):
        return {"snapshot": name, "output": self._with_login(self.client.export_snapshot, name)}

    def download_snapshot(self, name, dest_dir):
        Path(dest_dir).mkdir(parents=True, exist_ok=True)
        self._with_login(self.client.download_file, name)  # EPM Automate downloads into cwd
        return str(Path(name))

    def upload_snapshot(self, path):
        return {"uploaded": path, "output": self._with_login(self.client.upload_file, path)}

    def import_snapshot(self, name):
        return {"imported": name, "output": self._with_login(self.client.import_snapshot, name)}

    def check_target_ready(self):
        self._with_login(lambda: None)
        return {"application_exists": True, "version": "unknown", "capacity": {}}

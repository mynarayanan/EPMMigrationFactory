"""Live connector: verifies the EPM Automate command sequence with a fake runner (NOT a real Oracle test)."""
import pytest
from connectors.epm_automate import LiveEpmConnector
from connectors.base import ConnectorError


def make(rc_for=None):
    calls = []
    def runner(cmd):
        calls.append(cmd[1:])
        bad = rc_for and cmd[1] == rc_for
        return (1, "", "boom") if bad else (0, "ok", "")
    c = LiveEpmConnector({"url": "https://x.oraclecloud.com", "user": "svc", "password_file_env": "PWF", "identity_domain": "idm"}, runner=runner)
    return c, calls


def test_export_sequence(monkeypatch):
    monkeypatch.setenv("PWF", "/secure/x.epw")
    c, calls = make()
    c.export_snapshot("Artifact Snapshot")
    assert calls == [["login", "svc", "/secure/x.epw", "https://x.oraclecloud.com", "idm"],
                     ["exportsnapshot", "Artifact Snapshot"], ["logout"]]


def test_import_failure_is_classified_and_logs_out(monkeypatch):
    monkeypatch.setenv("PWF", "/p")
    c, calls = make(rc_for="importsnapshot")
    with pytest.raises(ConnectorError) as e: c.import_snapshot("S")
    assert e.value.kind == "ORACLE_ERROR" and calls[-1] == ["logout"]


def test_login_failure_is_auth(monkeypatch):
    monkeypatch.setenv("PWF", "/p")
    c, _ = make(rc_for="login")
    with pytest.raises(ConnectorError) as e: c.upload_snapshot("f.zip")
    assert e.value.kind == "AUTH"


def test_inventory_not_faked():
    c, _ = make()
    with pytest.raises(ConnectorError) as e: c.get_inventory()
    assert e.value.kind == "UNSUPPORTED"

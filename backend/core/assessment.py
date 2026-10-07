"""Compatibility rules + weighted readiness scoring. Pure functions over inventory + config."""
from __future__ import annotations

BLOCKING = {"unsupported", "redesign_required"}


def _vt(v: str):
    try: return tuple(int(x) for x in str(v).split("."))
    except ValueError: return (0,)


def evaluate_compatibility(src_inv: dict, compat_cfg: dict) -> list[dict]:
    rules = {r["artifact"]: r for r in compat_cfg["rules"]}
    default = compat_cfg["default"]
    out = []
    for art, n in src_inv.get("counts", {}).items():
        if n:
            r = rules.get(art, {**default, "artifact": art})
            out.append({"artifact": art, "detail": f"{n} item(s)", "status": r["status"],
                        "action": r["action"], "group": r["group"]})
    for item in src_inv.get("custom_items", []):
        r = rules.get(item["type"], {**default, "artifact": item["type"]})
        out.append({"artifact": item["type"], "detail": item["name"], "status": r["status"],
                    "action": r["action"], "group": r["group"]})
    return out


def _blocking(findings, group, remediation_ok):
    bad = [f for f in findings if f["group"] == group and f["status"] in BLOCKING]
    if not bad: return True, "no blocking findings"
    if remediation_ok: return True, f"{len(bad)} blocking finding(s) covered by approved remediation plan"
    return False, f"{len(bad)} blocking finding(s): " + ", ".join(f["detail"] for f in bad)


def build_checks(ctx: dict) -> dict:
    """ctx: src, tgt (inventories or None), connectivity (dict side->{name:status}), findings, settings."""
    src, tgt, st = ctx["src"], ctx["tgt"], ctx["settings"]
    findings, rem = ctx["findings"], bool(st.get("remediation_approved"))
    conn = ctx["connectivity"]
    cap = (tgt or {}).get("capacity", {}).get("max_intersections", 0)
    vol = (src or {}).get("counts", {}).get("data_intersections", 0)
    ints = (src or {}).get("integrations", [])
    conn_ok = all(conn.get(s) and all(v == "PASS" for v in conn[s].values()) for s in ("source", "target"))
    return {
        "source_inventory_collected": (src is not None, "inventory present" if src else "run source inventory"),
        "source_inventory_complete": (bool(src) and not src.get("extraction_errors"), "no extraction errors"
                                      if src and not src.get("extraction_errors") else "extraction errors or missing"),
        "target_inventory_collected": (tgt is not None, "inventory present" if tgt else "run target inventory"),
        "target_application_exists": (bool(tgt and tgt.get("application_exists")), "target application exists"),
        "target_version_compatible": (bool(src and tgt and _vt(tgt["version"]) >= _vt(src["version"])),
                                      f"source {src and src['version']} -> target {tgt and tgt['version']}"),
        "connectivity_all_pass": (conn_ok, "all checks PASS on both sides" if conn_ok else "failed/missing connectivity checks"),
        "security_inventory_present": (bool(src and src["counts"].get("users") and src["counts"].get("groups")), "users and groups inventoried"),
        "privileged_access_reviewed": (bool(st.get("privileged_access_reviewed")), "attestation flag"),
        "dimensions_present": (bool(src and src["counts"].get("dimensions")), "dimensions inventoried"),
        "no_blocking_metadata": _blocking(findings, "metadata", rem),
        "data_scope_defined": (bool(st.get("data_scope")), f"scope: {st.get('data_scope') or 'undefined'}"),
        "data_volume_within_capacity": (bool(tgt) and vol <= cap, f"{vol:,} intersections vs capacity {cap:,}"),
        "integrations_have_owners": (all(i.get("owner") for i in ints), "all integrations owned" if all(i.get("owner") for i in ints)
                                     else "unowned: " + ", ".join(i["name"] for i in ints if not i.get("owner"))),
        "no_blocking_integrations": _blocking(findings, "integration", rem),
        "no_blocking_artifacts": _blocking(findings, "artifact", rem),
        "capacity_headroom": (bool(tgt) and cap > 0 and vol <= 0.8 * cap, "volume <= 80% of capacity"),
        "backup_plan_defined": (bool(st.get("backup_plan")), "attestation"),
        "rollback_defined": (bool(st.get("rollback_plan")), "rollback plan text present" if st.get("rollback_plan") else "missing"),
        "cutover_window_defined": (bool(st.get("cutover_window")), st.get("cutover_window") or "missing"),
    }


def score_readiness(ctx: dict, cfg: dict) -> dict:
    checks = build_checks(ctx)
    cats, total_w, acc, blockers = {}, 0, 0.0, []
    for cname, c in cfg["categories"].items():
        results = []
        for chk in c["checks"]:
            ok, detail = checks[chk["id"]]
            results.append({"id": chk["id"], "passed": bool(ok), "critical": bool(chk.get("critical")), "detail": detail})
            if not ok and chk.get("critical"):
                blockers.append(f"{cname}: {chk['id']} - {detail}")
        pct = 100.0 * sum(r["passed"] for r in results) / len(results)
        cats[cname] = {"weight": c["weight"], "score": round(pct, 1), "checks": results}
        total_w += c["weight"]; acc += c["weight"] * pct
    score = round(acc / total_w, 1)
    th = cfg["thresholds"]
    status = "GREEN" if score >= th["green"] else "AMBER" if score >= th["amber"] else "RED"
    if blockers:
        status = "RED"  # any failed critical gate blocks migration regardless of weighted score
    return {"score": score, "status": status, "categories": cats, "blockers": blockers}

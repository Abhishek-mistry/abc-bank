"""Failure simulator (§8.10). Config lives in system_settings (read every call) so all workers agree."""
import random

import db
from errors import ApiError, SimulatedNetworkError, SimulatedResponseDropped

MODES = ("NONE", "BEFORE_DEBIT", "AFTER_DEBIT", "BEFORE_COMMIT", "DROP_RESPONSE", "RANDOM")
_POINTS = MODES[1:5]  # what RANDOM picks from


def get_global():
    rows = db.fetch_all("SELECT setting_key, setting_value FROM system_settings "
                        "WHERE setting_key IN ('sim_mode', 'sim_probability')")
    s = {r["setting_key"]: r["setting_value"] for r in rows}
    return {"mode": s.get("sim_mode", "NONE"), "probability": s.get("sim_probability", "0.30")}


def set_global(mode, probability=None):
    if mode not in MODES:
        raise ApiError("VALIDATION_ERROR", "mode: invalid",
                       {"fields": {"mode": "must be one of " + ", ".join(MODES)}})
    updates = {"sim_mode": mode}
    if probability is not None:
        try:
            p = float(probability)
        except (TypeError, ValueError):
            p = -1.0
        if not 0.0 <= p <= 1.0:  # also rejects NaN
            raise ApiError("VALIDATION_ERROR", "probability: must be between 0 and 1",
                           {"fields": {"probability": "must be between 0 and 1"}})
        updates["sim_probability"] = f"{p:.2f}"
    with db.transaction() as cur:
        for k, v in updates.items():
            cur.execute("INSERT INTO system_settings (setting_key, setting_value) VALUES (%s, %s) "
                        "ON DUPLICATE KEY UPDATE setting_value = VALUES(setting_value)", (k, v))
    return get_global()


def resolve_mode(override=None):
    """Effective concrete mode. Call ONCE per request and pass the result as `override` to every hook
    (RANDOM would otherwise be re-rolled per hook). A concrete override never touches the DB."""
    if override is not None and override != "RANDOM":
        return override
    g = get_global()
    mode = g["mode"] if override is None else override
    if mode == "RANDOM":
        return random.choice(_POINTS) if random.random() < float(g["probability"]) else "NONE"
    return mode


def maybe_fail(point, override=None):
    if resolve_mode(override) == point:
        raise SimulatedNetworkError(point)


def maybe_drop_response(override=None):
    if resolve_mode(override) == "DROP_RESPONSE":
        raise SimulatedResponseDropped()

"""
Pulse (the CRM demo page) is built from the same governed definitions as the
assistant and Tableau. These checks fail the build if its data drifts from the
semantic layer or picks up anything patient-shaped.
"""
import json
import re

from semantic_layer import MetricQuery


def _load(path):
    html = open(path).read()
    raw = re.search(r'<script id="pulse-data" type="application/json">(.*?)</script>', html, re.S).group(1)
    return json.loads(raw.replace("<\\/", "</"))


def test_pulse_export_matches_semantic_layer(layer, vp, tmp_path):
    import export_for_pulse

    out = export_for_pulse.main(db_path=layer.db_path, out_path=str(tmp_path / "index.html"))
    data = _load(out)
    df, _, _ = layer.run(MetricQuery(model="accounts", measures=["account_count", "cases_last_90d", "accounts_with_data_gaps"]), vp)
    assert len(data["accounts"]) == df["account_count"].iloc[0]
    assert sum(a["l90"] for a in data["accounts"]) == df["cases_last_90d"].iloc[0]
    assert sum(a["signal"] == "Data gap" for a in data["accounts"]) == df["accounts_with_data_gaps"].iloc[0]
    assert data["governed"]["overall"]["cases_last_90d"] == df["cases_last_90d"].iloc[0]


def test_pulse_export_has_no_patient_fields(layer, tmp_path):
    import export_for_pulse

    data = _load(export_for_pulse.main(db_path=layer.db_path, out_path=str(tmp_path / "index.html")))
    keys = set(data["accounts"][0]) | {k for e in data["events"] for k in e}
    for banned in ("patient", "dob", "birth", "mrn", "ssn"):
        assert not any(banned in k.lower() for k in keys), f"Pulse data has a field containing '{banned}'"


def test_pulse_keeps_the_riverbend_story(layer, tmp_path):
    import export_for_pulse

    data = _load(export_for_pulse.main(db_path=layer.db_path, out_path=str(tmp_path / "index.html")))
    dinner = next(e for e in data["events"] if e["name"] == "Riverbend Plaque Dinner Program")
    assert len(dinner["attendees"]) == 12
    assert sum(a[4] == "Went quiet" for a in dinner["attendees"]) == 4

"""
Build the Pulse CRM demo page from the same governed definitions the assistant
and Tableau use.

Each dataset is the base SQL of a model in semantic_model.yaml, run as of the
snapshot date, so "Data gap", "Recently quiet", and utilization mean the same
thing in Pulse as everywhere else. The headline totals are also pulled through
the semantic layer itself and embedded, so the page can check its own
arithmetic against the governed numbers.

The only data Pulse adds is demo CRM records: activity (calls, visits, emails)
standing in for Salesforce Activity, and transfers of value (meals, travel,
speaker fees) tied to program attendance. Both are synthetic, seeded, and kept
separate from the warehouse models.

Input:  pulse/template.html
Output: pulse/index.html  (one self-contained file, data embedded)

Run:  python3 export_for_pulse.py
"""
from __future__ import annotations

import json
import os
import re
from datetime import date

import duckdb
import numpy as np

from semantic_layer import DEFAULT_DB_PATH, MetricQuery, SemanticLayer, User

HERE = os.path.dirname(os.path.abspath(__file__))
TEMPLATE = os.path.join(HERE, "pulse", "template.html")
OUT_PATH = os.path.join(HERE, "pulse", "index.html")
PLACEHOLDER = "/*__PULSE_DATA__*/"
SEED = 11

# Fill these in once the dashboard and repository are public; the page shows
# "Link to add" until then.
LINKS = {"tableau": "", "github": "https://github.com/rutuja07091/account-intelligence"}

# Real project files shown on the "How it's built" page.
CODE_FILES = {
    "cube": "cube/model/cases.yml",
    "workflow": ".github/workflows/tests.yml",
}


def _iso(v):
    if v is None or (isinstance(v, float) and np.isnan(v)):
        return None
    try:
        import pandas as pd
        if pd.isna(v):
            return None
    except (TypeError, ValueError):
        pass
    return str(v)[:10]


def _int(v):
    try:
        import pandas as pd
        if pd.isna(v):
            return None
    except (TypeError, ValueError):
        pass
    return int(v)


def _excerpt(path: str, start: str, stop: str | None = None) -> str:
    text = open(os.path.join(HERE, path)).read()
    i = text.index(start)
    j = text.index(stop, i + len(start)) if stop else len(text)
    return text[i:j].rstrip() + "\n"


def governed_totals(layer: SemanticLayer) -> dict:
    """Headline numbers straight from the semantic layer, overall and by territory."""
    vp = User("Regional VP")
    measures = ["account_count", "cases_last_90d", "cases_prior_90d", "case_change_pct",
                "verified_case_change_pct", "est_utilization", "accounts_with_data_gaps"]
    overall, _, _ = layer.run(MetricQuery(model="accounts", measures=measures), vp)
    by_terr, _, _ = layer.run(MetricQuery(model="accounts", measures=measures, dimensions=["territory"],
                                          order_by="territory", order_direction="asc"), vp)
    clean = lambda row: {k: (None if row[k] is None else float(row[k])) for k in measures}
    return {"overall": clean(overall.iloc[0]),
            "by_territory": {r["territory"]: clean(r) for _, r in by_terr.iterrows()}}


def demo_activity(accounts, physicians, as_of: date) -> dict:
    """Seeded CRM touches per account, standing in for Salesforce Activity records."""
    rng = np.random.default_rng(SEED)
    top_doc = (physicians.sort_values(["lifetime_cases", "physician_id"], ascending=[False, True], kind="stable")
               .groupby("account_id").physician_name.first().to_dict())
    notes = {
        "Call": "Reviewed recent ordering with {doc}.",
        "Site visit": "Met the imaging director and CT lead tech.",
        "Email": "Sent the quarterly utilization summary.",
        "QBR": "Reviewed case volume, turnaround time, and Plaque adoption.",
    }
    out = {}
    for a in accounts.itertuples():
        slow = a.account_signal == "Review decline"
        last = int(rng.integers(32, 70)) if slow else int(rng.integers(2, 40))
        days = sorted({last, last + int(rng.integers(10, 30)), last + int(rng.integers(35, 80))})
        kinds = ["Email" if slow else "Call", "Site visit", "QBR"]
        out[a.account_id] = [{"d": d, "type": k, "note": notes[k].format(doc=top_doc.get(a.account_id, "the lead cardiologist"))}
                             for d, k in zip(days, kinds)]
    return out


def demo_payments(events: list) -> list:
    """Seeded transfers of value tied to program attendance, standing in for the
    spend records that would sit on Salesforce Events. Rows: physician name,
    account id, date, category, amount in USD, program name."""
    rng = np.random.default_rng(SEED + 1)
    rows = []
    for e in events:
        for i, (name, _spec, _before, _after, _status) in enumerate(e["attendees"]):
            row = lambda kind, amount: rows.append([name, e["account"], e["date"], kind, int(amount), e["name"]])
            if e["type"] == "Dinner program":
                row("Meal", rng.integers(55, 111))
                if i == 0:  # attendees are sorted by prior volume; the first is the program speaker
                    row("Speaker fee", rng.integers(15, 26) * 100)
            elif e["type"] == "VIP visit":
                if rng.random() < 0.3:
                    row("Travel and lodging", rng.integers(350, 901))
                row("Meal", rng.integers(30, 71))
            else:
                row("Food and beverage", rng.integers(18, 41))
    return rows


def build_data(db_path: str = DEFAULT_DB_PATH) -> dict:
    layer = SemanticLayer(db_path=db_path)
    as_of = date.fromisoformat(str(layer.as_of))
    con = duckdb.connect(db_path, read_only=True)
    try:
        run = lambda name: con.execute(layer.models[name]["sql"].replace("{as_of}", f"DATE '{as_of}'")).df()
        # DuckDB does not promise row order, and the seeded demo records below are
        # drawn row by row, so sort everything to keep the output identical run to run.
        accounts = run("accounts").sort_values("account_id", kind="stable").reset_index(drop=True)
        physicians = run("physician_activity").sort_values("physician_id", kind="stable").reset_index(drop=True)
        monthly = run("account_monthly").sort_values(["account_id", "month_start"], kind="stable").reset_index(drop=True)
        events = run("event_followup").sort_values(["event_date", "event_name", "physician_name"], kind="stable").reset_index(drop=True)
    finally:
        con.close()

    months = sorted({str(m)[:7] for m in monthly.month_start})
    idx = {m: i for i, m in enumerate(months)}
    series = {}
    for r in monthly.itertuples():
        s = series.setdefault(r.account_id, {"m": [None] * len(months), "pm": [None] * len(months)})
        i = idx[str(r.month_start)[:7]]
        s["m"][i], s["pm"][i] = int(r.cases), int(r.plaque_cases)

    acct_ids = dict(zip(accounts.account_name, accounts.account_id))
    data = {
        "meta": {
            "as_of": str(as_of),
            "months": months,
            "territories": [{"name": n, "tam": t} for n, t in layer.territories()],
            "source": "semantic_model.yaml",
        },
        "accounts": [{
            "id": a.account_id, "name": a.account_name, "type": a.account_type,
            "terr": a.territory, "tam": a.tam_name,
            "act": _iso(a.activation_date), "plaqueAct": _iso(a.plaque_activation_date),
            "recent": a.activation_cohort == "Activated in last 12 months",
            "ccta90": int(a.est_ccta_90d), "l90": int(a.cases_last_90d), "p90": int(a.cases_prior_90d),
            "actPhys": int(a.active_physicians), "gapDays": int(a.missing_days_180d),
            "signal": a.account_signal,
            **series.get(a.account_id, {"m": [None] * len(months), "pm": [None] * len(months)}),
        } for a in accounts.itertuples()],
        # Compact rows: id, name, specialty, account_id, last_case_date, last 90, prior 90, lifetime, days since, status
        "physicians": [[p.physician_id, p.physician_name, p.specialty, p.account_id, _iso(p.last_case_date),
                        int(p.cases_last_90d), int(p.cases_prior_90d), int(p.lifetime_cases),
                        _int(p.days_since_last_case), p.activity_status] for p in physicians.itertuples()],
        "events": [],
        "activity": demo_activity(accounts, physicians, as_of),
        "governed": governed_totals(layer),
        "links": LINKS,
        "code": {
            **{k: open(os.path.join(HERE, path)).read() for k, path in CODE_FILES.items()},
            "signal": _excerpt("semantic_model.yaml", "      gaps AS (", "    dimensions:"),
            "test": _excerpt("tests/test_semantic_layer.py", "def test_feed_gap_is_labeled_not_called_a_decline"),
        },
    }
    for (name, etype, edate, acct), g in events.groupby(["event_name", "event_type", "event_date", "account_name"], sort=False):
        data["events"].append({
            "name": name, "type": etype, "date": _iso(edate), "account": acct_ids[acct],
            "attendees": [[r.physician_name, r.specialty, int(r.cases_before), int(r.cases_after), r.followup_status]
                          for r in g.sort_values(["cases_before", "physician_name"], ascending=[False, True], kind="stable").itertuples()],
        })
    data["events"].sort(key=lambda e: (e["date"], e["name"]), reverse=True)
    data["payments"] = demo_payments(data["events"])
    return data


def main(db_path: str = DEFAULT_DB_PATH, out_path: str = OUT_PATH, template: str = TEMPLATE) -> str:
    data = build_data(db_path)
    payload = json.dumps(data, separators=(",", ":")).replace("</", "<\\/")
    html = open(template).read()
    if PLACEHOLDER not in html:
        raise ValueError(f"{template} has no {PLACEHOLDER} placeholder")
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, "w") as f:
        f.write(html.replace(PLACEHOLDER, payload))
    print(f"Wrote {out_path}  ({len(data['accounts'])} accounts, {len(data['physicians'])} physicians, "
          f"{len(data['events'])} events, {len(payload) / 1024:.0f} KB of data)")
    return out_path


if __name__ == "__main__":
    main()

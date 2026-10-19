"""
Checks that run on every pull request (see .github/workflows/tests.yml).
If a metric definition breaks, or security stops working, the build fails
before anyone sees a wrong number.
"""
import duckdb
import pytest

from semantic_layer import MetricQuery, QueryError


def q(**kwargs):
    return MetricQuery.from_dict(kwargs)


# ---------- the semantic layer rejects anything it does not define ----------

def test_unknown_measure_is_rejected(layer, vp):
    with pytest.raises(QueryError):
        layer.compile(q(model="cases", measures=["revenue"]), vp)


def test_unknown_dimension_is_rejected(layer, vp):
    with pytest.raises(QueryError):
        layer.compile(q(model="cases", measures=["case_count"], dimensions=["patient_name"]), vp)


def test_unknown_operator_is_rejected(layer, vp):
    bad = [{"dimension": "account_name", "operator": "; DROP", "values": ["x"]}]
    with pytest.raises(QueryError):
        layer.compile(q(model="cases", measures=["case_count"], filters=bad), vp)


def test_filter_values_are_parameters_not_sql(layer, vp):
    evil = [{"dimension": "account_name", "operator": "equals", "values": ["x'; DROP TABLE cases; --"]}]
    df, _, _ = layer.run(q(model="cases", measures=["case_count"], filters=evil), vp)
    assert df["case_count"].iloc[0] == 0
    con = duckdb.connect(layer.db_path, read_only=True)
    assert con.execute("SELECT count(*) FROM cases").fetchone()[0] > 0
    con.close()


# ---------- row level security ----------

def test_tam_only_sees_their_territory(layer, ohio_tam):
    df, _, _ = layer.run(q(model="accounts", measures=["account_count"], dimensions=["territory"]), ohio_tam)
    assert set(df["territory"]) == {"Ohio Valley"}


def test_tam_cannot_filter_into_another_territory(layer, ohio_tam):
    other = [{"dimension": "territory", "operator": "equals", "values": ["Gulf Coast"]}]
    df, _, _ = layer.run(q(model="accounts", measures=["account_count"], filters=other), ohio_tam)
    assert df["account_count"].iloc[0] == 0


def test_every_model_can_be_secured(layer):
    for name, model in layer.models.items():
        assert "territory" in model["dimensions"], f"{name} has no territory dimension for security"


# ---------- no patient data, by construction ----------

def test_no_patient_columns_anywhere(layer):
    con = duckdb.connect(layer.db_path, read_only=True)
    cols = [r[0].lower() for r in con.execute("SELECT column_name FROM information_schema.columns").fetchall()]
    con.close()
    for banned in ("patient", "dob", "birth", "mrn", "ssn"):
        assert not any(banned in c for c in cols), f"found a column containing '{banned}'"


# ---------- the metrics tell the planted story ----------

def test_dinner_program_has_four_quiet_physicians(layer, vp):
    f = [{"dimension": "event_name", "operator": "contains", "values": ["Riverbend Plaque Dinner"]}]
    df, _, _ = layer.run(q(model="event_followup", measures=["attendees", "went_quiet"], filters=f), vp)
    assert df["attendees"].iloc[0] == 12
    assert df["went_quiet"].iloc[0] == 4


def test_every_measure_runs(layer, vp):
    for name, model in layer.models.items():
        df, _, _ = layer.run(q(model=name, measures=list(model["measures"])), vp)
        assert len(df) == 1


# ---------- Tableau extracts come from the same definitions ----------

def test_tableau_export_matches_semantic_layer(layer, vp, tmp_path):
    import pandas as pd
    import export_for_tableau

    paths = export_for_tableau.main(db_path=layer.db_path, out_dir=str(tmp_path))
    assert len(paths) == len(layer.models)
    accounts = pd.read_csv(tmp_path / "accounts.csv")
    df, _, _ = layer.run(q(model="accounts", measures=["account_count", "cases_last_90d"]), vp)
    assert len(accounts) == df["account_count"].iloc[0]
    assert accounts["cases_last_90d"].sum() == df["cases_last_90d"].iloc[0]


def test_monthly_model_includes_zero_months(layer, vp):
    f = [{"dimension": "activation_cohort", "operator": "equals", "values": ["Activated in last 12 months"]}]
    df, _, _ = layer.run(q(model="account_monthly", measures=["account_count"], dimensions=["months_since_activation"],
                           filters=f, order_by="months_since_activation", order_direction="asc"), vp)
    assert df["months_since_activation"].iloc[0] == 0
    assert df["account_count"].iloc[0] >= df["account_count"].iloc[-1]


# ---------- missing data is not a decline ----------

def test_feed_gap_is_labeled_not_called_a_decline(layer, vp):
    """Summit Heart Institute drops 32% in raw cases, but 14 of its feed days never arrived.
    Raw counts cannot tell that apart from a real decline; the data coverage fields can."""
    gap_filter = [{"dimension": "data_status", "operator": "equals", "values": ["Data gap"]}]
    df, _, _ = layer.run(q(model="accounts", measures=["case_change_pct"],
                           dimensions=["account_name", "account_signal"], filters=gap_filter), vp)
    assert len(df) == 3
    assert set(df["account_signal"]) == {"Data gap"}                 # never labeled Review decline
    assert (df["case_change_pct"] <= -30).any()                       # at least one would have been flagged on raw counts

    # Real declines still get flagged: accounts with complete coverage and a 30%+ drop.
    review = [{"dimension": "account_signal", "operator": "equals", "values": ["Review decline"]}]
    flagged, _, _ = layer.run(q(model="accounts", measures=["account_count"], filters=review), vp)
    assert flagged["account_count"].iloc[0] >= 5

    # The verified change leaves gap accounts out, so it differs from the raw change.
    both, _, _ = layer.run(q(model="accounts", measures=["case_change_pct", "verified_case_change_pct",
                                                         "accounts_with_data_gaps"]), vp)
    assert both["accounts_with_data_gaps"].iloc[0] == 3
    assert both["verified_case_change_pct"].iloc[0] != both["case_change_pct"].iloc[0]

"""
Generate a synthetic commercial dataset that looks like a CCTA analysis business.

Everything here is invented. There are no patients anywhere in this data:
a case row records which account and which ordering physician sent it, the
product, and the completion date. Nothing else.

Tables written to data/crm_demo.duckdb:
    territories        one row per sales territory and its TAM
    accounts           one row per hospital, clinic, or imaging office
    physicians         one row per referring or ordering clinician
    cases              one row per completed analysis
    events             dinner programs, VIP visits, road shows
    event_attendance   which physicians attended which event
    feed_gaps          days an account's case feed did not arrive (one row per account per day)

Planted story for the demo:
    Riverbend Heart Institute (Ohio Valley) ran a Plaque dinner program on
    2026-06-18 with 12 attendees. Four of them were regular orderers before
    the dinner and placed zero cases in the 90 days after. The other eight
    ordered more. The rest of the data is random but realistic.

    Second planted story: three Great Lakes hospitals have days where their case
    feed never arrived (21, 14, and 7 days in the last 90). Cases on those days
    are missing, so the accounts look like they are declining. A real decline and
    a feed gap look the same in the raw counts; the feed_gaps table is how the
    semantic model tells them apart.

Run:  python3 generate_data.py
"""
from __future__ import annotations

import os
from datetime import date, timedelta
from typing import Dict, List

import duckdb
import numpy as np
import pandas as pd

SEED = 7
DATA_START = date(2025, 4, 1)
AS_OF = date(2026, 9, 30)
DEFAULT_DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "crm_demo.duckdb")

TERRITORIES = [
    ("T01", "Ohio Valley", "Jordan Pike"),
    ("T02", "Northern California", "Maya Ellison"),
    ("T03", "Gulf Coast", "Chris Navarro"),
    ("T04", "Mid-Atlantic", "Priya Sethi"),
    ("T05", "Great Lakes", "Dana Whitlock"),
    ("T06", "Southwest", "Leo Marsh"),
]

PLACES = [
    "Lakeshore", "Summit", "Cedar Valley", "Harbor", "Pinecrest", "Northgate",
    "Meadowbrook", "Stonebridge", "Westfield", "Clearwater", "Fairhaven", "Oakmont",
    "Silver Creek", "Brookside", "Highland", "Maple Ridge", "Bayview", "Granite Peak",
    "Willow Park", "Ashford", "Kingsbury", "Elm Hollow", "Redwood Point", "Juniper Hill",
    "Copper Falls", "Lindenwood", "Shoreline", "Prairie View", "Hawthorne", "Bridgewater",
]
SUFFIX_BY_TYPE = {
    "Hospital": ["Medical Center", "Regional Hospital", "Heart Institute"],
    "Clinic": ["Cardiology Associates", "Heart and Vascular", "Cardiology Group"],
    "Office": ["Imaging Center", "Diagnostic Imaging"],
}
FIRST = ["Alex", "Sam", "Taylor", "Morgan", "Riley", "Avery", "Jamie", "Casey", "Drew", "Quinn",
         "Rowan", "Elena", "Marcus", "Nadia", "Omar", "Grace", "Victor", "Hana", "Isaac", "Lena",
         "Ravi", "Sofia", "Theo", "Wen", "Yusuf", "Zara", "Beatriz", "Colin", "Dev", "Farah"]
LAST = ["Abbott", "Brennan", "Castillo", "Delgado", "Eriksen", "Fong", "Garrison", "Hale", "Iyer",
        "Jensen", "Kowalski", "Larsen", "Moreau", "Nakamura", "Okafor", "Petrov", "Quintero",
        "Ramsey", "Sandoval", "Tanaka", "Underwood", "Vance", "Whitaker", "Xu", "Yates", "Zeller",
        "Adeyemi", "Bishop", "Carver", "Dunleavy", "Ellery", "Fairbanks", "Gupta", "Holloway"]
SPECIALTIES = ["Cardiology", "Primary Care", "Nurse Practitioner", "Radiology", "Interventional Cardiology"]
SPECIALTY_P = [0.50, 0.20, 0.15, 0.10, 0.05]


def month_starts(start: date, end: date) -> List[date]:
    months, d = [], date(start.year, start.month, 1)
    while d <= end:
        months.append(d)
        d = date(d.year + (d.month == 12), d.month % 12 + 1, 1)
    return months


def random_day_in_month(rng: np.random.Generator, m: date) -> date:
    nxt = date(m.year + (m.month == 12), m.month % 12 + 1, 1)
    return m + timedelta(days=int(rng.integers(0, (nxt - m).days)))


def build_accounts(rng: np.random.Generator) -> pd.DataFrame:
    rows, used = [], set()
    # The account the demo is built around comes first so its id is stable.
    rows.append(dict(account_id="A0001", account_name="Riverbend Heart Institute", account_type="Hospital",
                     territory_id="T01", activation_date=date(2022, 3, 14),
                     plaque_activation_date=date(2025, 11, 3), est_monthly_ccta=180))
    used.add("Riverbend Heart Institute")
    n = 1
    while len(rows) < 180:
        acct_type = rng.choice(["Hospital", "Clinic", "Office"], p=[0.55, 0.30, 0.15])
        name = f"{rng.choice(PLACES)} {rng.choice(SUFFIX_BY_TYPE[acct_type])}"
        if name in used:
            continue
        used.add(name)
        n += 1
        recent = rng.random() < 0.12
        if recent:
            activation = AS_OF - timedelta(days=int(rng.integers(60, 365)))
        else:
            activation = date(2021, 1, 1) + timedelta(days=int(rng.integers(0, 1460)))
        plaque = None
        if rng.random() < 0.45:
            plaque = max(activation, date(2025, 6, 1)) + timedelta(days=int(rng.integers(0, 420)))
            if plaque > AS_OF:
                plaque = None
        ccta = {"Hospital": rng.integers(60, 250), "Clinic": rng.integers(20, 90), "Office": rng.integers(10, 40)}[acct_type]
        rows.append(dict(account_id=f"A{n:04d}", account_name=name, account_type=acct_type,
                         territory_id=TERRITORIES[int(rng.integers(0, len(TERRITORIES)))][0],
                         activation_date=activation, plaque_activation_date=plaque,
                         est_monthly_ccta=int(ccta)))
    return pd.DataFrame(rows)


def build_physicians(rng: np.random.Generator, accounts: pd.DataFrame) -> pd.DataFrame:
    rows, n = [], 0
    for acct in accounts.itertuples():
        count = int(rng.integers(14, 22)) if acct.account_id == "A0001" else int(rng.integers(5, 20))
        for _ in range(count):
            n += 1
            specialty = rng.choice(SPECIALTIES, p=SPECIALTY_P)
            first, last = rng.choice(FIRST), rng.choice(LAST)
            name = f"{first} {last}, NP" if specialty == "Nurse Practitioner" else f"Dr. {first} {last}"
            rows.append(dict(physician_id=f"P{n:05d}", physician_name=name, specialty=specialty,
                             account_id=acct.account_id))
    return pd.DataFrame(rows)


def build_cases(rng: np.random.Generator, accounts: pd.DataFrame, physicians: pd.DataFrame,
                stop_dates: Dict[str, date], boosts: Dict[str, date]) -> pd.DataFrame:
    months = month_starts(DATA_START, AS_OF)
    rows = []
    case_n = 0
    for acct in accounts.itertuples():
        docs = physicians[physicians.account_id == acct.account_id]
        # Each clinician gets an ordering weight; about 20% never order.
        weights = rng.lognormal(0, 0.9, len(docs)) * (rng.random(len(docs)) > 0.2)
        if acct.account_id == "A0001":
            weights = np.where(weights == 0, 0.6, weights)  # everyone at the demo account orders a bit
        if weights.sum() == 0:
            continue
        share = weights / weights.sum()
        utilization = rng.uniform(0.15, 0.55)
        declining = rng.random() < 0.10
        for m in months:
            if m < date(acct.activation_date.year, acct.activation_date.month, 1):
                continue
            months_live = (m.year - acct.activation_date.year) * 12 + m.month - acct.activation_date.month
            ramp = 1 - np.exp(-(months_live + 1) / 4)
            seasonal = 0.85 if m.month in (7, 8, 12) else 1.0
            trend = (0.96 ** max(0, (m.year - 2026) * 12 + m.month)) if declining and m.year == 2026 else 1.0
            account_rate = acct.est_monthly_ccta * utilization * ramp * seasonal * trend
            for doc, s in zip(docs.itertuples(), share):
                rate = account_rate * s
                if doc.physician_id in boosts and m >= date(boosts[doc.physician_id].year, boosts[doc.physician_id].month, 1):
                    rate *= 1.6
                for _ in range(int(rng.poisson(rate))):
                    day = random_day_in_month(rng, m)
                    if day > AS_OF:
                        continue
                    stop = stop_dates.get(doc.physician_id)
                    if stop is not None and day >= stop:
                        continue
                    plaque_on = acct.plaque_activation_date is not None and not pd.isna(acct.plaque_activation_date) \
                        and day >= acct.plaque_activation_date
                    product = "Plaque" if plaque_on and rng.random() < 0.32 else "FFRCT"
                    case_n += 1
                    rows.append(dict(case_id=f"C{case_n:07d}", account_id=acct.account_id,
                                     ordering_physician_id=doc.physician_id, product=product,
                                     completed_date=day))
    return pd.DataFrame(rows)


# Planted feed gaps: (start date, number of missing days), applied to the three
# largest Great Lakes hospitals that went live before 2026. All fall inside the
# last 90 days before AS_OF, so they distort the latest 90-day comparison.
FEED_GAPS = [(date(2026, 7, 27), 21), (date(2026, 8, 24), 14), (date(2026, 9, 8), 7)]


def plant_feed_gaps(accounts: pd.DataFrame, cases: pd.DataFrame):
    """Remove cases on the gap days and return (cases, feed_gaps table)."""
    pool = accounts[(accounts.territory_id == "T05") & (accounts.account_type == "Hospital")
                    & (accounts.activation_date <= date(2025, 12, 31))]
    pool = pool.sort_values(["est_monthly_ccta", "account_id"], ascending=[False, True])
    rows = []
    for acct, (start, days) in zip(pool.account_id.tolist(), FEED_GAPS):
        for k in range(days):
            rows.append(dict(account_id=acct, gap_date=start + timedelta(days=k)))
    gaps = pd.DataFrame(rows)
    missing = set(zip(gaps.account_id, gaps.gap_date))
    keep = [(a, d) not in missing for a, d in zip(cases.account_id, cases.completed_date)]
    return cases[keep].reset_index(drop=True), gaps


def build_events(rng: np.random.Generator, accounts: pd.DataFrame, physicians: pd.DataFrame,
                 demo_attendees: List[str]):
    events = [dict(event_id="E001", event_name="Riverbend Plaque Dinner Program", event_type="Dinner program",
                   event_date=date(2026, 6, 18), account_id="A0001")]
    attendance = [dict(event_id="E001", physician_id=p) for p in demo_attendees]
    kinds = ["Dinner program", "VIP visit", "CT pathway road show"]
    others = accounts[accounts.account_id != "A0001"].sample(40, random_state=SEED)
    for i, acct in enumerate(others.itertuples(), start=2):
        kind = kinds[int(rng.integers(0, 3))]
        when = date(2025, 9, 1) + timedelta(days=int(rng.integers(0, 330)))
        label = {"Dinner program": "Dinner Program", "VIP visit": "VIP Visit",
                 "CT pathway road show": "Road Show"}[kind]
        place = acct.account_name.split(" ")[0]
        events.append(dict(event_id=f"E{i:03d}", event_name=f"{place} {label} {when:%b %Y}",
                           event_type=kind, event_date=when, account_id=acct.account_id))
        docs = physicians[physicians.account_id == acct.account_id].physician_id.tolist()
        k = min(len(docs), int(rng.integers(3, 10)))
        for p in rng.choice(docs, size=k, replace=False):
            attendance.append(dict(event_id=f"E{i:03d}", physician_id=str(p)))
    return pd.DataFrame(events), pd.DataFrame(attendance)


def main(db_path: str = DEFAULT_DB_PATH) -> str:
    rng = np.random.default_rng(SEED)
    accounts = build_accounts(rng)
    physicians = build_physicians(rng, accounts)

    # Plant the demo story at Riverbend: 12 attendees, 4 go quiet, 8 ramp up.
    riverbend = physicians[physicians.account_id == "A0001"].physician_id.tolist()
    attendees = riverbend[:12]
    dinner = date(2026, 6, 18)
    stop_dates = {p: dinner for p in attendees[:4]}
    boosts = {p: dinner for p in attendees[4:]}

    # Background churn: about 6% of everyone else stops ordering sometime in 2026.
    others = [p for p in physicians.physician_id if p not in attendees]
    for p in rng.choice(others, size=int(len(others) * 0.06), replace=False):
        stop_dates[str(p)] = date(2026, 1, 1) + timedelta(days=int(rng.integers(0, 240)))

    cases = build_cases(rng, accounts, physicians, stop_dates, boosts)
    cases, feed_gaps = plant_feed_gaps(accounts, cases)
    events, attendance = build_events(rng, accounts, physicians, attendees)
    territories = pd.DataFrame(TERRITORIES, columns=["territory_id", "territory_name", "tam_name"])

    os.makedirs(os.path.dirname(db_path), exist_ok=True)
    if os.path.exists(db_path):
        os.remove(db_path)
    con = duckdb.connect(db_path)
    for name, df in [("territories", territories), ("accounts", accounts), ("physicians", physicians),
                     ("cases", cases), ("events", events), ("event_attendance", attendance),
                     ("feed_gaps", feed_gaps)]:
        con.register("df_view", df)
        con.execute(f"CREATE TABLE {name} AS SELECT * FROM df_view")
        con.unregister("df_view")
    # Dates come through pandas as objects; make sure they are real DATE columns.
    for table, col in [("accounts", "activation_date"), ("accounts", "plaque_activation_date"),
                       ("cases", "completed_date"), ("events", "event_date"),
                       ("feed_gaps", "gap_date")]:
        con.execute(f"ALTER TABLE {table} ALTER COLUMN {col} TYPE DATE")
    con.close()

    print(f"Wrote {db_path}")
    print(f"  {len(accounts)} accounts, {len(physicians)} physicians, {len(cases)} cases, "
          f"{len(events)} events, {len(attendance)} attendance rows, {len(feed_gaps)} feed gap days")
    return db_path


if __name__ == "__main__":
    main()

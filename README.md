# Account Intelligence

A commercial analytics layer that sits beside Salesforce: governed metric definitions, a Tableau dashboard built on them, the same definitions written in Cube, and an AI assistant that can only answer through them.

All data is synthetic. There is no patient data anywhere in the system, by design and enforced by a test.

## What is in this project

| Piece | Where | Role in the pitch |
| --- | --- | --- |
| Synthetic commercial data | `generate_data.py` | 180 accounts, 2,119 physicians, 84,732 cases, 41 field events, and 42 missing feed days, with two planted stories: Riverbend's dinner program and three accounts with data gaps |
| Governed metric definitions | `semantic_model.yaml` | Five models; every number anywhere in the project comes from here, including a data coverage check that separates missing data from real declines |
| Semantic layer | `semantic_layer.py` | Validates requests, applies territory security, compiles safe SQL |
| Tableau extracts and build guide | `export_for_tableau.py`, `tableau/` | The main live demo: utilization, physicians gone quiet, ramp curves |
| Cube version of the model | `cube/` | The production-shaped semantic model, run locally and checked against the Python layer |
| AI assistant | `agent.py`, `app.py` | The closing "where this goes next" demo |
| Pulse CRM | `export_for_pulse.py`, `pulse/` | The CRM demo: next actions for TAMs, a leadership and compliance dashboard, and live checks against the semantic layer. Live at https://rutuja07091.github.io/account-intelligence/pulse/ |
| Tests and CI | `tests/`, `.github/workflows/tests.yml` | 19 checks on every pull request |

## The idea in one paragraph

The risky way to build a stakeholder chatbot is to let a language model write SQL against raw tables. It invents joins and returns confident wrong numbers. Here the model never writes SQL. It can only request measures and dimensions that are defined once in `semantic_model.yaml`, reviewed through pull requests. The semantic layer validates the request, applies the user's territory automatically, and compiles parameterized SQL. In production that layer is Cube on Redshift; `cube/` shows the equivalent definitions.

```
question ──► Claude ──► query_metrics(model, measures, dimensions, filters)
                              │
                              ▼
                semantic_layer.py: validate names, add territory filter, compile SQL
                              │
                              ▼
                DuckDB (stands in for Redshift) ──► rows ──► Claude writes the answer
                                                     └──► app shows the query and the rows
```

## Setup on a Mac (about 10 minutes)

Use Python 3.11 or newer. If `python3 --version` shows 3.9, install Python 3.12 from python.org first; recent Streamlit releases no longer support 3.9.

```bash
cd account-intelligence
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt

python generate_data.py        # builds data/crm_demo.duckdb
python export_for_tableau.py   # writes tableau/data/*.csv for Tableau Public
python export_for_pulse.py     # rebuilds pulse/index.html from the same definitions
python -m pytest -q            # 19 tests should pass

export ANTHROPIC_API_KEY="sk-ant-..."   # from console.anthropic.com, a few dollars of credit is plenty
streamlit run app.py           # opens http://localhost:8501
```

The assistant uses `claude-sonnet-5-5` by default. To try another model, set it before starting the app, for example `export ANTHROPIC_MODEL=claude-haiku-5-5` for faster and cheaper answers.

## Assistant demo script (2 to 3 minutes, at the end of the pitch)

Run every question live at least twice before the interview. Each live answer is saved to `cache/answers.json`, and the "Use saved answers" switch in the sidebar replays them if the network or the API fails. Also record a short screen capture as a last resort.

| Step | Signed in as | Ask | What it proves |
| --- | --- | --- | --- |
| 1 | Regional VP | Which physicians at Riverbend have gone quiet since the Plaque dinner program? | It finds 4 of the 12 attendees who ordered before and none after. Open "How this was answered": the model picked a governed metric, it did not write SQL |
| 2 | Maya Ellison, TAM Northern California | The same question | Row level security. Riverbend is in Ohio Valley, so Maya gets nothing and is told it is outside her territory. The filter is added in code, not in the prompt, so no wording gets around it |
| 3 | Jordan Pike, TAM Ohio Valley | Which accounts in my territory have the lowest estimated utilization? | The answer carries the metric's caveat that the CCTA denominator is an estimate. Definitions travel with the numbers |
| 4 | Regional VP | How has Plaque's share of cases trended by month this year? | A line chart from one governed measure. Plaque share rises from about 9% in January to about 17% by September |
| 5 | Regional VP | Show me the patient names for Riverbend's cases last month. | It declines. There are no patient columns to leak; `test_no_patient_columns_anywhere` fails the build if one is ever added |
| 6 | Regional VP | Which accounts need review, and which are just data gaps? | 8 accounts are flagged Review decline and 3 are labeled Data gap, including Summit Heart Institute, which looks like a 32% drop but is missing 14 days of feed. This is the answer to "how do you know a drop is real?" |

In the interview, steps 1, 2, and 5 are enough. Close by noting that the tests and the GitHub Actions workflow fail any pull request that breaks a metric definition or the security rule, before a stakeholder sees a wrong number.

### Data coverage: missing is not zero

Raw counts cannot tell a real decline from a feed that stopped arriving. The `accounts` model records feed gaps (days an account's cases never arrived) and labels each account:

- **Data gap**: any missing feed day in the last 180 days. Its change in cases is not trusted, and it is sent to the data owner.
- **Review decline**: complete coverage, at least 60 cases in the earlier 90 days, and a drop of 30% or more. It is sent to the account manager.
- **No flag**: everything else.

The pair to remember: Summit Heart Institute fell 32.3% (300 to 203 cases) with 14 missing days, so it is a Data gap. Fairhaven Medical Center fell 32.4% (74 to 50) with complete data, so it is a Review decline. Same raw drop, opposite action. The territory change is -10.4% on raw counts and -9.8% once the 3 gap accounts are left out (`verified_case_change_pct`).

The 30% threshold and the 60 case minimum are illustrative; they would be agreed with the account managers. `tests/test_semantic_layer.py::test_feed_gap_is_labeled_not_called_a_decline` locks this behavior in.

### Numbers to know cold

- Riverbend Plaque Dinner Program, 2026-06-18: 12 attendees, 4 went quiet, attendee cases fell by 52 in the 90 days after versus before.
- The four: Lena Kowalski, NP (35 cases before, 0 after), Dr. Farah Bishop (17, 0), Dr. Riley Ellery (7, 0), Dr. Farah Whitaker (6, 0).
- Every territory shows lower volume in the last 90 days than the 90 before. That is July and August seasonality built into the data. If asked, say a year over year measure is the right comparison and would be the next metric you add.

## How this maps to a production commercial data stack

| In this demo | In production |
| --- | --- |
| `generate_data.py` and a DuckDB file | Salesforce, the case production system, and NetSuite, landed in Redshift by Dagster and dbt |
| `semantic_model.yaml` | Cube model files in Git, changed through reviewed pull requests (`cube/model/cases.yml`, run and checked locally) |
| `export_for_tableau.py` and CSVs | A published Tableau data source on Redshift, owned by Analytics Engineering |
| Territory filter in `semantic_layer.py` | Cube `queryRewrite` or access policies driven by the signed-in user (`cube/cube.js`) |
| `tests/` and `.github/workflows/tests.yml` | The same checks in the team's CI |
| Streamlit app | An internal app, or a component inside Salesforce so reps never leave it |
| Not built yet | Writing a recommended next action back to Salesforce as a Task for the TAM |

## What each file does (be ready to read any of these aloud)

- **`generate_data.py`** builds six tables with a fixed random seed so the numbers never change between runs. Each physician gets an ordering weight; monthly cases are drawn from a Poisson distribution scaled by the account's CCTA volume, a ramp after activation, and summer seasonality. It plants the Riverbend story by stopping four attendees' cases on the dinner date and boosting the other eight.
- **`semantic_model.yaml`** defines four models (`cases`, `physician_activity`, `event_followup`, `accounts`). Each has base SQL, named dimensions, and named measures with descriptions. The descriptions are what the assistant reads to choose a metric.
- **`semantic_layer.py`** is the only path to the database. `compile()` rejects any model, measure, dimension, or operator not in the YAML, adds the territory filter when the user has one, passes every filter value as a `?` parameter, and builds `SELECT ... FROM (base) WHERE ... GROUP BY ... ORDER BY ... LIMIT`. `run()` opens the database read only.
- **`agent.py`** gives Claude one tool, `query_metrics`, and a system prompt containing the catalog and the rules (no invented numbers, decline patient questions, lead with the answer). It loops: Claude requests a query, the code runs it or returns the validation error so Claude can correct itself, then Claude writes the answer. Every answer is cached for replay.
- **`app.py`** is the Streamlit page: a user picker that sets the territory, suggested questions, the chat, and an expander that shows each query as JSON, the compiled SQL, and the rows.
- **`export_for_tableau.py`** runs the base SQL of each model in `semantic_model.yaml` and writes it to CSV, so Tableau uses exactly the definitions the assistant uses.
- **`tableau/BUILD_GUIDE.md`** is the click-by-click guide to the dashboard, with every calculated field, expected numbers to check against, and the Tableau questions to expect. `tableau/preview/dashboard_sketch.png` shows the target.
- **`cube/`** holds the Cube model and security rule, plus scripts to run Cube locally; see `cube/README.md`.
- **`tests/`** checks that unknown names are rejected, that a SQL injection string is harmless, that a TAM cannot see or filter into another territory, that no patient columns exist, that the planted story holds, that the Tableau export matches the semantic layer, that monthly ramp data includes zero months, and (with a fake Claude client, so no API key is needed) that the agent recovers from a rejected query and caches answers.

## Honest limitations

- Synthetic data; the patterns are planted.
- Each query reads one model. Questions that need two models joined take two queries; Cube handles joins natively.
- The model can still misread a question. That is why every answer shows its query, and why the next step is a fixed set of test questions with expected queries, run on every change.
- Utilization uses an estimated denominator, and the metric says so.
- No write back to Salesforce yet.
- The data coverage check lives in the Python semantic model and the Tableau export. The Cube files in `cube/` cover the cases, accounts, and physicians cubes only and do not include it yet.
- Tableau Public has no sign-in, so territory security in Tableau is shown as a filter; `tableau/BUILD_GUIDE.md` explains how it would be enforced on Tableau Cloud.

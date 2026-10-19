# Building the Account Intelligence dashboard in Tableau Public

Target: one dashboard with a KPI band, three views, a territory filter, a parameter, and a click-through action. Open `preview/dashboard_sketch.png` to see what you are aiming for. The sketch is matplotlib, not Tableau; build your own and use your own screenshots as the backup.

Time: about 3 to 4 hours the first time. Build it once fully, then rebuild the hardest sheet (ramp curves) from scratch the next day so you can explain every click.

Use the free **Tableau Public desktop app** (tableau.com/products/public/download), not web authoring. Everything below works in both, but the desktop app is faster and more reliable for relationships, parameters, and dashboard actions.

## 0. Create the data

```bash
source .venv/bin/activate
python generate_data.py
python export_for_tableau.py
```

This writes five CSVs to `tableau/data/`. Each one is the base SQL of a model in `semantic_model.yaml`, so Tableau and the AI assistant use identical definitions.

| File | Grain | Used for |
| --- | --- | --- |
| `accounts.csv` | one row per account, with data coverage fields (`data_status`, `account_signal`, `missing_days_180d`) | KPI band, utilization view |
| `physician_activity.csv` | one row per physician | Gone quiet view |
| `account_monthly.csv` | one row per account per month since go-live, zero months included | Ramp curves |
| `event_followup.csv` | one row per physician per event | Optional program view |
| `cases.csv` | one row per case | Not needed for the dashboard; available for extra exploration |

Tableau renames fields on import: `cases_last_90d` shows as something like **Cases Last 90D**. The names below use that display style. Match by meaning if the capitalization differs slightly.

## 1. Connect and relate the tables

1. Open Tableau Public. Under Connect, choose **Text file** and open `accounts.csv`.
2. Drag `physician_activity.csv` onto the canvas next to `accounts`. Tableau draws a relationship line. Click it and set **Account Id = Account Id**.
3. Drag `account_monthly.csv` onto the canvas, also related to `accounts` on **Account Id = Account Id**.
4. Leave `event_followup.csv` for later as its own data source.

Why relationships and not joins: the three tables have different grains (account, physician, account-month). A join would duplicate account rows and inflate sums. Relationships let Tableau aggregate each table at its own grain and only combine results. Expect this question.

## 2. Create the parameter

Right-click in the Data pane, **Create Parameter**:

- Name: `Quiet Threshold Days`
- Data type: Integer, current value 60
- Allowable values: Range, minimum 30, maximum 180, step 15

Right-click it and choose **Show Parameter**.

## 3. Create the calculated fields

Right-click in the Data pane, **Create Calculated Field**, one at a time.

**Est Utilization** (format as percentage, 1 decimal)
```
SUM([Cases Last 90D]) / SUM([Est Ccta 90D])
```

**Case Change %** (format as percentage, 1 decimal)
```
(SUM([Cases Last 90D]) - SUM([Cases Prior 90D])) / SUM([Cases Prior 90D])
```

**Territory Utilization** (a level of detail expression)
```
{ FIXED [Territory] : SUM([Cases Last 90D]) / SUM([Est Ccta 90D]) }
```

**Gap To Territory** (format as percentage)
```
[Est Utilization] - MIN([Territory Utilization])
```

**Gone Quiet** (from `physician_activity`; a boolean)
```
[Days Since Last Case] >= [Quiet Threshold Days]
AND [Lifetime Cases] >= 5
```
Physicians with no cases have a null Days Since Last Case, so they are correctly excluded. The 5 lifetime cases rule keeps one-off orderers out of the list.

**Quiet Physicians**
```
COUNTD(IF [Gone Quiet] THEN [Physician Id] END)
```

**Cases Per Account** (use the `account_monthly` fields: Cases and Account Id from that table)
```
SUM([Cases]) / COUNTD([Account Id (Account Monthly)])
```

**Accounts In Month**
```
COUNTD([Account Id (Account Monthly)])
```

## 4. Sheet: KPI band

1. New sheet, name it `KPIs`.
2. Drag **Measure Names** to Columns and **Measure Values** to Text.
3. On the Measure Values shelf keep only: Accounts (use **CNT(Account Id)** from `accounts`, rename the alias to "Accounts"), Cases Last 90D (SUM), Est Utilization, Case Change %, Quiet Physicians.
4. Format: Measure Values font 20 to 24 pt bold, headers 10 pt grey. Hide the row header.

## 5. Sheet: utilization by account

1. New sheet, `Utilization`.
2. Rows: **Account Name** (from `accounts`). Columns: **Est Utilization**.
3. Sort Account Name ascending by Est Utilization, so the biggest upside is at the top.
4. Color: **Case Change %**. Edit colors: Orange-Blue Diverging, center 0, so declining accounts are orange.
5. Add the territory benchmark reference line:
   - In the **Data** pane, drag **Territory Utilization** onto **Detail** on the Marks card. Open its pill menu and choose **Measure → Minimum**, so it reads **MIN(Territory Utilization)** and stays green (continuous). A reference line can only use fields already in the view; adding it to Detail makes it available in the Value menu.
   - Drag **Territory** from `accounts` to **Filters** and select **Ohio Valley** for the initial build. Use one territory at a time so the benchmark represents that territory. In the dashboard step, use the same Territory filter across all sheets.
   - Switch to **Analytics**, drag **Reference Line** onto the **Est Utilization** axis, and drop on **Pane**.
   - In the line dialog, set **Value** to **MIN(Territory Utilization)** and **Computation** to **Minimum**. Set **Label → Custom** and type `Territory average`. For Ohio Valley, the benchmark should be approximately **20.4%**.
   - If you already opened the line dialog without adding the field to Detail, cancel it first, add the field, then add or edit the line again.
6. Tooltip: Account Name, Account Type, Est Utilization, Gap To Territory, Cases Last 90D, Est Ccta 90D, Active Physicians, Case Change %.
7. Title: `Estimated utilization by account, lowest first`.

**Optional, and worth the 10 minutes: show data gaps.** The exported `accounts.csv` has an **Account Signal** column (Data gap, Review decline, No flag). Drag **Account Signal** to Shape on this sheet, or to Filters. In Ohio Valley there are no data gaps and three Review declines (Clearwater Regional Hospital, Hawthorne Regional Hospital, Shoreline Heart and Vascular). Switch the territory filter to Great Lakes to show the three Data gap accounts, including Summit Heart Institute. Say why: a missing feed day looks like a decline, so those accounts go to the data owner, not the account manager.

## 6. Sheet: physicians gone quiet

1. New sheet, `Gone Quiet`.
2. Filters: drag **Gone Quiet** to Filters, keep True.
3. Rows: **Physician Name**, then **Account Name (Physician Activity)**, then **Last Case Date** as an exact date (discrete).
4. Columns: **SUM(Cases Prior 90D)**. Sort descending.
5. Color: a single strong color (the accent red).
6. Title, using the parameter so it changes live: `Physicians quiet for <Parameters.Quiet Threshold Days>+ days` (insert the parameter from the title editor's Insert menu).
7. Tooltip: Specialty, Days Since Last Case, Lifetime Cases, Activity Status.

Bar length means the cases this physician sent in the 90 days before the latest 90. That is the volume at risk, so the top of the list is where a TAM should call first.

## 7. Sheet: ramp curves

1. New sheet, `Ramp`.
2. Filters: **Activation Cohort (Account Monthly)** = "Activated in last 12 months".
3. Columns: **Months Since Activation** as a continuous dimension (right-click, Dimension, then Continuous).
4. Rows: **Cases Per Account**. Mark type Line, add circle markers.
5. Drag **Accounts In Month** to Filters, choose "At least 3". This hides months where the average comes from one or two accounts and would jump around misleadingly. Expect a question about it; it is a good one to get.
6. Polish (optional, and impressive): duplicate the Rows pill as a second axis with **SUM(Cases)** and **Account Name (Account Monthly)** on Detail, thin light grey lines, then Dual Axis and Synchronize Axis. Grey lines are each account; the dark line is the average.
7. Title: `Ramp curves: accounts activated in the last 12 months`.

## 8. Dashboard

1. New dashboard, Size: Fixed, 1400 x 900.
2. Top: a text title "Account Intelligence" and a subtitle "Synthetic data, snapshot 2026-09-30".
3. Under it, the `KPIs` sheet across the full width.
4. Left two thirds: `Utilization`. Right column: `Gone Quiet` on top, `Ramp` below.
5. Show a **Territory** filter (from `accounts`) as a single value dropdown, and choose **Apply to Worksheets, All Using This Data Source**. Show the **Quiet Threshold Days** parameter as a slider.
6. Dashboard menu, **Actions**, **Add Action, Filter**: source sheet `Utilization`, target sheet `Gone Quiet`, run on Select, clearing the selection shows all values. Now clicking an account shows only its quiet physicians.
7. Set the Territory filter to **Ohio Valley** before publishing, so the demo opens on the story.

## 9. Optional: program follow-up view

Connect `event_followup.csv` as a second data source. Rows: **Event Name**. Columns: **CNT(Physician Name)**. Color: **Followup Status**. Filter Event Type = Dinner program. The Riverbend Plaque Dinner Program shows 4 of 12 attendees went quiet. Use this only if you have time; it links Tableau to the assistant demo.

## 10. Publish and back up

1. **File, Save to Tableau Public As**, name it `Account Intelligence (synthetic data)`.
2. On your Tableau Public profile, open the workbook settings, turn off "show sheets as tabs", and copy the link into your slides.
3. Take full-screen screenshots of the dashboard: Ohio Valley at 60 days, after clicking Riverbend, and with the slider at 120 days. These are your backup if Wi-Fi fails.

Tableau Public workbooks are public. That is fine here because every row is synthetic. Never publish real company data to Tableau Public.

## 11. Numbers to check while you build (Ohio Valley, threshold 60 days)

| Check | Expected |
| --- | --- |
| Accounts | 25 |
| Cases, last 90 days | 1,516 |
| Est Utilization | 20.4% |
| Case Change % | -19.6% |
| Quiet Physicians | 49 |
| Lowest utilization account | Shoreline Diagnostic Imaging, 7.7% |
| Account Signal in Ohio Valley | 3 Review decline, 22 No flag, 0 Data gap |
| Account Signal in Great Lakes | 3 Data gap, 34 No flag |
| Top of the gone quiet list | Lena Kowalski, NP (Riverbend Heart Institute), 29 |
| All territories: accounts, cases, utilization | 180, 13,378, 26.0% |

If a number is off, the usual cause is a join instead of a relationship, or a field taken from the wrong table.

Why every territory shows a decline: the last 90 days include July and August, which run about 15% lower in this data (the seasonality real CCTA volumes show). Say so if asked, and that a year-over-year comparison is the right fix.

Why Lena Kowalski shows 29 here but 35 in the assistant's dinner program answer: different windows. Here it is the 90 days before the latest 90 (Apr 3 to Jul 2); there it is the 90 days before the dinner (Mar 20 to Jun 17). Both are governed definitions with documented windows.

## 12. Tableau questions to expect

| Question | Answer |
| --- | --- |
| Why relationships, not joins? | Different grains. Joins would duplicate account rows and inflate sums |
| What does the FIXED expression do? | Computes territory utilization at the territory level regardless of what is in the view, so each account can be compared with its territory |
| Extract or live connection? | Extract for Tableau Public. In production, a published Redshift data source owned by Analytics Engineering, extract or live depending on freshness needs and query cost |
| How would you secure it per TAM? | On Tableau Cloud, a data source filter such as `ISMEMBEROF("Regional Leaders") OR [Tam Name] = FULLNAME()`, or better, enforce it once in the semantic layer so Tableau, apps, and AI all inherit it |
| Why the 5 lifetime cases rule? | Keeps one-off orderers out, so the list is physicians worth a visit |
| Why hide months with fewer than 3 accounts? | An average of one or two accounts is noise and would mislead |
| How would you know this dashboard is used? | Tableau's usage stats by view and user, plus asking TAMs which view changed a call they made |

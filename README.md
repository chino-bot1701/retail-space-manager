# Retail Space Manager — Occupancy as an Append-Only Ledger

> Leasing system for shopping-centre space: floor plan, availability, tenants
> and history. **Releasing a unit never deletes anything** — it posts a
> negative-square-metre entry. Occupancy is the running sum, so the history and
> the current state cannot drift apart.

![Python](https://img.shields.io/badge/Python-3.11+-3776AB) ![Streamlit](https://img.shields.io/badge/Streamlit-leasing%20app-FF4B4B) ![Altair](https://img.shields.io/badge/Altair-floor%20plan-1f77b4) ![tests](https://img.shields.io/badge/tests-43%20passing-2b6cb0)

> [!IMPORTANT]
> **Rebuild of a production R/Shiny app, on synthetic data.** The original runs
> inside a Mexican real-estate group against Snowflake. This repository keeps
> the data model and the business rules, rebuilt in Python, over a **generated**
> market — no plaza, brand, tenant or contract here is real, and no real record
> was anonymized to produce them. Every figure below describes this synthetic
> dataset and nothing else.

**▶ Live demo: <https://retail-space-manager.streamlit.app>** — *first load may take ~40s while the free instance wakes up.*

![Floor plan](docs/plano_ocupacion.png)

---

## The problem

A leasing team needs four answers, all day, about three shopping centres:

- **What is free right now, and how many square metres?**
- **Who is in unit PB-014, and under which contract?**
- **Register a new tenant / expand one / hand a unit back.**
- **When did this tenant move in, and when did the previous one leave?**

The original system answered all four from Excel-backed tables, then from a
Shiny app on Snowflake. It got two things right that most inventory systems get
wrong, and those two are what this repository is about.

### 1 · A unit is not occupied or free — it is occupied by *how much*

A 300 m² unit can hold two tenants behind one shopfront, or one tenant on 180 m²
with 120 m² still to lease. A boolean `occupied` column cannot express that, and
once the model is boolean the reports are wrong forever. Here every unit tracks
**square metres**, and *partial* falls out of the arithmetic instead of being a
third state somebody has to maintain.

### 2 · Handing back a unit is an event, not an undo

The original never issued a `DELETE` or an `UPDATE`. To release space it
inserted a row with **negative square metres**. That one decision is why the
history tab exists at all.

---

## The ledger

```
occupied(unit)   = Σ entries for that unit
available(unit)  = total m² − occupied(unit)
state at date D  = Σ entries with date ≤ D
```

That is the whole model. Three consequences make it worth defending:

**History is not a log somebody has to remember to write.** It *is* the ledger.
It cannot fall out of sync with the current state, because the current state is
derived from it. There is no `current_occupancy` table to reconcile.

**Any past date is a query, not an investigation.** "What was in unit 014 in
March 2023?" is a filter. The demo has a date slider that redraws the floor plan
for any month since January 2022 — no historical snapshots, no audit table.

**A mistake is corrected by a compensating entry, not by editing the past.**
Both entries stay visible. This is how accounting has worked for six centuries
and it is the right shape for anything a regulator or an auditor might ask about.

The price is that **validation has to happen at write time**, because afterwards
there is nowhere to fix it. That is the single biggest difference from the system
this is modelled on.

---

## What changed from the original

Three defects found while porting. Each one is now a test.

### The release path never checked the balance

The original built the release like this:

```r
# read the tenant name, then post the negative — with no check that
# the contract actually holds those metres in that unit
query_insert <- sprintf(
  "INSERT INTO OCCUPANCY_LEDGER (...) VALUES ('%s','%s',%.2f,'%s',...)",
  id_comercial, id_local, -abs(metros_a_liberar), cliente, ...)
```

Renting validated available space. Releasing did not. Hand back 200 m² from a
100 m² tenancy and the unit ends up with *negative* occupancy, quietly, and the
availability report is wrong from then on. Worse with two tenants sharing a
unit: one of them can release the other's square metres.

Here, `Libro.asentar` refuses both, by contract and by unit:

```python
if m2 > 0:
    if m2 > self.disponible(id_local) + EPS:
        raise AsientoInvalido(...)      # does not fit
else:
    if abs(m2) > self.saldo_contrato(id_contrato, id_local) + EPS:
        raise AsientoInvalido(...)      # not yours to give back
```

### A multi-unit contract could be posted half-way

Leases routinely cover two or three adjacent units. In the original each unit
was a separate `INSERT` in a loop, so a failure on the third left the first two
posted — and nobody found out until billing did not reconcile. Here a
multi-unit posting is **rehearsed on a copy first**: if any leg fails, none is
written.

### Contract ids were built by concatenating unit numbers

The original id looked like `PB-014_PB-016_8231`: the units joined together plus
a random number, checked against the database for collisions. Three problems —
it is unreadable, it *changes meaning* when the tenant expands into another
unit, and the check-then-insert is a race between two clerks. Replaced by a
readable sequence per centre and year, `PALT-2026-0007`, which keeps its
identity through expansions.

### And one more, found by the tests

Client names went into SQL through `sprintf`. A tenant called `Café O'Brien`
closes the string literal. There is a parametrized test for exactly that, plus
four other names that break naive concatenation.

---

## The data

Generated, not anonymized.

| | |
|---|---|
| Shopping centres | 3 (opened 2019, 2021 and 2022) |
| Units | 157, including 5 anchor boxes |
| Leasable area | 26,273 m² |
| Ledger | 383 entries, Jan 2022 → Aug 2026 |
| Contracts | 265 · 157 active · 108 closed |
| Tenants | 72 fictional brands across 11 categories |

The generator does not write the ledger directly — **it calls the same API the
app calls** (`Libro.alta`, `.expansion`, `.baja_total`). If an invariant breaks,
the data cannot be generated at all. It is the cheapest smoke test available.

Each centre has its own lease-up curve, counted from **its own opening year**:

![Occupancy over time](docs/ocupacion_historica.png)

Paseo Altamira was already mature when the ledger starts, so January 2022 is a
migration of the state it already had. Paseo San Isidro opens that month and
fills over three years. Neither centre ever reaches 100% — one unit is always
under fit-out or between tenants, and a dashboard showing 100% is a dashboard
that is lying.

---

## Measured, not asserted

`python scripts/run_demo.py` runs the pipeline and checks 24 assertions. A few
worth naming:

| | |
|---|---|
| Current occupancy by area | **92.3%** |
| …by unit count | 94.3% — *not the same number* |
| Shared units (two tenants, one unit) | 7 |
| State vs. sum of the ledger | max gap **0.000 m²** |
| Units over their own area | 0 |
| Median closed-lease duration | 1,161 days |

**Occupancy is reported by square metres, not by unit count.** An empty anchor
weighs what it weighs; counting it as "one of 157" hides the hole. Both numbers
are shown, precisely so the gap is visible.

The assertions that matter most are the ones about the ledger itself: entry
numbers are gapless, no entry is dated before the one before it, every closed
contract nets to exactly zero, and the state recomputed from the raw entries
matches the state the app displays — today and at any past cut-off.

---

## Running it

```bash
pip install -r requirements.txt

python scripts/run_demo.py          # 24 assertions
streamlit run app/gestor.py         # the app

pip install -r requirements-dev.txt
pytest -q                           # 43 tests
```

**No credentials, no database, no environment variables.** The app generates its
world at startup and keeps the ledger in session state, so anyone can post
entries in the demo without touching anyone else's.

### Layout

```
src/plaza.py             unit catalogue + floor-plan geometry
src/libro.py             the append-only ledger — the core
src/ocupacion.py         state derived from the ledger
src/plano.py             the floor plan, in Altair
src/generar_historia.py  4½ years of synthetic movement
app/gestor.py            Streamlit: plan · rent · release · history
```

`src/libro.py` is the file to read first. Everything else derives from it.

---

## Honest limits

**The ledger is recomputed, not materialized.** Every view sums the entries.
With tens of thousands of rows that is milliseconds in pandas; at a hundred
million it needs a materialized view refreshed on write. The design does not
change — what changes is where the sum is cached. Maintaining the state by hand
is not the alternative; it is the bug.

**Entries cannot be back-dated.** That is deliberate, and it is what a ledger
means, but it does mean a lease signed on the 1st and captured on the 8th is
recorded on the 8th. The clean fix is two dates per entry — when it happened and
when it was posted — which is what a production version should carry.

**Unit geometry is a rectangle.** Real leasing plans are irregular polygons from
CAD. Rectangles are enough to show occupancy and keep the plan honest (the
rectangle's area *is* the leasable area), but a real deployment would read the
actual polygons — which is what
[`property-portfolio-geo`](https://github.com/chino-bot1701/property-portfolio-geo)
does with WKT and geodesic areas.

**No money.** Rents, escalations and recoveries are the obvious next layer, and
the ledger is the right place for them: a rent change is another entry.

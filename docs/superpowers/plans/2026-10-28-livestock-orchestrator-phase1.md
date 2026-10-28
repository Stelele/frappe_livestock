# Livestock Orchestrator — Phase 1 (Broilers) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build phase 1 of `frappe_livestock` — a capture-first orchestration layer over ERPNext for broiler flocks: one-tap mortality/feed capture, a one-action purchase cycle (PO→PR→PI→Payment), flock cost allocation, FIFO sale allocation, and simple cost-per-bird.

**Architecture:** A Frappe v16 app adding custom DocTypes (Livestock Type + Stage, Housing + Region, Flock, Mortality, Feed Event, Flock Cost + Item) as the orchestration layer, reusing ERPNext Item / Purchase Order / Purchase Receipt / Purchase Invoice / Payment Entry as the ledger. Derived values (age, stage, remaining, cost) are computed on read via `Flock` controller methods — no scheduler. Whitelisted methods live under `frappe_livestock.api.*`; a `doc_events` hook drives sale allocation.

**Tech Stack:** Frappe Framework v16 + ERPNext v16, Python 3.14, `frappe.get_doc` ORM, Ruff (tab indent), pre-commit. Tests run via `bench run-tests --app frappe_livestock`.

**Spec:** `docs/superpowers/specs/2026-10-28-livestock-orchestrator-design.md`

## Global Constraints

- Package is `frappe_livestock` (folder = app_name). Doctypes under `frappe_livestock/frappe_livestock/frappe_livestock/doctype/`; API under `frappe_livestock/api/`; controllers importable as `frappe_livestock.frappe_livestock.doctype.<name>.<name>`.
- `frappe.call` paths include the `.api` segment: `frappe.call("frappe_livestock.api.purchase.create_full_purchase", ...)`.
- Generic over custom: no hardcoded species, stage schedule, item mapping, or naming. Seed data via patch, everything configurable.
- Live birds are not ERPNext stock — flock quantity is a plain number; no Stock Entry / Work Order for birds.
- Feed Events are informational (no stock ledger write); medicine is cost-only (no event capture).
- Payment is always immediate and in full; only the mode of payment varies.
- Simplicity over resilience: no queues, no retry machinery, no offline support.
- Python indent is tabs (Ruff); run `pre-commit run --all-files` before each commit.
- Explicit save over autosave; restraint in UI.

## Review Focus

1. **All birds die** → `cost_per_bird` returns `0`, never divides by zero. (pinned in Task 7)
2. **Over-sale** → allocation never lets `birds_sold` exceed `surviving_birds`; clamps and records the shortfall. (pinned in Task 8)
3. **Flock with no costs yet** → `total_cost` / `cost_per_bird` are `0`, not an error. (pinned in Task 7)
4. **Stage boundary off-by-one** → age exactly at a stage's `start_day`/`end_day` maps to the correct stage. (pinned in Task 1)
5. **Duplicate allocation** → allocating the same purchase twice upserts, never double-counts. (pinned in Task 7)

---

### Task 1: Livestock Type + Stage (species & stage schedule)

**Files:**
- Create: `frappe_livestock/frappe_livestock/frappe_livestock/doctype/livestock_type/livestock_type.json`
- Create: `frappe_livestock/frappe_livestock/frappe_livestock/doctype/livestock_type/livestock_type.py`
- Create: `frappe_livestock/frappe_livestock/frappe_livestock/doctype/livestock_stage/livestock_stage.json`
- Create: `frappe_livestock/frappe_livestock/frappe_livestock/doctype/livestock_stage/livestock_stage.py`
- Test: `frappe_livestock/frappe_livestock/frappe_livestock/doctype/livestock_type/test_livestock_type.py`
- Modify: `frappe_livestock/patches.txt`, and create `frappe_livestock/patches/seed_broiler_type.py`

**Interfaces:**
- Produces: `LivestockType` DocType (fields `finished_item` Link Item, `stages` Table → `Livestock Stage`); `Livestock Stage` child (fields `stage_name` Data, `start_day` Int, `end_day` Int).
- Produces module function: `get_stage_for_age(stages: list[dict], age_days: int) -> dict | None` returning `{"stage_name", "start_day", "end_day"}` of the first stage where `start_day <= age_days <= end_day`; if `age_days >` the greatest `end_day`, return the last stage (by `start_day`); if `age_days < 0`, return `None`.

- [ ] **Step 1: Write the failing test** (`test_livestock_type.py`)

```python
import frappe
from frappe.tests import IntegrationTestCase
from frappe_livestock.frappe_livestock.doctype.livestock_type.livestock_type import get_stage_for_age

BROILER_STAGES = [
    {"stage_name": "Day Old Chick", "start_day": 0, "end_day": 20},
    {"stage_name": "Grower", "start_day": 21, "end_day": 41},
    {"stage_name": "Broiler", "start_day": 42, "end_day": 48},
]

class TestLivestockType(IntegrationTestCase):
    def test_stage_boundaries(self):
        self.assertEqual(get_stage_for_age(BROILER_STAGES, 0)["stage_name"], "Day Old Chick")
        self.assertEqual(get_stage_for_age(BROILER_STAGES, 20)["stage_name"], "Day Old Chick")
        self.assertEqual(get_stage_for_age(BROILER_STAGES, 21)["stage_name"], "Grower")
        self.assertEqual(get_stage_for_age(BROILER_STAGES, 41)["stage_name"], "Grower")
        self.assertEqual(get_stage_for_age(BROILER_STAGES, 42)["stage_name"], "Broiler")

    def test_stage_clamps_to_last_stage_past_final(self):
        self.assertEqual(get_stage_for_age(BROILER_STAGES, 60)["stage_name"], "Broiler")

    def test_negative_age_returns_none(self):
        self.assertIsNone(get_stage_for_age(BROILER_STAGES, -1))

    def test_broiler_type_is_seeded(self):
        self.assertTrue(frappe.db.exists("Livestock Type", "Broiler"))
```

- [ ] **Step 2: Run test to verify it fails**

Run: `bench run-tests --app frappe_livestock --module frappe_livestock.frappe_livestock.doctype.livestock_type.test_livestock_type`
Expected: FAIL (module / DocType not found)

- [ ] **Step 3: Implement the two DocTypes and `get_stage_for_age`**

`Livestock Type` DocType (istable=0): fields `finished_item` (Link → Item), `stages` (Table → Livestock Stage). `Livestock Stage` (istable=1): `stage_name` (Data, reqd), `start_day` (Int, reqd), `end_day` (Int, reqd). Controller `livestock_type.py` exports `get_stage_for_age(stages, age_days)` per the Produces signature.

- [ ] **Step 4: Seed the Broiler type via a patch**

`patches/seed_broiler_type.py` idempotently creates a "Broiler" `Livestock Type` (stages: Day Old Chick 0–20, Grower 21–41, Broiler 42–48) if absent; add it to `patches.txt`.

- [ ] **Step 5: Run test to verify it passes**

Run: `bench run-tests --app frappe_livestock --module frappe_livestock.frappe_livestock.doctype.livestock_type.test_livestock_type`
Expected: PASS (4 tests)

- [ ] **Step 6: Commit**

```bash
git add frappe_livestock/frappe_livestock/frappe_livestock/doctype/livestock_type frappe_livestock/frappe_livestock/frappe_livestock/doctype/livestock_stage frappe_livestock/patches frappe_livestock/patches.txt
git commit -m "feat: Livestock Type + Stage doctypes with age-based stage lookup and Broiler seed"
```

---

### Task 2: Housing + Region (rooms / pens)

**Files:**
- Create: `frappe_livestock/frappe_livestock/frappe_livestock/doctype/housing/housing.json`
- Create: `frappe_livestock/frappe_livestock/frappe_livestock/doctype/housing/housing.py`
- Create: `frappe_livestock/frappe_livestock/frappe_livestock/doctype/housing_region/housing_region.json`
- Test: `frappe_livestock/frappe_livestock/frappe_livestock/doctype/housing/test_housing.py`

**Interfaces:**
- Produces: `Housing` DocType (fields `housing_type` Select: Brooding/Grower/Finisher/General, `capacity` Int, `status` Select: Occupied/Resting/Ready default Ready, `last_used_date` Date, `last_cleaned_date` Date, `regions` Table → `Housing Region`). `Housing Region` child (fields `region_name` Data reqd, `capacity` Int).

- [ ] **Step 1: Write the failing test**

```python
import frappe
from frappe.tests import IntegrationTestCase

class TestHousing(IntegrationTestCase):
    def test_default_status_is_ready(self):
        doc = frappe.get_doc({"doctype": "Housing", "housing_name": "Brooding A", "housing_type": "Brooding"}).insert()
        self.assertEqual(doc.status, "Ready")

    def test_regions_save(self):
        doc = frappe.get_doc({
            "doctype": "Housing",
            "housing_name": "Grower 1",
            "housing_type": "Grower",
            "regions": [{"region_name": "North", "capacity": 200}, {"region_name": "South", "capacity": 200}],
        }).insert()
        self.assertEqual(len(doc.regions), 2)
```

Note: use field name `housing_name` (Data, reqd) for the label to avoid colliding with the `name` autoname field.

- [ ] **Step 2: Run test to verify it fails**

Run: `bench run-tests --app frappe_livestock --module frappe_livestock.frappe_livestock.doctype.housing.test_housing`
Expected: FAIL

- [ ] **Step 3: Implement the two DocTypes**

Per the Produces block. Controller `housing.py` defines `class Housing(Document): pass`.

- [ ] **Step 4: Run test to verify it passes**

Run: `bench run-tests --app frappe_livestock --module frappe_livestock.frappe_livestock.doctype.housing.test_housing`
Expected: PASS (2 tests)

- [ ] **Step 5: Commit**

```bash
git add frappe_livestock/frappe_livestock/frappe_livestock/doctype/housing frappe_livestock/frappe_livestock/frappe_livestock/doctype/housing_region
git commit -m "feat: Housing + Housing Region doctypes"
```

---

### Task 3: Flock (autoname, age, stage, expected ready date)

**Files:**
- Create: `frappe_livestock/frappe_livestock/frappe_livestock/doctype/flock/flock.json`
- Create: `frappe_livestock/frappe_livestock/frappe_livestock/doctype/flock/flock.py`
- Test: `frappe_livestock/frappe_livestock/frappe_livestock/doctype/flock/test_flock.py`

**Interfaces:**
- Consumes: `Livestock Type` (Task 1), `Housing` (Task 2), `get_stage_for_age` (Task 1).
- Produces: `Flock` DocType with fields `livestock_type` (Link Livestock Type, reqd), `start_date` (Date, reqd), `quantity_placed` (Int, reqd), `housing` (Link Housing), `status` (Select: Draft/Active/Ready/Closed, default Active), `birds_sold` (Int, default 0). Controller `class Flock(Document)` with methods `age_days() -> int`, `stage_name() -> str | None`, `expected_ready_date() -> date | None`, plus `autoname()` producing `"{livestock_type} {start_date}"`.

- [ ] **Step 1: Write the failing test**

```python
import frappe
from frappe.tests import IntegrationTestCase
from frappe.utils import add_days, today

class TestFlock(IntegrationTestCase):
    def _make(self, start_days_ago=0):
        return frappe.get_doc({
            "doctype": "Flock",
            "livestock_type": "Broiler",
            "start_date": add_days(today(), -start_days_ago),
            "quantity_placed": 500,
        }).insert()

    def test_autoname_is_type_plus_start_date(self):
        doc = frappe.get_doc({
            "doctype": "Flock", "livestock_type": "Broiler",
            "start_date": "2026-10-28", "quantity_placed": 500,
        }).insert()
        self.assertEqual(doc.name, "Broiler 2026-10-28")

    def test_stage_and_age_are_computed(self):
        doc = self._make(start_days_ago=25)  # 25 days old -> Grower
        self.assertEqual(doc.age_days(), 25)
        self.assertEqual(doc.stage_name(), "Grower")

    def test_expected_ready_date_is_start_plus_final_stage_end(self):
        doc = frappe.get_doc({
            "doctype": "Flock", "livestock_type": "Broiler",
            "start_date": "2026-10-28", "quantity_placed": 500,
        }).insert()
        self.assertEqual(doc.expected_ready_date().isoformat(), "2026-12-15")  # 48 days later
```

- [ ] **Step 2: Run test to verify it fails**

Run: `bench run-tests --app frappe_livestock --module frappe_livestock.frappe_livestock.doctype.flock.test_flock`
Expected: FAIL

- [ ] **Step 3: Implement the Flock DocType and controller**

`autoname()` sets `self.name = f"{self.livestock_type} {self.start_date}"`. `age_days()` = `(today() - start_date).days` (floor at 0). `stage_name()` uses `get_stage_for_age(self.livestock_type stages, self.age_days())`. `expected_ready_date()` = `start_date + last stage end_day` (the max `end_day` across the type's stages).

- [ ] **Step 4: Run test to verify it passes**

Run: `bench run-tests --app frappe_livestock --module frappe_livestock.frappe_livestock.doctype.flock.test_flock`
Expected: PASS (3 tests)

- [ ] **Step 5: Commit**

```bash
git add frappe_livestock/frappe_livestock/frappe_livestock/doctype/flock
git commit -m "feat: Flock doctype with date-based autoname and computed age/stage/ready date"
```

---

### Task 4: Mortality → surviving & remaining birds

**Files:**
- Create: `frappe_livestock/frappe_livestock/frappe_livestock/doctype/mortality/mortality.json`
- Create: `frappe_livestock/frappe_livestock/frappe_livestock/doctype/mortality/mortality.py`
- Modify: `frappe_livestock/frappe_livestock/frappe_livestock/doctype/flock/flock.py`
- Test: `frappe_livestock/frappe_livestock/frappe_livestock/doctype/flock/test_flock.py`

**Interfaces:**
- Consumes: `Flock` (Task 3).
- Produces: `Mortality` DocType (fields `flock` Link Flock reqd, `date` Date default today, `qty` Int reqd ≥ 1, `reason` Small Text). `Flock` gains methods `mortalities_total() -> int`, `surviving_birds() -> int` (`quantity_placed − mortalities_total`), `remaining_birds() -> int` (`surviving_birds − birds_sold`).

- [ ] **Step 1: Write the failing test** (append to `test_flock.py`)

```python
class TestFlockMortality(IntegrationTestCase):
    def test_mortality_reduces_surviving_and_remaining(self):
        flock = frappe.get_doc({
            "doctype": "Flock", "livestock_type": "Broiler",
            "start_date": today(), "quantity_placed": 500,
        }).insert()
        frappe.get_doc({"doctype": "Mortality", "flock": flock.name, "qty": 12}).insert()
        self.assertEqual(flock.mortalities_total(), 12)
        self.assertEqual(flock.surviving_birds(), 488)
        self.assertEqual(flock.remaining_birds(), 488)

    def test_mortality_qty_must_be_positive(self):
        with self.assertRaises(frappe.exceptions.ValidationError):
            frappe.get_doc({"doctype": "Mortality", "flock": "x", "qty": 0}).insert()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `bench run-tests --app frappe_livestock --module frappe_livestock.frappe_livestock.doctype.flock.test_flock`
Expected: FAIL

- [ ] **Step 3: Implement Mortality DocType + Flock aggregation methods**

Mortality `validate()` throws on `qty < 1`. `Flock.mortalities_total()` = `sum` of `Mortality.qty` for this flock (via `frappe.db.get_value` with `SUM`); `surviving_birds()` = `quantity_placed − mortalities_total()`; `remaining_birds()` = `surviving_birds() − birds_sold`.

- [ ] **Step 4: Run test to verify it passes**

Run: `bench run-tests --app frappe_livestock --module frappe_livestock.frappe_livestock.doctype.flock.test_flock`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add frappe_livestock/frappe_livestock/frappe_livestock/doctype/mortality frappe_livestock/frappe_livestock/frappe_livestock/doctype/flock/flock.py frappe_livestock/frappe_livestock/frappe_livestock/doctype/flock/test_flock.py
git commit -m "feat: Mortality doctype and flock surviving/remaining computation"
```

---

### Task 5: Feed Event

**Files:**
- Create: `frappe_livestock/frappe_livestock/frappe_livestock/doctype/feed_event/feed_event.json`
- Create: `frappe_livestock/frappe_livestock/frappe_livestock/doctype/feed_event/feed_event.py`
- Test: `frappe_livestock/frappe_livestock/frappe_livestock/doctype/feed_event/test_feed_event.py`

**Interfaces:**
- Consumes: `Flock` (Task 3).
- Produces: `Feed Event` DocType (fields `flock` Link Flock reqd, `feed_item` Link Item reqd, `event` Select: Open/Finish reqd, `date` Date default today, `qty` Float optional). Informational only — no stock write.

- [ ] **Step 1: Write the failing test**

```python
import frappe
from frappe.tests import IntegrationTestCase

class TestFeedEvent(IntegrationTestCase):
    def test_feed_event_saves(self):
        flock = frappe.get_doc({
            "doctype": "Flock", "livestock_type": "Broiler",
            "start_date": frappe.utils.today(), "quantity_placed": 500,
        }).insert()
        doc = frappe.get_doc({
            "doctype": "Feed Event", "flock": flock.name,
            "feed_item": "Early Lay Feed", "event": "Open", "qty": 1,
        }).insert()
        self.assertEqual(doc.event, "Open")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `bench run-tests --app frappe_livestock --module frappe_livestock.frappe_livestock.doctype.feed_event.test_feed_event`
Expected: FAIL

- [ ] **Step 3: Implement the Feed Event DocType**

Per the Produces block; controller `class FeedEvent(Document): pass`.

- [ ] **Step 4: Run test to verify it passes**

Run: `bench run-tests --app frappe_livestock --module frappe_livestock.frappe_livestock.doctype.feed_event.test_feed_event`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add frappe_livestock/frappe_livestock/frappe_livestock/doctype/feed_event
git commit -m "feat: Feed Event doctype for bag open/finish tracking"
```

---

### Task 6: Full purchase cycle (PO → PR → PI → Payment)

**Files:**
- Create: `frappe_livestock/api/__init__.py`
- Create: `frappe_livestock/api/purchase.py`
- Test: `frappe_livestock/api/test_purchase.py`

**Interfaces:**
- Produces: `frappe_livestock.api.purchase.create_full_purchase(company, supplier, warehouse, items, invoice_number=None, invoice_date=None, mode_of_payment="Cash") -> dict` returning `{"purchase_order", "purchase_receipt", "purchase_invoice", "payment_entry"}`; `cancel_full_purchase(purchase_invoice) -> dict`; `amend_full_purchase(purchase_invoice, company, supplier, warehouse, items, invoice_number=None, invoice_date=None, mode_of_payment="Cash") -> dict`. `items` is a list of `{"item_code", "qty", "rate"}`. Payment is always full (`paid_amount == grand_total`), mode configurable.
- Reference implementation: `awesome_dashboard/awesome_dashboard/api/purchase.py` (`create_full_purchase` / `cancel_full_purchase` / `amend_full_purchase`). Reuse its structure; change only the payment to accept `mode_of_payment`.

- [ ] **Step 1: Write the failing test** (`test_purchase.py`)

```python
import frappe
from frappe.tests import IntegrationTestCase
from frappe.utils import get_defaults
from frappe_livestock.api.purchase import create_full_purchase, cancel_full_purchase

class TestFullPurchase(IntegrationTestCase):
    def setUp(self):
        self.company = frappe.defaults.get_user_default("company")
        self.supplier = frappe.get_doc({
            "doctype": "Supplier", "supplier_name": "FeedCo", "supplier_group": "All Supplier Groups",
        }).insert().name
        self.warehouse = frappe.db.get_value("Warehouse", {"company": self.company, "is_group": 0}, "name")
        self.item = frappe.get_doc({
            "doctype": "Item", "item_code": "Test Feed", "item_group": "Products", "stock_uom": "Nos",
            "is_stock_item": 1,
        }).insert().name

    def test_creates_four_submitted_docs(self):
        res = create_full_purchase(self.company, self.supplier, self.warehouse,
            [{"item_code": self.item, "qty": 10, "rate": 5}])
        self.assertEqual(frappe.db.get_value("Purchase Order", res["purchase_order"], "docstatus"), 1)
        self.assertEqual(frappe.db.get_value("Purchase Receipt", res["purchase_receipt"], "docstatus"), 1)
        self.assertEqual(frappe.db.get_value("Purchase Invoice", res["purchase_invoice"], "docstatus"), 1)
        self.assertEqual(frappe.db.get_value("Payment Entry", res["payment_entry"], "docstatus"), 1)

    def test_cancel_reverses_chain(self):
        res = create_full_purchase(self.company, self.supplier, self.warehouse,
            [{"item_code": self.item, "qty": 10, "rate": 5}])
        cancel_full_purchase(res["purchase_invoice"])
        self.assertEqual(frappe.db.get_value("Purchase Invoice", res["purchase_invoice"], "docstatus"), 2)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `bench run-tests --app frappe_livestock --module frappe_livestock.api.test_purchase`
Expected: FAIL

- [ ] **Step 3: Implement `api/purchase.py`**

Port `create_full_purchase` / `cancel_full_purchase` / `amend_full_purchase` from `awesome_dashboard/api/purchase.py` (same PO→PR→PI→PE construction, same cancel order, transactional commit). Change `_create_payment_entry` to accept `mode_of_payment` (default "Cash") instead of hardcoding it, keeping `paid_amount = pi.grand_total`. Decorate each with `@frappe.whitelist()`.

- [ ] **Step 4: Run test to verify it passes**

Run: `bench run-tests --app frappe_livestock --module frappe_livestock.api.test_purchase`
Expected: PASS (2 tests)

- [ ] **Step 5: Commit**

```bash
git add frappe_livestock/api
git commit -m "feat: full purchase cycle (PO→PR→PI→Payment) with cancel/amend"
```

---

### Task 7: Flock Cost + allocation → total cost & cost-per-bird

**Files:**
- Create: `frappe_livestock/frappe_livestock/frappe_livestock/doctype/flock_cost/flock_cost.json`
- Create: `frappe_livestock/frappe_livestock/frappe_livestock/doctype/flock_cost/flock_cost.py`
- Create: `frappe_livestock/frappe_livestock/frappe_livestock/doctype/flock_cost_item/flock_cost_item.json`
- Create: `frappe_livestock/api/allocation.py`
- Modify: `frappe_livestock/frappe_livestock/frappe_livestock/doctype/flock/flock.py`
- Test: `frappe_livestock/api/test_allocation.py`

**Interfaces:**
- Consumes: `Flock` (Task 3), `Purchase Invoice` (ERPNext).
- Produces: `Flock Cost` DocType (fields `purchase_invoice` Link Purchase Invoice reqd, `posting_date` Date; child `items` Table → `Flock Cost Item`). `Flock Cost Item` (fields `item_code` Link Item, `qty` Float, `amount` Currency, `flock` Link Flock reqd).
- Produces `frappe_livestock.api.allocation.split_purchase_to_flocks(purchase_invoice, allocations) -> dict`, where `allocations = [{"item_code", "qty", "flock"}]`; `amount` is derived as `source invoice line rate × qty`. Upserts one `Flock Cost` per purchase invoice (idempotent — re-running replaces the rows, never doubles). Also `get_active_flocks() -> list[dict]` (name, start_date, remaining_birds) of non-closed flocks, newest first.
- `Flock` gains `total_cost() -> float` (sum of `Flock Cost Item.amount` for this flock) and `cost_per_bird() -> float` (`total_cost / surviving_birds`, returning `0.0` when `surviving_birds == 0`).

- [ ] **Step 1: Write the failing test** (`test_allocation.py`)

```python
import frappe
from frappe.tests import IntegrationTestCase
from frappe_livestock.api.allocation import split_purchase_to_flocks

class TestAllocation(IntegrationTestCase):
    def _flock(self, date, placed=500):
        return frappe.get_doc({
            "doctype": "Flock", "livestock_type": "Broiler", "start_date": date, "quantity_placed": placed,
        }).insert()

    def test_split_across_two_flocks_and_cost(self):
        a = self._flock("2026-10-28"); b = self._flock("2026-11-14")
        # cost doc referencing a purchase invoice is hand-built to avoid needing a real PI
        cost = frappe.get_doc({
            "doctype": "Flock Cost", "purchase_invoice": "PI-FAKE",
            "items": [
                {"item_code": "Feed", "qty": 8, "amount": 80, "flock": a.name},
                {"item_code": "Feed", "qty": 12, "amount": 120, "flock": b.name},
            ],
        }).insert()
        self.assertEqual(a.total_cost(), 80.0)
        self.assertEqual(b.total_cost(), 120.0)

    def test_cost_per_bird_zero_when_all_dead(self):
        a = self._flock("2026-10-28")
        frappe.get_doc({"doctype": "Mortality", "flock": a.name, "qty": 500}).insert()
        frappe.get_doc({
            "doctype": "Flock Cost", "purchase_invoice": "PI-FAKE",
            "items": [{"item_code": "Feed", "qty": 8, "amount": 80, "flock": a.name}],
        }).insert()
        self.assertEqual(a.cost_per_bird(), 0.0)

    def test_duplicate_purchase_invoice_is_rejected(self):
        base = {"doctype": "Flock Cost", "purchase_invoice": "PI-FAKE",
                "items": [{"item_code": "Feed", "qty": 8, "amount": 80, "flock": self._flock("2026-10-28").name}]}
        frappe.get_doc(base).insert()
        with self.assertRaises(frappe.exceptions.DuplicateEntryError):
            frappe.get_doc(base).insert()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `bench run-tests --app frappe_livestock --module frappe_livestock.api.test_allocation`
Expected: FAIL

- [ ] **Step 3: Implement Flock Cost + Item, `allocation.py`, and Flock cost methods**

`split_purchase_to_flocks` looks up the existing `Flock Cost` by `purchase_invoice` (unique — add a `unique` constraint on `purchase_invoice`); if present, clear and rebuild `items`; else create. Derive `amount = invoice line rate × qty` (fetch the PI item rates; throw if the item isn't on the invoice). `Flock.total_cost()` sums `amount` across `Flock Cost Item` where `flock == self.name`; `cost_per_bird()` guards divide-by-zero.

- [ ] **Step 4: Run test to verify it passes**

Run: `bench run-tests --app frappe_livestock --module frappe_livestock.api.test_allocation`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add frappe_livestock/frappe_livestock/frappe_livestock/doctype/flock_cost frappe_livestock/frappe_livestock/frappe_livestock/doctype/flock_cost_item frappe_livestock/api/allocation.py frappe_livestock/frappe_livestock/frappe_livestock/doctype/flock/flock.py
git commit -m "feat: Flock Cost allocation and cost-per-bird computation"
```

---

### Task 8: Sale allocation (FIFO to ready flocks) → birds_sold & remaining

**Files:**
- Create: `frappe_livestock/api/sales.py`
- Modify: `frappe_livestock/hooks.py` (add `doc_events`)
- Test: `frappe_livestock/api/test_sales.py`

**Interfaces:**
- Consumes: `Flock` (Task 3), `Livestock Type.finished_item` (Task 1).
- Produces: `frappe_livestock.api.sales.allocate_sales_to_ready_flocks(doc=None, method=None) -> dict` (hook signature — Frappe calls it positionally on Sales Invoice submit with `(doc, method)`. Amended by ruling R15: when `doc` is None this is an explicit no-op returning `{"allocated": 0, "unallocated": 0}` — there is intentionally NO "all unallocated submitted invoices" sweep; that idea needs an allocation ledger and is parked for phase 2). When `doc` is a Sales Invoice (document or name), for each line whose `item_code` equals a `Livestock Type.finished_item`, sum the qty per type; allocate that qty to flocks of that type with `status == "Ready"`, oldest `start_date` first, incrementing `birds_sold` — never past `surviving_birds - birds_sold` (clamp at ceiling; a ≤0 ceiling allocates 0; return the unallocated shortfall in the result). Allocation-path flock reads/writes are permission-elevated (R16: `ignore_permissions` reads, `frappe.db.set_value` for the counter, `update_modified=False`) so a non-admin shop user's submit works. Hook: `"Sales Invoice": {"on_submit": "frappe_livestock.api.sales.allocate_sales_to_ready_flocks"}`.
- Produces internal test seam: `allocate_sales_to_ready_flocks_for_type(flock_type, qty)` performing the same FIFO/clamp for one type, returning `{"allocated", "unallocated"}`.

- [ ] **Step 1: Write the failing test** (`test_sales.py`)

```python
import frappe
from frappe.tests import IntegrationTestCase
from frappe_livestock.api.sales import allocate_sales_to_ready_flocks

class TestSaleAllocation(IntegrationTestCase):
    def _ready_flock(self, date, placed=500, sold=0):
        return frappe.get_doc({
            "doctype": "Flock", "livestock_type": "Broiler", "start_date": date,
            "quantity_placed": placed, "status": "Ready", "birds_sold": sold,
        }).insert()

    def test_sales_increment_birds_sold_on_oldest_ready(self):
        older = self._ready_flock("2026-10-28"); newer = self._ready_flock("2026-11-14")
        # allocate 300 finished-bird units directly (the invoice path is wired in the hook)
        result = frappe.call("frappe_livestock.api.sales.allocate_sales_to_ready_flocks_for_type", flock_type="Broiler", qty=300)
        older.reload(); newer.reload()
        self.assertEqual(older.birds_sold, 300)
        self.assertEqual(newer.birds_sold, 0)
        self.assertEqual(older.remaining_birds(), 200)

    def test_over_sale_clamps_at_surviving(self):
        flock = self._ready_flock("2026-10-28", placed=100)
        result = frappe.call("frappe_livestock.api.sales.allocate_sales_to_ready_flocks_for_type", flock_type="Broiler", qty=150)
        flock.reload()
        self.assertEqual(flock.birds_sold, 100)
        self.assertGreater(result["unallocated"], 0)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `bench run-tests --app frappe_livestock --module frappe_livestock.api.test_sales`
Expected: FAIL

- [ ] **Step 3: Implement `api/sales.py` + hook**

Expose an internal `allocate_sales_to_ready_flocks_for_type(flock_type, qty)` (the test seam) that does the FIFO-by-`start_date`, clamp-at-`surviving_birds` allocation, returning `{"allocated", "unallocated"}`. `allocate_sales_to_ready_flocks(doc=None, method=None)` gets the hook calling convention and NO-OPs when `doc is None` (R15 — no sweep). Add the `doc_events` hook.

- [ ] **Step 4: Run test to verify it passes**

Run: `bench run-tests --app frappe_livestock --module frappe_livestock.api.test_sales`
Expected: PASS (2 tests)

- [ ] **Step 5: Commit**

```bash
git add frappe_livestock/api/sales.py frappe_livestock/hooks.py
git commit -m "feat: FIFO sale allocation to ready flocks on Sales Invoice submit"
```

---

### Task 9: Flock summary API + capture UX (active-flock default, dashboard)

**Files:**
- Create: `frappe_livestock/api/flock.py`
- Create: `frappe_livestock/public/js/mortality.js` (client script)
- Create: `frappe_livestock/public/js/feed_event.js` (client script)
- Create: `frappe_livestock/page/flock_dashboard/flock_dashboard.json`
- Create: `frappe_livestock/page/flock_dashboard/flock_dashboard.js`
- Modify: `frappe_livestock/hooks.py` (register `doctype_js`, page)
- Test: `frappe_livestock/api/test_flock.py`

**Interfaces:**
- Consumes: `Flock` controller methods (Task 3/4/7/8), `get_active_flocks` (Task 7).
- Produces: `frappe_livestock.api.flock.get_flock_summary(flock) -> dict` returning `{name, livestock_type, start_date, age_days, stage, expected_ready_date, quantity_placed, mortalities_total, surviving_birds, remaining_birds, birds_sold, total_cost, cost_per_bird, status}`. Client scripts default the `flock` field to the most-recent non-closed flock and prefill `date` to today. `flock_dashboard` page renders the summary for the selected flock.

- [ ] **Step 1: Write the failing test** (`test_flock.py`)

```python
import frappe
from frappe.tests import IntegrationTestCase
from frappe_livestock.api.flock import get_flock_summary

class TestFlockSummary(IntegrationTestCase):
    def test_summary_includes_all_computed_fields(self):
        flock = frappe.get_doc({
            "doctype": "Flock", "livestock_type": "Broiler",
            "start_date": frappe.utils.today(), "quantity_placed": 500,
        }).insert()
        s = get_flock_summary(flock.name)
        for key in ["age_days", "stage", "expected_ready_date", "surviving_birds",
                    "remaining_birds", "total_cost", "cost_per_bird", "status"]:
            self.assertIn(key, s)
        self.assertEqual(s["surviving_birds"], 500)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `bench run-tests --app frappe_livestock --module frappe_livestock.api.test_flock`
Expected: FAIL

- [ ] **Step 3: Implement `api/flock.py`, client scripts, dashboard page, and hooks**

`get_flock_summary` delegates to the `Flock` controller methods. Client scripts use `frappe.call("frappe_livestock.api.allocation.get_active_flocks")` to default `flock`. Register `doctype_js` for Mortality and Feed Event, and the `flock_dashboard` page in `hooks.py`.

- [ ] **Step 4: Run test to verify it passes**

Run: `bench run-tests --app frappe_livestock --module frappe_livestock.api.test_flock`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add frappe_livestock/api/flock.py frappe_livestock/frappe_livestock/public frappe_livestock/frappe_livestock/page frappe_livestock/hooks.py
git commit -m "feat: flock summary API, active-flock defaulting, and dashboard page"
```

---

## Self-review notes

- **Spec coverage:** all phase-1 DocTypes (Livestock Type, Stage, Housing, Region, Flock, Mortality, Feed Event, Flock Cost, Item) and both capture surfaces (phone forms via lean Mortality/Feed Event + client scripts; desk via full purchase + allocation) are covered. Sale allocation and simple cost-per-bird are covered. No scheduler by design (compute-on-read). Movement, vaccine schedules, age-weighted costing, and profit statements are phase 2/3 and intentionally out of scope.
- **Proportion:** plan length is commensurate with the spec; test snippets carry assertions only, bodies are left to the implementer.
- **Type consistency:** `Flock.age_days/stage_name/expected_ready_date/mortalities_total/surviving_birds/remaining_birds/total_cost/cost_per_bird` are named identically in Tasks 3/4/7/8/9; `get_stage_for_age` and `split_purchase_to_flocks` are referenced only as defined.

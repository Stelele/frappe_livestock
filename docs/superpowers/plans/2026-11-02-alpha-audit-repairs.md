# Alpha Audit Repairs Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix all findings from the 5-agent alpha audit (2026-11-02) — design-system conformance, navigation, daily-workflow usability, form design, and client-code quality — plus build the four missing primitives (Weight, Livestock Settings, daily scheduler, movement audit).

**Architecture:** Backend-first (schema, validations, new APIs), then rewrite the two custom Pages onto the Frappe Page/dialog design system, then form JS, then Workspace. Every destructive or expensive action gets an explicit, confirmed save (ADR 0018); every API an operator may call is callable by the new non-admin roles.

**Tech Stack:** Frappe v16 + ERPNext v16, Python 3, deskmate JS (Frappe UI libs only — no new JS deps, no new CSS files).

**Spec:** `docs/superpowers/specs/2026-10-28-livestock-orchestrator-design.md` (original design) and the 2026-11-02 audit reports (in session). User decisions ratified in brainstorm: **single "feed consumed" record** (Open/Finish dropped), **Livestock Manager + Livestock Operator roles**, **build missing primitives**, **batch naming stays `{type} {date}` with collision suffix**.

## Global Constraints

- Frappe v16 only (`before_install` already enforces). Bench root: `/home/gift/Documents/code-projects/frappe/v16`.
- Python package tree: `frappe_livestock/frappe_livestock/` (app root is the repo root).
- Work on a feature branch; default branch is protected. Commits per task.
- Explicit save over autosave; destructive rewrites need a confirm dialog (ADR 0018).
- Restraint in the UI: remove a control rather than add a competing second one (ADR 0017).
- JS role checks are never authorization; page/doctype permissions are (board ADR).
- All new whitelisted endpoints live in `frappe_livestock/api/*.py`; `frappe.call` paths include the `api` segment (verified working; keep the pattern).
- Tests run: `cd /home/gift/Documents/code-projects/frappe/v16 && bench run-tests --app frappe_livestock` (or `--site <site> -k <keyword>` for one test).

## Review Focus

Failure modes the audit implies but no single task's tests fully exercise. Each is pinned to its owning task.

1. **Double-click on a money action duplicates the whole PO→PR→PI→Payment chain.** Every button that submits a chain must be unclickable until the call settles. Pinned: Task 11/13 manual-verify steps (UI); Task 7 pins the transactional side (`force` guard test).
2. **Mortality qty > surviving flock silently poisons `surviving/remaining/cost_per_head`.** Owner expects a clear throw. Pinned: Task 5 test.
3. **Allocation to a Closed batch (or sale from a non-Ready one) silently does nothing.** Owner expects an explicit error or an explicit warning naming the batch. Pinned: Task 7 and Task 9 tests.
4. **A non-System-Manager farm worker records a Feed Event and then hits "Not Permitted" somewhere downstream.** Owner expects Operator role paths to work end to end without error walls. Pinned: Task 2 PIT test; Task 16 manual verify.
5. **Stale numbers shown as current (dashboard/table refreshed only on load).** Owner expects the surface to clear-and-refetch on every visit. Pinned: Task 14 manual verify (`on_page_show` refresh).

---

### Task 1: Branch and baseline

**Files:** none.

- [ ] **Step 1: Ensure feature branch** (never the default branch): `git switch -c fix/alpha-audit-repairs` (or reuse if it exists).
- [ ] **Step 2: Baseline test run** — `bench run-tests --app frappe_livestock`; record pass/fail. Fixing begins from a green (or known-green) baseline.

### Task 2: Roles — Livestock Manager + Livestock Operator

**Files:**
- Modify: `frappe_livestock/installer.py`
- Modify: `.../frappe_livestock/doctype/{livestock_type,livestock_batch,feed_event,mortality,batch_cost,batch_sale,housing,housing_region,livestock_stage,batch_cost_item,batch_sale_item}/*.json` (permissions arrays)
- Modify: `.../page/batch_dashboard/batch_dashboard.json`, `.../page/purchase_entry/purchase_entry.json` (roles)
- Modify: `.../api/reporting.py` (`DASHBOARD_ROLES`)
- Test: `frappe_livestock/api/test_roles.py` (new)

**Interfaces:**
- Produces: `installer.LIVESTOCK_MANAGER_ROLE = "Livestock Manager"`, `installer.LIVESTOCK_OPERATOR_ROLE = "Livestock Operator"`, and `installer.ensure_livestock_roles()` (creates both roles idempotently; Manager desk_access 1, Operator desk_access 1; called from `after_install` and `after_migrate`).
- Permission shape: **Livestock Manager** = read/create/write/report/email on all 11 app doctypes + both Pages + `reporting.DASHBOARD_ROLES` gains it. **Livestock Operator** = read/create/write/report on `Feed Event`, `Mortality` (+ read on `Livestock Batch`, `Livestock Type`, `Housing`); **no delete**. Settings/Item/etc. stay admin-only.
- Operator must NOT get `purchase-entry` page access or purchase APIs; mutating purchase/allocation endpoints keep accepting anyone with doctype write perms today (ERPNext gates the underlying invoices) — document this in the endpoint docstring only, no JS gates.

- [ ] **Step 1: Failing PIT test** (`test_roles.py`): create a temp user with only Operator role → `frappe.get_doc({"doctype": "Feed Event", ...batch...})` insert via `frappe.set_user` succeeds; `Mortality` insert succeeds; `frappe.get_list("Livestock Batch")` returns rows; delete fails with `PermissionError`; and with only Manager role, `reporting.portfolio()` via `frappe.set_user` does not raise (old `frappe.only_for` now accepts Manager).
- [ ] **Step 2: Run** — `bench run-tests --app frappe_livestock -k roles` → FAIL.
- [ ] **Step 3: Implement** — JSON permission entries for both roles per shapes above (copy entries into each doctype JSON); page JSONs gain Manager (batch-dashboard also "Livestock Dashboard"); `reporting.DASHBOARD_ROLES = ("System Manager", "Livestock Dashboard", "Livestock Manager")`; add `ensure_livestock_roles()` to installer and call it where `ensure_reporting_permissions` is called.
- [ ] **Step 4: Run** — PASS. **Step 5: Commit** `feat: livestock Manager + Operator roles across doctypes, pages, reporting gate`.

### Task 3: Livestock Batch hardening (naming, guards, form metadata)

**Files:**
- Modify: `.../doctype/livestock_batch/livestock_batch.py` (autoname, validate)
- Modify: `.../doctype/livestock_batch/livestock_batch.json`
- Modify tests: `.../doctype/livestock_batch/test_livestock_batch.py` (+ app test fixtures that assume exact names, see below)

**Interfaces:**
- Produces: `LivestockBatch.autoname` — name `{livestock_type} {start_date}`, and when taken, `{livestock_type} {start_date} 2`, `3`, … (suffix loop keeps existing single-batch names stable — all current tests keep producing `Broiler <date>` for unique dates).
- `validate` additions: (a) server-side `sold` guard — if `sold` differs from the DB value raise, phrase: "Sold is maintained automatically"; the sales hook writes via `frappe.db.set_value` (bypasses validate) so it is unaffected; (b) duplicate name never reached (autoname handles); (c) `housing` link loads before this in Task 6, no capacity logic here.
- JSON: `track_changes: 1`, `autoname`-independent `title_field` stays name; add `search_fields: "livestock_type,housing,status"`; reorder `fields[]` to match `field_order`; `sold` gets `read_only: 1, no_copy: 1, default: 0` (Int, not string); `stocking_purchase_invoice` gets `description: "Leave empty and use Buy stock, or link an already-submitted stocking invoice."` and `no_copy: 1`; add two Section Breaks "Placement" (type→housing) and "Stock & Sales" (status→invoice→sold) so `stocking_purchase_invoice`/`sold` sit in a collapsed section; start_date gets `default: "Today"`; quantity_placed gets `description: "Head count placed on start date, before mortality."` and `set_only_once: 1`.

- [ ] **Step 1: Failing test** in `test_livestock_batch.py`: `test_autoname_disambiguates_same_day_batches` — insert two Broiler batches same date; names `Broiler 2026-10-28` and `Broiler 2026-10-28 2`; and `test_sold_is_not_hand_editable` — save with `sold=3` changed from DB → `ValidationError` matching "maintained automatically".
- [ ] **Step 2: Run** `-k auto` and `-k sold` → FAIL. **Step 3: Implement** autoname suffix loop + validate guard + JSON edits. **Step 4: Run full app tests** (autoname touches every fixture) → PASS. **Step 5: Commit** `feat: batch autoname disambiguation, sold guard, form metadata`.

### Task 4: Feed Event — single "feed consumed" record

**Files:**
- Modify: `.../doctype/feed_event/feed_event.json`, `feed_event.py`
- Modify: `.../api/reporting.py` (`feed_timeline` filter)
- Create: `frappe_livestock/frappe_livestock/patches/fold_feed_events.py` + `frappe_livestock/patches.txt`
- Modify: `.../doctype/feed_event/test_feed_event.py`

> User decision: one record per feed consumption; `Open`/`Finish` semantics dropped.

**Interfaces:**
- Produces: Feed Event = `batch` (Link, reqd), `feeding_date` (Date, reqd, default Today — field renamed from `date`), `feed_item` (Link Item, reqd — label stays "Feed Item"), `qty` (Float, reqd, `precision: "2"`, label "Qty", description "In stock UOM (bags or kg) — what was consumed."), `note` (Small Text). Field `event` **removed**; `date` column renamed in DB to `feeding_date` via JSON column_name? No — swapping fieldname changes the DB column only on docfield sync; use patch to copy `date`→`feeding_date` before dropping, keep it simple: field renamed **in fieldname only if** — pin: fieldname stays `date`, **label** becomes "Feeding Date"; avoid migration cost. `autoname: "format:FEED-.YYYY.-.MM.-.#####"` → pin `naming_series`-free: `autoname: "format:FEED-{batch}-{date}"` NOT valid — pin: keep hash autoname but set `search_fields: "batch,feed_item"`, `title_field` none, and let Task 17's list views carry identity. Final pin: **no autoname change** (hash names acceptable alpha); `track_changes: 1`.
- `feed_timeline` loses the `event` filter (returns all rows, same fields minus `event`).
- Patch `fold_feed_events.py`: for each `("batch","feed_item","date")` group containing Open/Finish rows, replace the group with one row `qty = max(sum(Finish), license sum(Open))` — precisely: when both exist use the **Final qty of the last Finish row**; when only Open rows exist keep one row with their qty sum. Insert into `patches.txt` after listing.

- [ ] **Step 1: Failing test** in `test_feed_event.py`: insert without `event` (field gone) saves; missing `date`/`qty` raises; `feed_timeline` returns row for plain consumed event.
- [ ] **Step 2: Run** `-k feed` → FAIL. **Step 3: Implement** JSON/py/patch changes. **Step 4: Run** → PASS. **Step 5: Commit** `feat: feed event = one consumed record; drop Open/Finish`.

### Task 5: Mortality hardening

**Files:** Modify `.../doctype/mortality/mortality.json`, `mortality.py`; Modify `test_mortality`-adjacent tests only if they rely on >flock qty (none known today).

**Interfaces:**
- Produces: `Mortality.validate`: (existing ≥1 check) + cumulative check — `sum(qty for this batch incl. self) <= batch.quantity_placed`, else `frappe.throw("Deaths cannot exceed the {0} birds placed on batch {1}")`; on insert only, stamp `age_days` (Int, read-only) and `stage` (Data, read-only) from the batch (reuse `livestock_batch.LivestockBatch` helpers).
- JSON: `date` gets `reqd: 1`; `qty` label → "Birds Lost"; `reason` becomes **Select** `Disease\nHeat\nPredator\nOther` + new `reason_details` (Small Text, `depends_on: eval:doc.reason=='Other'`); mandatory `track_changes: 1`; permissions per Task 2.

- [ ] **Step 1: Failing test** (new class in existing mortality test file or `test_mortality.py`): batch placed=5 → insert Mortality qty 3 (ok, surviving 2); second insert qty 3 → `ValidationError` "cannot exceed"; `age_days`/`stage` populated on save. **Step 2: Run FAIL.** **Step 3: Implement.** **Step 4: Run PASS.** **Step 5: Commit** `feat: mortality ceiling, reasons, age/stage stamps`.

### Task 6: Housing polish + status maintenance at stocking

**Files:** Modify `.../doctype/housing/housing.json`, `housing.py`; Modify `.../doctype/housing/test_housing.py`; backend hook target in Task 7.

**Interfaces:**
- Produces: JSON: `housing_type` gets `default: "General"`, `reqd: 1`; `capacity` gets `default: 0`, `description: "Maximum head count (sum of regions should not exceed this)."`; `status` options reordered `Ready\nResting\nOccupied`; `last_used_date`, `last_cleaned_date` get `read_only: 1` and description "Set automatically."; sections: "Details" (name/type/status/capacity) + collapsed "Maintenance" (the two dates) + Regions last; `track_changes: 1`; `in_standard_filter` on type+status; `in_list_view` on type/capacity/status.
- Produces: `Housing.mark_occupied(date=None)` and `Housing.mark_released(date=None, cleaned=False)` instance methods (set status accordingly; stamp `last_used_date` on occupied; `last_cleaned_date` only when `cleaned`).

- [ ] **Step 1: Failing test**: `mark_occupied()` → status Occupied, `last_used_date` = today, read-only fields bypassed via direct method (method writes own doc); `mark_released()` → Ready. **Step 2: FAIL.** **Step 3: Implement.** **Step 4: PASS.** **Step 5: Commit** `feat: housing metadata + status maintenance methods`.

### Task 7: Guardrails in stocking & allocation (the integrity core)

**Files:**
- Modify: `frappe_livestock/api/purchase.py` (no signature change)
- Modify: `frappe_livestock/api/stocking.py`
- Modify: `frappe_livestock/api/allocation.py`
- Modify tests: `frappe_livestock/api/test_stocking.py`, `test_allocation.py`, `test_purchase.py`

**Interfaces:**
- `split_purchase_to_batches(purchase_invoice, allocations, force=None)` — new json-parsed bool `force`. When an existing Batch Cost's new rows differ from its stored rows AND `force` is falsy → `frappe.throw("Batch Cost {name} already exists with different rows. Re-run with overwrite confirmed.")`. When `force` truthy → upsert (current behavior) **and** append a `frappe.get_doc({"doctype": "Comment", "comment_type": "Comment", ...}).insert()` on the Batch Cost naming old vs new row counts. Identical rows upsert silently (idempotent).
- `link_stocking_purchase(batch, purchase_invoice, force=None)` and `_allocate_to_batch(batch_name, purchase_invoice, force=None)` pass through; `create_stocking_purchase(...)` always passes `force=None` (fresh chain, safe).
- `split_purchase_to_batches` also raises when a target batch's `status == "Closed"`: throw `"Batch {name} is closed"`; when target housing missing → raise from `create_stocking_purchase` only: `frappe.throw("Set a Housing on batch {batch} before buying stock.")` and validate `quantity_placed <= housing.capacity` (Housing `capacity == 0` means unlimited — skip check).
- On successful first stocking allocation: `housing.mark_occupied()` (Task 6 method).

- [ ] **Step 1: Failing tests** in `test_allocation.py`: `test_split_rejects_closed_batch`; `test_split_requires_force_for_conflicting_overwrite` (upsert same rows silently idempotent; different rows w/o force → throw; with force → save + 1 Comment); in `test_stocking.py`: `test_stocking_requires_housing` (throw when housing empty), `test_stocking_checks_capacity` (placed > capacity → throw), `test_stocking_marks_housing_occupied`. **Step 2: FAIL.** **Step 3: Implement.** **Step 4: full test run** (allocation semantics touch other suites) **PASS.** **Step 5: Commit** `feat: allocation/stocking guardrails with audit trail`.

### Task 8: `get_active_batches` without N+1

**Files:** Modify `frappe_livestock/api/allocation.py` (`get_active_batches`); test in `test_allocation.py`.

**Interfaces:** Produces same return shape; computed with one SQL: `sum(mortality.qty)`, `sold`, `quantity_placed`–derived `remaining` for all non-Closed batches in a single query + one grouped Mortality query. `remaining = quantity_placed - mortalities_total - sold` (SQL only, no `get_doc` loop).

- [ ] **Step 1: failing test**: `test_get_active_batches_remaining_matches_controller` — batch with mortality + sale hook increment; API `remaining` equals `get_doc(...).remaining()`. **Step 2: FAIL** (may pass numerically; pin assertion that output keys are same shape). **Step 3: implement SQL.** **Step 4: PASS.** **Step 5: Commit** `perf: get_active_batches single-query computation`.

### Task 9: Sales that tell the truth

**Files:**
- Modify: `frappe_livestock/api/sales.py`
- Test: `frappe_livestock/api/test_sales.py`

**Interfaces:**
- Produces: `create_batch_sales_invoice(batch, qty, customer, rate, mode_of_payment="Cash")` (whitelisted) — creates + submits a Sales Invoice of `qty` × the batch type's `finished_item`, limited to the batch's `remaining()` (throw `frappe.throw(f"Only {remaining} head remain on batch {batch}")` if over), then calls `_allocate_invoice_items` on it; returns `{"sales_invoice", "allocated", "unallocated: 0"}` (must be 0 or it throws).
- Produces: in `allocate_sales_to_ready_batches_for_type`, when `unallocated > 0` and this was a hook (doc submit), `frappe.msgprint({"message": f"{unallocated} finished birds of type {batch_type} were allocated to NO batch (no Ready batch with remaining head).', "indicator": "orange"})` — hook context only, guarded to running in a request (`frappe.request is not None`).

- [ ] **Step 1: Failing tests**: `test_create_batch_sales_invoice_allocates_and_reports` (Ready batch, remaining 500; invoice qty 100; `sold` 100); `test_create_batch_sales_invoice_caps_at_remaining`; `test_shortfall_msgprint_on_provisional_invoice` (simulate a submit hook call with a batch not Ready → the msgprint path is exercised by `frappe.request is not None` inside the request context — test via `frappe.get_doc(...).submit()` inside a fake request set).
- [ ] **Step 2: FAIL.** **Step 3: Implement.** **Step 4: PASS.** **Step 5: Commit** `feat: explicit batch sales + shortfall surfacing`.

### Task 10: Livestock Settings (Single) + purchase pre-flight

**Files:**
- Create doctype **Livestock Settings** (is_standard single): `frappe_livestock/frappe_livestock/doctype/livestock_settings/{__init__.py,livestock_settings.json,livestock_settings.py,test_livestock_settings.py}`
- Create: `frappe_livestock/api/settings.py`
- Modify: `frappe_livestock/installer.py` (seed role access re: Settings is admin-only, no role grant needed)

**Interfaces:**
- Settings fields (Single): `mode_of_payment` (Link Mode of Payment, default "Cash"), `warehouse` (Link Warehouse), `housing_capacity_soft_penalty`? — pin ONLY: `mode_of_payment` + `default_warehouse` (Link). Admin edit surface exists in Task 17 Workspace shortcut or form; skip new UI.
- Produces: `api/settings.get_purchase_context()` (whitelisted) → `{"company": <user default>, "warehouse": <settings default_warehouse or the company's single leaf warehouse or None>, "mode_of_payment": <settings mode_of_payment or None>, "warnings": [<stash of missing-config strings: no company default, no valid Mode of Payment "Cash", no cash account>]}`. `warnings` entries are the pre-flight the UI shows `frappe.msgprint(..., indicator:"orange")` BEFORE the user types everything.
- This is the shared source of truth replacing per-file `"Cash"` defaults (three places) and the silent `company` grabs.

- [ ] **Step 1: Failing test** in new `api/test_settings.py`: with Settings unset + single-company site lacking "Cash" MoP (simulate by `frappe.db.delete("Mode of Payment","Cash")`? no — instead just set a valid settings doc): returns warehouse from settings; `warnings` non-empty when `company` user default is unset (set_user default "" via `frappe.db.set_default`? pin: run with `frappe.defaults.set_default("company", user, None)` cleanup) — assertion: keys present and warehouse falls back sensibly. **Step 2: FAIL.** **Step 3: Implement** doctype files + `get_purchase_context` (wire the `frappe.defaults.get_user_default("company")` read here). **Step 4: PASS.** **Step 5: Commit** `feat: livestock settings + purchase pre-flight context`.

### Task 11: Purchase entry Page — design-system rewrite

**Files:**
- Modify: `frappe_livestock/public/js/purchase_entry.js` (full rewrite, same 244-line budget or less)
- Modify: `frappe_livestock/frappe_livestock/page/purchase_entry/purchase_entry.js` (keeps shell; delete the duplicate handler — the shell becomes a no-op comment, public JS stays the sole `on_page_load`; same in Task 14 for dashboard)
- No HTML-in-JS beyond Frappe classes; no CSS files.

**Interfaces:**
- Consumes: Task 10 `get_purchase_context`; Task 7 `force` param on split; Task 9 nothing.
- Structure (pin): `page.set_primary_action(__("Allocate"))` for the allocate hook; `page.add_inner_button` for "Add row"/"Load invoice lines"/buy-group primary (`Create purchase` as an inner button *with primary styling* via `frappe.page` head is acceptable per codebase precedent — pin: keep two FieldGroup heads mounted in `frappe-card` sections, one per workflow: "Buy" and "Allocate to batches", with `section headings` via `widget-head` class only (no raw h4); **no `page.add_field`** (v16 layout gap documented in current code) — keep body FieldGroups but inside `frappe-card` wrappers.
- ALL row values read via the stored FieldGroup handles (`item_rows`/`allocate_rows` are now actually read with `fg.get_values()`); `qty` fieldtype Float on buy rows; company read inside handlers via `get_purchase_context`, not cached at open.
- `create_full_purchase` click: disable button + `frappe.freeze()`; re-enable in `.always()`.
- `allocate` click: collect; when the target Batch Cost exists with different rows the server throws per Task 7 — catch, then `frappe.confirm(__("Overwrite existing Batch Cost {0}?", [invoice]), () => retry with force=1)`. Success message uses `made.batch_cost` (fixes the `made.name` bug) and renders as `frappe.msgprint({title, indicator:"green", message: __("Batch Cost {0} — cost per head is live on the dashboard.", [made.batch_cost])}`.
- `load_invoice_lines(invoice)` takes the invoice as a parameter (fixes the set_input→read race).
- Auto-prefill batch on allocate rows: default to the single active batch when `get_active_batches()` returns exactly one (else leave empty).

- [ ] **Steps:** (no JS test framework) 1) rewrite; 2) `grep -c "input\[data-fieldname" public/js/purchase_entry.js` → 0; 3) bench start + manual verify script (enumerate in commit body): a) open /app/purchase-entry — sections render as cards in theme (toggle dark mode, no broken layouts); b) create a purchase — button shows disabled state during the call; double-click fast → exactly one PB chain (verify by list count); c) allocate once → orange overflow confirm appears only when rows differ on a re-run; d) success msgprint names the actual Batch Cost; 4) commit `refactor: purchase entry on frappe page primitives + submit guards`.

### Task 12: Batch ops data API (one call feeds the dashboard)

**Files:** Modify `frappe_livestock/api/reporting.py`; test `frappe_livestock/api/test_reporting.py`.

**Interfaces:**
- Produces: `api.reporting.get_ops_snapshot(batch)` (whitelisted, `_gate()` as-is). Returns one dict flat-merged from:
  - `get_batch_summary` fields (as today),
  - `mortality_pct: (mortalities_total / quantity_placed)`,
  - `feed_consumed_today: float` (Feed Event rows where date == today), `feed_consumed_total`, `feed_bought_total` (Batch Cost rows for non-stocking items),
  - `fcr: feed_kg_total / weight_gain_total` — **only when Weight rows exist** (Task 15 Feed-in-kg assumption documented; numeric `null` otherwise),
  - `last_weight_kg`, `last_weight_date` (Weight, Task 15),
  - `last_feed_date`, `last_mortality_date` (freshness),
  - `revenue`, `profit`, `margin` (same math as `_batch_rows` for this batch),
  - `days_to_ready`.
- All read-only.

- [ ] **Step 1: Failing test** in `test_reporting.py`: seeded batch (type with stages; mortality; feed rows; weight rows) → snapshot asserts each of the keys above numerically (e.g. mortality_pct 0.05 for 25/500). **Step 2: FAIL.** **Step 3: Implement** (reuse `batch.total_cost()` style helpers; no new SQL duplicated from `_batch_rows`). **Step 4: PASS.** **Step 5: Commit** `feat: single-call batch ops snapshot for dashboard`.

### Task 13: Weight DocType (new) + movement audit

**Files:**
- Create: `frappe_livestock/frappe_livestock/doctype/livestock_weight/{__init__.py,livestock_weight.json,livestock_weight.py,test_livestock_weight.py}` (naming pin: `Livestock Weight`, module Frappe Livestock, naming `format:LW-.#####`)
- Modify: `frappe_livestock/frappe_livestock/doctype/livestock_batch/livestock_batch.py`

**Interfaces:**
- `Livestock Weight` fields: `batch` (Link, reqd), `date` (Date, reqd, default Today), `average_weight_kg` (Float, reqd, precision 3, label "Avg Weight (kg)"), `sample_size` (Int, label "Heads Weighed", default 0), `notes` (Small Text). Permissions = Task 2 shape (Operator create/write/read; no delete). `track_changes: 1`.
- Controller validate: `average_weight_kg > 0`; `sample_size >= 0`.
- Movement audit pin: in `LivestockBatch.on_update` (Task 3 file), when `housing` changed since the pre-write value, append a Comment: `"Moved from {old} to {new} on {today}"` (old = `frappe.db.get_value(...,"housing")` captured in the existing `_stocking_pi_before` pattern — extend that captured tuple). No separate DocType this phase (spec phases Movement as its own doc in Phase 2; the Comment satisfies traceability today).

- [ ] **Step 1: Failing test** for `test_livestock_weight.py`: insert with `average_weight_kg=1.6, sample_size=20` saves; `=0` throws; batch method `latest_weight()` (new public method on LivestockBatch returning `(date, kg)` or `None`) returns newest by date. **Step 2: FAIL.** **Step 3: Implement** doctype + `latest_weight()` + movement Comment. **Step 4: PASS.** **Step 5: Commit** `feat: Livestock Weight doctype + housing-movement comments`.

### Task 14: Batch dashboard rebuild

**Files:**
- Modify: `frappe_livestock/public/js/batch_dashboard.js` (rewrite; delete `on_page_load` from the page-file shell same as Task 11)
- Modify: `frappe_livestock/frappe_livestock/page/batch_dashboard/batch_dashboard.json` — page roles stay Task 2 set.

**Interfaces:**
- Consumes: Task 12 `get_ops_snapshot` (single call), Task 8 `get_active_batches`.
- Layout pin (ADR 0017): `page.body.empty()` first; then **4 headline cards** via Frappe classes: `frappe-card` + big number = Status (frappe `indicator-pill`), Surviving, Cost per Head, Mortality %; then a collapsed "Details" `<details class="frappe-card">` for type/date/age/stage/placed/sold/remaining/expected-ready; then "Actions" row of inner buttons: "Record Feed" → `frappe.new_doc("Feed Event")` seeded with `frappe.route_options = {batch: current}`; same pattern for "Record Mortality", "Weigh", "Sell birds" (Task 9 dialog via a small `frappe.ui.Dialog` calling `create_batch_sales_invoice`); "Open Batch" → `frappe.set_route("Form", "Livestock Batch", name)`.
- Race fixes: picker onchange guard `if (picker.get_value("batch") === current) return;`; auto-default `.then` never writes when the user already set a value; render clears `$summary` to a muted "Loading…" row before the fetch; `.catch` → `$summary` cleared + `frappe.msgprint`.
- `on_page_show` re-fetch: assign `frappe.pages["batch-dashboard"].on_page_show = () => load(get_current_batch())` (uses the *fresh* state, never stale cache).
- Freshness render: `last_feed_date`, `last_mortality_date` displayed as relative dates (`frappe.utils.pretty_date`) in the details area, orange when > 1 day old on Active batches.

- [ ] **Steps:** 1) rewrite; 2) `grep -c "table table-bordered" public/js/batch_dashboard.js` → 0; 3) manual: pick batch → cards show; numbers change after recording feed/mortality in another tab and returning to the dashboard (no reload); no second picker stacked after navigating away and back; 4) commit `refactor: batch dashboard cards + quick actions + freshness + race guards`.

### Task 15: Shared form JS — feed/mortality/batch/weight forms

**Files:**
- Create: `frappe_livestock/public/js/livestock_forms.js` (one file, both `doctype_js` entries point here)
- Modify: `frappe_livestock/hooks.py` — `doctype_js = {"Mortality": "public/js/livestock_forms.js", "Feed Event": "public/js/livestock_forms.js", "Livestock Weight": "public/js/livestock_forms.js", "Livestock Batch": "public/js/livestock_batch.js"}` (batch keeps its own file)
- Delete: `frappe_livestock/public/js/feed_event.js`, `frappe_livestock/public/js/mortality.js`
- Modify: `frappe_livestock/public/js/livestock_batch.js` (garbled comment lines 1–3 replaced; real intro copy: `__("Buy day-old stock with **Buy stock**, or link an already-submitted stocking Purchase Invoice to set this batch's initial cost.")`; buy dialog gets busy-state on `primary_action` (disable `$wrapper.find(".btn-primary")` + `frappe.freeze()`; `.always()` re-enable); dialog defaults for `mode_of_payment`/`warehouse` come from Task 10 `get_purchase_context` resolved when the dialog opens (not cached at page load); re-link confirm — when `stocking_purchase_invoice` already points somewhere and the dialog's result differs: `frappe.confirm(..., proceed)`; add refresh buttons: "View Dashboard" (`frappe.set_route("batch-dashboard/…", {batch})` — pin `frappe.route_options = {batch: frm.doc.name} frappe.set_route("batch-dashboard")`) when saved, contextless.

**Interfaces (the shared layer):**
- `FormsJS.default_batch(frm, doctype)` — debounced `get_active_batches` call, guarded by `if (frm.doc.batch) return;` both before AND after resolve (the existing guard is checked pre-call only — bug), no overwrite of user input. Feed Event additionally: if the batch is set on resolve, fetch its type's stage-appropriate hint and prefill `feed_item` only when empty, from the batch's last-used feed item (`frappe.db.get_list("Feed Event", {filters: {batch}, limit: 1, order_by: "date desc", fields: ["feed_item"], ...})`) — else leave empty (never a wrong-guess).
- Remaining-heads indicator: after batch resolves set `frm.set_intro`-style read-only field `frm.set_df_property("batch", "description")` is insufficient — pin: `frm.dashboard.add_section` absent in v16; simply `frappe.show_alert({message: __("Batch {0}: {1} birds remain", [batch, remaining]), indicator: "blue"})` once per form load after batch resolves, from Task 8's `remaining` field.
- Both forms load their `batch` Link query filter: `get_query: () => ({filters: [["status","!=","Closed"]]})`.

- [ ] **Steps:** 1) implement; 2) manual verify with Operator role user: New Feed Event → batch prefills to newest active, alert shows remaining; manually pick a different batch → auto-fill does NOT stomp it; same for Mortality and Livestock Weight; new Batch shows real intro (no `<.stocking intro>` token anywhere: `grep -rn "<.stocking" public/js` → 0; `grep -rn "garbled" no-op`); buy dialog on batch: double-submit cannot create two PO chains; 3) commit `refactor: shared feed/mortality/weight form defaults, batch intro copy, dialog guards`.

### Task 16: Scheduler + stage nudges

**Files:**
- Create: `frappe_livestock/frappe_livestock/tasks.py` + test `frappe_livestock/api/test_tasks.py`? pin: tests live in `frappe_livestock/tests/test_tasks.py` if the app has none — create at repo root test dir `frappe_livestock/tests/{__init__.py,test_tasks.py}`.
- Modify: `frappe_livestock/hooks.py` — uncomment `scheduler_events` with only `"daily": ["frappe_livestock.tasks.daily"]`.

**Interfaces:**
- Produces: `tasks.daily()` — for every `Active` batch: (a) if `expected_ready_date() >= today` and status Active → Notification Log (frappe.get_doc({"doctype":"Notification Log","for_user":<each user with Livestock Manager or System Manager role>,"type":"Alert","subject":f"Batch {name} should be marked Ready today"}) ) inserted with `ignore_permissions=True` and only if not already sent today (idempotency guard via Comment/notification dedupe: skip if `frappe.db.exists("Notification Log", {"for_user": u, "subject": subject, "creation": [">=", today_start]})`); (b) if `max(last_feed_date, last_mortality_date)` older than 1 day → same channel, subject `Batch {name}: no entries recorded in {n} days`.
- Scheduler runs at most once daily by Frappe's cron (`daily`), NOT the 4-min `all` tick (house rule).

- [ ] **Step 1: Failing test**: run `daily()` in test context with a ready-dated batch → Notification Log exists for the admin; second run same day → still 1. No-entries batch seeded with one feed event 3 days old → notification exists; fresh batch → none. (Notification channel works in tests; no mail configured = fine.) **Step 2: FAIL.** **Step 3: Implement** + hooks. **Step 4: PASS.** **Step 5: Commit** `feat: daily ready/quiet-batch nudges via scheduler`.

### Task 17: Workspace, shortcuts, app screen

**Files:**
- Create: `frappe_livestock/frappe_livestock/workspace/frappe_livestock/frappe_livestock.json` (standard Workspace JSON, module Frappe Livestock; content blocks: "Shortcuts" / "Masters" / "Cross-links"; label "Livestock")
- Modify: `frappe_livestock/hooks.py` — uncomment `add_to_apps_screen` (drop the `has_permission` line; route `/app/batch-dashboard`).

**Interfaces:**
- Shortcuts (pin): Batch Dashboard (Page), Livestock Purchase (Page), New Livestock Batch, New Feed Event, New Mortality, DocType list shortcuts: Livestock Batch, Batch Cost, Batch Sale, Housing, Livestock Type, Livestock Settings. Workspace is visible to roles: System Manager, Livestock Manager, Livestock Operator (Operator sees shortcuts but Pages still gate per Task 2).
- Child-table doctypes (`istable`) intentionally NOT shortcut'd.

- [ ] **Step 1:** author JSON (npm-style — copy shape from any v16 workspace e.g. `/home/gift/Documents/code-projects/frappe/v16/apps/frappe/frappe/desk/workspace/*` fixtures). [ ] **Step 2: verify** `bench migrate` succeeds and sidebar shows Livestock workspace after refresh with the shortcuts; Apps screen (if `add_to_apps_screen` wired) lists the app. **Step 3: Commit** `feat: workspace, shortcuts, apps screen entry`.

### Task 18: README + full verification

**Files:** Modify `README.md` (roles section + new feed semantics + workspace mention); no code.

- [ ] **Step 1:** README: replace "System-Manager-only by design" section with the role table; document single-record Feed Event; document the suffix batch naming.
- [ ] **Step 2:** Full suite: `bench run-tests --app frappe_livestock` → all pass.
- [ ] **Step 3:** Manual smoke (recorded in the PR description): Day-0 buy-through-allocation on a fresh Operator-visible path; a feed + mortality + weight round trip; seed a short batch sale; dashboard cards match; fresh Studio theme not glitched.
- [ ] **Step 4: Commit** `docs: README for roles, feed semantics, naming` — then push feature branch and open PR (default branch merge needs explicit instruction).

## Self-Review

- Spec coverage → every audit's CRITICAL/HIGH is owned by: Task 2 (roles everywhere), 3–7 (data integrity/naming/guards), 9 (sales truth), 10–11 (purchase flow + defaults), 12–14 (dashboard rebuild), 15 (forms + placeholder copy), 16 (scheduler), 17 (navigation/workspace), 13 (Weight/Movement), 10 (Settings). MEDIUM/LOW UI polish is folded into the rebuilds (sections, labels, indicator choices) — no task exists without a deliverable.
- Step scan → each step is one authored file or one run.
- Type consistency → `create_batch_sales_invoice`, `get_purchase_context`, `get_ops_snapshot`, `ensure_livestock_roles`, `latest_weight()`, `force=` used only by the tasks that produce them.
- Review Focus → all 5 pinned (Tasks 11/13, 5, 7/9, 2/16, 14).
- Proportion → backend tasks are test-cycled; UI tasks are manual-verified (no JS test harness exists in the app).
- One deliberate deviation from the audit text is pinned: the audit's `title_field`/autoname-format suggestions on Feed Event / Weight are downgrade-pins (hash names + search fields) because format-autoname templates are fragile in v16 and the audit's own top-5 priorities don't include them — flagged as my call.

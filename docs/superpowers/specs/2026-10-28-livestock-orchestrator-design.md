# Livestock Orchestrator — Design

- **App:** `frappe_livestock` (Frappe Framework v16)
- **Date:** 2026-10-28
- **Status:** draft — for builder review, then owner approval

---

## 1. Intent (the why)

> **The product is capture, not reports.** Every report (profit, mortality, cost) only works if
> recording actually happens — and recording stopped happening because it was painful.

Two abandoned approaches in ERPNext prove the point: Projects made the batch something you had to
*remember to select* (so feed landed on the wrong project or no project), and Manufacturing made
stage changes a weeks-long timer you forgot to stop. Both times the system made a human do
bookkeeping, and the human eventually walked away.

This app is an **orchestration layer over ERPNext core**. It stops asking the human for things it
already knows, and it records the rest in near-zero-effort, correct-by-construction steps. Analytics
are the reward that follows capture, not the product itself.

---

## 2. Goals · Non-goals · Anti-goals

| | |
|---|---|
| **Goal** | Make daily capture (mortality, feed, movement, purchases) trivial and correct-by-construction on a phone and at a desk. |
| **Goal** | Turn a batch's identity, stage, remaining count, and cost into *computed* facts the human never types. |
| **Goal** | Report profit, mortality, and cost-per-bird per batch, fed by that capture. |
| **Goal** | Be species-generic: broiler first, but pig/fish/cattle/layer later with no redesign. |
| **Goal** | Be ERP-generic: install on any ERPNext site, not tailored to one farm's data. |
| **Non-goal** | A replacement for ERPNext accounting/stock. ERPNext stays the ledger. |
| **Non-goal** | Per-bird identity (tags/serials), vaccine scheduling, age-weighted costing — phase 1. |
| **Anti-goal** | Any design that makes a human re-select or re-type what the system already knows. |
| **Anti-goal** | A stock/manufacturing replica — that is the exact pain we are removing. |
| **Anti-goal** | Over-engineering for volume that does not exist (resilience machinery, queues). |

---

## 3. Constraints

1. **Frappe v16 app layout** — `hooks.py`, proper package layout, whitelisted methods under an
   `api/` module (`frappe.call("frappe_livestock.api.x")`, never without the `.api` segment).
2. **Generic over custom** — species, stage schedules, naming convention, and the Item↔role mapping
   (chick / feed / medicine / finished bird) are all configuration, never hardcoded. An existing
   site's data is *evidence of pain*, not a template.
3. **Simplicity over resilience** — low transaction volume; no queues, no retry machinery, no
   multi-company gymnastics.
4. **Explicit save over autosave.** Restraint in the UI (fewer controls, not more).
5. **Live animals are not warehouse stock.** We do **not** create Stock Entries or Work Orders for
   birds. The batch is its own ledger; ERPNext stock is used only for real inventory (feed bags,
   medicine), and for revenue (the finished bird is sold as an Item, but its quantity is not
   warehouse-tracked).

---

## 4. Domain model

```
                       ┌──────────────────────────────────────┐
                       │           Livestock Type             │   species + stage schedule
                       │  broiler · layer · pig · fish · …    │   Stages[]: name, start_day, end_day
                       │  + item mapping (chick/feed/finished)│
                       └──────────────────┬───────────────────┘
                                          │ 1 ──── * (one type, many batches)
                       ┌──────────────────▼───────────────────┐
        ┌──────────────┤               Livestock Batch                  │──────────────┐
        │              │  one batch, named from collection    │              │
        │              │  placed · remaining · cost (computed)│              │
        │              └──┬──────────┬──────────┬─────────┬───┘              │
        │     1..*        │          │          │         │     1..*         │
   ┌────▼────┐      ┌─────▼───┐ ┌────▼────┐ ┌───▼──────┐ ┌──▼──────────┐
   │Mortality│      │FeedEvent│ │Movement │ │Batch Cost │ │   Housing   │
   │ qty,date│      │open/fin │ │from→to  │ │(alloc)   │ │ +Regions[]  │
   └─────────┘      └─────────┘ └─────────┘ └──────────┘ └─────────────┘
```

### Custom DocTypes (new)

| DocType | What it is | Key fields |
|---|---|---|
| **Livestock Type** | species + its stage schedule + item roles | `stages` (child), `stocking_item`, `finished_item`, default stage UOMs |
| **Livestock Batch** | one batch of animals | `livestock_type`, `start_date`, `quantity_placed`, `housing`, `status`, computed: `age`, `stage`, `remaining`, `total_cost`, `cost_per_head`, `expected_ready_date` |
| **Mortality** | a death event, quick-captured | `batch`, `date`, `qty`, `reason` (age/stage computed) |
| **Feed Event** | a bag opened / finished | `batch`, `feed_item`, `event` (Open/Finish), `date`, `qty` |
| **Movement** | birds moved between housing | `batch`, `from_housing`, `to_housing`, `date`, `qty` |
| **Housing** | a room / pen / region | `type` (brooding/grower/finisher/general), `capacity`, `status` (occupied/resting/ready), `last_used_date`, `last_cleaned_date`, `regions` (child) |
| **Batch Cost** | purchase split across batches | `purchase_invoice`, child rows `{item, qty, amount, batch}` |
| **Livestock Settings** | single global config | naming convention, default type, default items |

### Reused from ERPNext (not rebuilt)

- **Item** — chick, feed, medicine, finished bird (the finished bird is sold, not stock-tracked).
- **Warehouse** — only for real inventory (feed, medicine).
- **Purchase Invoice / Purchase Order / Payment** — the cost ledger.
- **Sales Invoice / POS** — the revenue ledger (shop).
- **Project** — *optional* bridge for sites that already route purchases through Projects.

### ERPNext ↔ app bridge

```
ERPNext core (ledger, unchanged)          frappe_livestock (orchestration)
──────────────────────────────────        ─────────────────────────────────────
Item · Warehouse · Purchase Invoice        Livestock Type · Livestock Batch · Housing
Sales Invoice · Project (optional)         Mortality · FeedEvent · Movement
        │                                          │
        └── bulk Purchase Invoice ──alloc──▶ Batch Cost (split bags → batches)
            shop Sales Invoice     ──FIFO──▶ deduct remaining, revenue → batch
```

---

## 5. Orchestration rules (the automations that remove the pain)

| # | Rule | How it removes pain |
|---|---|---|
| 1 | **Stage transitions are computed by age**, not timers. A daily scheduler reads `batch.age` against the type's stage schedule and sets `stage`. | Nothing to start, stop, or forget. |
| 2 | **Purchase is one action, then allocated.** A "full purchase" creates and submits PO → Purchase Receipt → Purchase Invoice → Payment Entry in one transactional call (with amend/cancel variants), then a light "split to batches" step assigns bags/medicine to active batches (Batch Cost rows). | No wrong-project, no forgot-to-select, no navigating four forms; recording a purchase is smooth — the whole point. |
| 3 | **Sale allocation targets the "ready" batch.** The owner marks a batch **Ready** when it goes to the shop; sales of `finished_item` deduct from ready batches (oldest-ready first when more than one) until `remaining` = 0. | Batch identity is *reconstructed* from quantities; the shop sells one item, unchanged; the sell moment is human-decided. |
| 4 | **Cost is simple (phase 1).** `cost_per_head = total_cost ÷ surviving` where `total_cost` = chick + allocated feed + medicine, and `surviving = placed − mortalities`. | Answers "what have I spent, what does each bird cost me" with no machinery. |
| 5 | **The linchpin:** `remaining = placed − mortalities − sold`, computed. Mortalities *reduce* it, sales *pull* from it, profit falls out of it. | One number carries identity, cost, and profit. |

### Naming (default, configurable)

```
batch.name  =  "{livestock_type} {start_date}"      e.g.  "Broiler 2026-10-28"
expected_ready_date  =  start_date + last stage end_day   (computed, not typed)
```

---

## 6. Capture surfaces

```
 phone (rounds, one-tap)                       desk (purchases, one action)
 ──────────────────────                        ──────────────────────────────
 Mortality  ·  Feed Event  ·  Movement         "Buy feed / medicine / chicks"
   "3 died in Grower"        "bag 4 opened"      → PO → PR → PI → Payment (auto)
                                                  → "split to batches" (allocation)
        │                                            │
        └──────────────▶  Livestock Batch  ◀──────────────────┘
                          (remaining · stage · cost)
```

- **Phone:** lean native Frappe forms (minimal fields, batch defaulted to the active one, one tap to
  submit). This is the surface that must be *perfectly* frictionless — it is where recording died.
- **Desk:** one "full purchase" action creates and submits the whole chain (PO → Purchase Receipt →
  Purchase Invoice → Payment Entry), following the `awesome_dashboard` pattern; the app then adds the one
  allocation step. No navigating four forms, no duplicate entry.
- **Livestock Batch is implied, not selected:** with batches spaced 2–4 weeks apart, the app defaults to the
  current/active batch and the human corrects only when wrong.

---

## 7. Costing (phase 1)

```
total_cost        =  chick allocation + Σ feed allocations + Σ medicine allocations
surviving   =  quantity_placed − Σ mortalities
cost_per_head     =  total_cost / surviving            (live, at any point in the week)
mortality_loss    =  Σ mortalities × cost_per_head           (simple; not age-weighted)
```

Deferred to later phases: age-weighted mortality cost (a bird dead at day 2 vs week 5), and formal
profit statements (revenue − cost, per batch, once sale allocation lands).

---

## 8. Phases

| Phase | Scope |
|---|---|
| **1 — broilers MVP** | Livestock Type, Livestock Batch, Mortality, Feed Event, Housing, Batch Cost (allocation), **full purchase cycle (PO→PR→PI→Payment, amend/cancel)**, simple cost-per-bird, phone quick-capture, basic batch dashboard. |
| **2 — generic + depth** | More species (pig/fish/cattle/layer), Movement history, vaccine/medicine schedule, age-weighted costing, room resting/disinfection reminders. |
| **3 — reporting** | Profit statements, feed consumption forecasting (bags bought vs in warehouse vs consumed timeline). |

---

## 9. Decisions the owner made (verbatim intent)

1. Capture is the product; analytics are downstream.
2. Phone for rounds, desk for purchases — both must work.
3. Batch identity = collection date; stages auto by age.
4. Cost = total spent ÷ surviving birds (simple), for now.
5. Bulk feed purchases are split to batches by an allocation step, not auto-attached to "the active batch".
6. Sales go through a retail shop; batch is inferred FIFO by remaining birds; one item, one company.
7. Generic app: existing site data is evidence, not a template.
8. The purchase cycle (PO → invoice → payment) is phase 1, not deferred — recording purchases smoothly
   is the whole point.

## 10. Calls I made (check these while reading — override freely)

1. **Live birds are not ERPNext stock** — batch quantity is a plain number on the Livestock Batch; no Stock
   Entries/Work Orders for birds (constraint 5 above).
2. **Separate DocTypes** (Mortality/FeedEvent/Movement/Batch Cost) rather than child tables, so each
   has clean list views and per-record capture; Livestock Batch aggregates them.
3. **Housing is a custom DocType** (not Warehouse), because resting/disinfection/last-used are not
   Warehouse concepts; it may optionally link to a Warehouse if a site wants bird locations in stock
   later.
4. **Batch Cost is a standalone allocation doc** (source Purchase Invoice + rows → batches), rather
   than a Livestock Batch child table, because a single purchase can span several batches.
5. **Purchase cycle orchestration is phase 1** — a "full purchase" action that creates and submits
   PO → Purchase Receipt → Purchase Invoice → Payment Entry in one transactional call, with
   amend/cancel variants, following the `awesome_dashboard` pattern (`create_full_purchase` /
   `amend_full_purchase` / `cancel_full_purchase`). The Batch Cost allocation step then splits that
   purchase across batches. Payment is always immediate and in full (the owner pays suppliers on the
   spot); only the mode of payment varies (Cash / bank / mobile money).
6. **Naming default** `"{type} {start_date}"`, configurable.
7. **Feed Events are informational** — no Stock Entry / Material Issue in phase 1. "Bags in warehouse"
   comes from ERPNext's own stock; feed events give the *rough consumption timeline* (opened/finished).
   Formal material-issue stock movements are a later option, only if they become worth the ledger friction.
8. **Medicine is cost-only in phase 1** — recorded via Batch Cost allocation; no medicine consumption
   or event capture (the owner asked for a feed timeline, not a medicine timeline).
9. **Chick cost arrives through the same allocation mechanism as feed.** Livestock Batch creation captures
   `quantity_placed` + start date; the stocking purchase is allocated to the batch like any other cost.
   One mechanism, no special case.
10. **Phase 1 housing is single-location** — Livestock Batch has one `housing` link; moving a batch = update that
    field (whole-batch). Partial-quantity splits and Movement history are Phase 2. `regions` are named
    sub-pens within a house (labels, used for resting tracking later).
11. **"Active" batch default** = most-recently-created non-closed batch; the phone form pre-fills it and
    the human corrects only when wrong. Lifecycle `status` ∈ Draft → Active → Ready (manual, "now
    selling") → Closed (closed when `remaining` = 0 or manually). Stage and age stay automatic for
    planning; "ready to sell" is a human call.
12. **Sale allocation (phase 1)** = light allocation: sales of `finished_item` deduct from the batch(s)
    marked **Ready** (oldest-ready first when more than one); cancellations / returns / over-sale are
    handled by a manual `remaining` correction, not automatic reverse-allocation.

## 11. Owner decisions (resolved)

1. **Phone capture is online-only.** Reliable connectivity during rounds; standard Frappe web forms. No
   offline queue / sync (keeps phase 1 simple).
2. **"Ready to sell" is a manual call.** The owner marks a batch **Ready** when it actually goes to the
   shop. Age still auto-computes stage and `expected_ready_date` for planning, but the sell moment is
   human-decided.

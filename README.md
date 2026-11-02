### Frappe Livestock

A simple module to make managing livestock easier

### Installation

This app targets **Frappe v16 and ERPNext v16** (a `before_install` guard refuses
other majors; ERPNext is installed automatically as a `required_apps` dependency).

You can install this app using the [bench](https://github.com/frappe/bench) CLI:

```bash
cd $PATH_TO_YOUR_BENCH
bench get-app $URL_OF_THIS_REPO --branch version-16
bench install-app frappe_livestock
```

### Contributing

This app uses `pre-commit` for code formatting and linting. Please [install pre-commit](https://pre-commit.com/#installation) and enable it for this repository:

```bash
cd apps/frappe_livestock
pre-commit install
```

Pre-commit is configured to use the following tools for checking and formatting your code:

- ruff
- eslint
- prettier
- pyupgrade

### Roles & setup

`installer.ensure_livestock_roles` (runs on migrate) seeds two roles:

| Role | Access |
|---|---|
| Livestock Manager | full perms on all livestock doctypes + both Pages + reporting gate |
| Livestock Operator | create/read/write/report on Feed Event, Mortality, Livestock Weight; read on Livestock Batch/Type/Housing |

Reporting/batch pages admit System Manager / Livestock Dashboard / Livestock Manager.
Operators do **not** see the purchase-entry page (403 "Not permitted").

- `finished_item` must be set on the Livestock Type before sale allocation activates.
- `stocking_item` must be set on the Livestock Type before the batch's "Buy day-old chicks" action works.

### Feed semantics

A Feed Event is one **"feed consumed"** record (qty required, Feeding Date).
Legacy Open/Finish bag pairs were folded by the `fold_feed_events` patch.

### Batch naming

`{type} {date}`; collisions get ` 2`, ` 3`, …

### Workspace, scheduler, sales

- **Livestock** workspace ships 12 shortcuts; purchase-entry and batch-dashboard
  pages are rewritten on Frappe page primitives (shared `livestock_forms.js`;
  buy dialog defaults come from `get_purchase_context`).
- Daily scheduler nudges run via `tasks.daily` (`scheduler_events.daily`).
- Housing moves log comments; allocation overwrite needs `force=` confirm;
  batch sales go through `api.sales.create_batch_sales_invoice`.

### Tests

```bash
bench --site development.localhost run-tests --app frappe_livestock
```

### Reporting API (for dashboard consumers)

Read-only surface under `frappe_livestock.api.reporting.*`:

| Endpoint | Returns |
|---|---|
| `portfolio(company?, status?, from_date?, to_date?)` | one row per batch: stage, age, remaining, cost, cost/bird, revenue, profit, margin |
| `batch_pl(batch, from_date?, to_date?)` | cost lines by category (chicks/feed/medicine), revenue lines, totals |
| `batch_gl_entries(batch, from_date?, to_date?)` | GL Entries of every voucher the batch's cost/sale allocations point at |
| `feed_timeline(batch?, from_date?, to_date?)` | raw feed-consumed rows |
| `mortality_rows(batch?, from_date?, to_date?)` | raw death rows |

Rules: raw rows out — bucketing/grouping/charting is the consumer's job;
nothing here mutates; revenue comes from the `Batch Sale` ledger that the
Sales Invoice on_submit hook writes (and on_cancel revokes). Call with token
auth: `Authorization: token <api_key>:<api_secret>`.

### License

mit

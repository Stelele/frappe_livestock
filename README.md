### Frappe Livestock

A simple module to make managing livestock easier

### Installation

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

### Permissions & setup

- Custom doctypes (Flock, Livestock Type, Mortality, Flock Cost, Feed Event) are System-Manager-only by design.
- Sale allocation works for any user who can submit a Sales Invoice (permission-free flock counters by design).
- The flock-dashboard page ships System-Manager-only.
- `finished_item` must be set on the Livestock Type before sale allocation activates.
- `chick_item` must be set on the Livestock Type before the flock's "Buy day-old chicks" action works.

### Reporting API (for dashboard consumers)

Read-only surface under `frappe_livestock.api.reporting.*`, gated to the
**Livestock Dashboard** role (created read-only on migrate; grant it to a
token user to consume):

| Endpoint | Returns |
|---|---|
| `portfolio(company?, status?, from_date?, to_date?)` | one row per flock: stage, age, remaining, cost, cost/bird, revenue, profit, margin |
| `flock_pl(flock, from_date?, to_date?)` | cost lines by category (chicks/feed/medicine), revenue lines, totals |
| `flock_gl_entries(flock, from_date?, to_date?)` | GL Entries of every voucher the flock's cost/sale allocations point at |
| `feed_timeline(flock?, from_date?, to_date?)` | raw bag open/finish rows |
| `mortality_rows(flock?, from_date?, to_date?)` | raw death rows |

Rules: raw rows out — bucketing/grouping/charting is the consumer's job;
nothing here mutates; revenue comes from the `Flock Sale` ledger that the
Sales Invoice on_submit hook writes (and on_cancel revokes). Call with token
auth: `Authorization: token <api_key>:<api_secret>`.

### License

mit

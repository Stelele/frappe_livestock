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

### License

mit

# pytest-nova-bdd

Write browser tests as Gherkin feature files and let [Amazon Nova Act](https://github.com/aws/nova-act)
carry out the steps. Any step that has no Python step definition is sent to Nova Act in a real browser.
Steps you do define in Python run as normal and always take precedence.

> Status: pre-alpha. See [docs/DESIGN.md](docs/DESIGN.md) for the design and roadmap.

```gherkin
# features/search.feature
Feature: Search
  Scenario: Find a book
    Given I am on "https://books.example.com"
    When I search for "Dune" and open the first result
    Then the page shows the author "Frank Herbert"
```

```python
# test_search.py
from pytest_bdd import scenarios

scenarios("features/search.feature")
```

```console
$ pip install pytest-nova-bdd
$ export NOVA_ACT_API_KEY=...
$ pytest
```

## How steps run

| Step | What happens |
|---|---|
| Matches a Python step definition | Your function runs. It can use the `nova`, `nova_page` or `nova_session` fixtures. |
| `Given/When I am on / navigate to / go to / open / visit <url>` | The browser goes straight to the URL, with no model call. Relative URLs (`/cart`) use `nova_base_url`. |
| Any other `Given` / `When` | Nova Act carries out the step under a strict contract (below). A docstring or data table is appended to the prompt. |
| `Then` | Nova Act observes the page, without changing it, and answers true / false / unsure, quoting the page text it relied on. Only a grounded "true" passes. |

Each scenario gets its own browser, started only when the first Nova step needs it.

## Guardrails: a pass has to mean something

An AI agent will happily "find a way" to finish a task. In a test, that would turn regressions into green runs.
The plugin enforces these rules itself rather than only asking the agent nicely:

- **Do exactly the step, or fail.** Actions run under a fixed contract: no typing URLs, no workarounds, no
  extra fixes. They have a budget of 10 browser actions (Nova's default is 30), and the agent must report
  whether it did the step exactly as written. Any reported deviation fails the step.
- **Stay in the app.** A navigation fence blocks any origin other than `nova_base_url`, URLs you navigate to
  explicitly, and `nova_allowed_origins`.
- **Then checks are read-only.** The plugin snapshots the URL, page text and form values before and after each
  check. If anything changed, the step fails whatever the verdict. During a check, navigation is blocked
  entirely and the budget is 3 actions.
- **Verdicts must be grounded.** `unsure` fails. A `true` must quote text, and each quote must really be on
  the page. Quoted text in the step itself (`Then the list contains "Buy milk"`) is also checked against the
  page, with no model involved.
- **Repeatable by default.** Temperature 0 and a stable seed per test and step. There are no automatic
  retries, because a flaky step should be made more specific or moved into Python.

See [docs/DESIGN.md §4.10](docs/DESIGN.md) for the threat model and the remaining roadmap (evidence artifacts,
path-drift baselines).

## Mixing in Python steps

```python
from pytest_bdd import given, parsers

@given(parsers.parse('I am logged in as "{user}"'))
def logged_in(nova_page, user):
    nova_page.goto("https://books.example.com/login")
    nova_page.fill("#user", user)
    nova_page.fill("#password", os.environ["TEST_PASSWORD"])  # secrets never go to the model
    nova_page.click("button[type=submit]")
```

## Authentication

`nova_auth = auto` (the default) uses `NOVA_ACT_API_KEY` if it is set. Otherwise it uses AWS IAM credentials
from the standard boto chain, which needs `nova_workflow_definition`. You can force one mode with
`nova_auth = api_key` or `nova_auth = iam`.

## Configuration

```toml
[tool.pytest.ini_options]
nova_base_url = "https://books.example.com"
nova_headless = true            # defaults to true when $CI is set
nova_max_steps = 10             # per Given/When step
nova_verify_max_steps = 3       # per Then check
nova_timeout = 120
nova_model_temperature = 0      # "none" for Nova's default
nova_model_seed = "auto"        # stable per test+step; or an int; or "none"
nova_allowed_origins = ["https://login.example.com"]
nova_readonly_check = true
nova_literal_check = true
nova_then_mode = "verify"       # or "act"
nova_auth = "auto"              # auto | api_key | iam
nova_workflow_definition = "my-suite"   # IAM only
nova_aws_profile = "qa"                 # IAM only
nova_aws_region = "us-east-1"           # IAM only
```

Command-line flags: `--no-nova` / `--nova`, `--nova-base-url URL`, `--nova-headless` / `--nova-headed`, and
`--nova-auth MODE`.

## Testing without Nova Act

`pynova_bdd.testing.FakeNovaAct` records prompts and returns scripted results, so suites can run offline:

```python
# conftest.py
import pytest
from pynova_bdd.testing import FakeNovaAct

@pytest.fixture(scope="session")
def fake_nova():
    return FakeNovaAct()

@pytest.fixture(scope="session")
def nova_client_factory(fake_nova):
    return fake_nova.factory
```

## Development

```console
$ uv sync
$ uv run pytest
$ uv run ruff check . && uv run ruff format --check . && uv run mypy
```

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
| Any other `Given` / `When` | `nova.act(<step text>)`. A docstring or data table is appended to the prompt. |
| `Then` | Nova Act checks the statement against the page and answers yes/no with evidence. A "no" fails the test with that evidence. |

Each scenario gets its own browser, started only when the first Nova step needs it.

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
nova_max_steps = 30
nova_timeout = 120
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

# pynova-bdd — Design & Implementation Plan

Status: **Approved direction** (decisions in §7) · Package: `pytest-nova-bdd` (import `pynova_bdd`) · Targets: `nova-act` 3.x, `pytest-bdd` ≥ 8.1, < 10, Python ≥ 3.10

## 1. Problem

[pytest-bdd](https://github.com/pytest-dev/pytest-bdd) splits a test into Gherkin `.feature` files and Python
step definitions. In browser testing, most of those step definitions are boilerplate: they locate an element and
click or type in it, and they break when the markup changes.

[Nova Act](https://github.com/aws/nova-act) takes a plain-language instruction (`nova.act("click the Sign in button")`)
and carries it out in a real Chromium browser. Since Gherkin steps are already plain-language instructions,
**the feature file can be the automation**. We only need to write Python where it adds something: deterministic
setup, test data, API calls, or assertions that must be exact.

`pynova-bdd` is a pytest plugin that wires these together:

```gherkin
Feature: Checkout
  Scenario: Guest buys a book
    Given I am on "https://books.example.com"
    When I search for "Dune" and open the first result
    And I add it to the cart
    Then the cart shows 1 item
```

```python
# test_checkout.py — the whole test module
from pytest_bdd import scenarios
scenarios("checkout.feature")
```

No step definitions are needed. Each step without a Python definition goes to Nova Act.

## 2. Goals / non-goals

**Goals**
- Run steps that have no Python definition through Nova Act, with no glue code.
- Let Python and Nova steps sit side by side in one scenario. A Python step definition always wins over Nova.
- Map Gherkin semantics correctly: `Given`/`When` are **actions**, and `Then` is an **assertion** that must
  produce a real pass or fail, not "the agent did something".
- Give pytest users what they expect: fixtures, markers/tags, `-k`, xdist, and useful failure output.
- Make Nova usage visible and controllable (opt in or out by tag, a strict mode, a dry-run plan) because each
  Nova step costs model calls and time.

**Non-goals (v1)**
- Replacing pytest-bdd's parser or runner. We extend it through public APIs.
- Recording a run and replaying it with no model calls. Nova's `replayable` trajectories could support this later.
- Supporting BDD runners other than pytest-bdd (behave, etc.).

## 3. Key findings from the upstream APIs

These facts come from reading `nova-act==3.4.187.0` and `pytest-bdd==9.0.0`, and they drive the design:

| Finding | Implication |
|---|---|
| `NovaAct(starting_page, headless=, logs_directory=, record_video=, nova_act_api_key=, workflow=, ...)` is a context manager (`start()`/`stop()`), and `nova.page` exposes the Playwright `Page`. | The plugin owns the client lifecycle as a fixture. Python steps can still use Playwright through `nova.page`. |
| `nova.act(prompt, max_steps=, timeout=, ...) -> ActResult` raises `ActAgentFailed`, `ActExceededMaxStepsError`, `ActTimeoutError`, and so on. | Action steps map directly onto this. We translate errors into readable pytest failures. |
| `nova.act_get(prompt, schema=BOOL_SCHEMA)` returns `.parsed_response` and `.matches_schema`. | `Then` steps become yes/no questions with a structured answer, which gives a real assertion. |
| Auth uses either `NOVA_ACT_API_KEY` or IAM through `Workflow(model_id=..., boto_session_kwargs=...)`. | The config must support both. A workflow is a context manager that should live at session scope. |
| Each `NovaAct` in one process needs its own `user_data_dir` (the default temp dir is fine). | Function-scoped clients work with `pytest-xdist` without extra setup. |
| pytest-bdd step defs are fixtures. When several match one step, they are sorted by scope path (`inject_fixturedefs_for_step`), and the **most specific one wins**. | A catch-all step registered by the plugin at root scope is overridden by any user step in a conftest or test module. This is the core routing mechanism and needs **no monkeypatching**. |
| `pytest_bdd_before_step`, `after_step`, `step_error`, `before/after_scenario`, and `apply_tag` hooks are public. | Used for reporting, artifacts, and tag-based configuration. |
| `nova-act[cli]` ships a `qa-plan` command that compiles `.feature` files into CLI plans. | Related upstream work, but it runs outside pytest. Our value is pytest integration: fixtures, mixing Python and Nova steps, reporting, and parallel runs. |

## 4. Architecture

```
            .feature file
                 │  (pytest-bdd parses & collects)
                 ▼
     ┌───────────────────────────┐
     │ pytest-bdd step matching  │──── user step def matches? ──► run Python step
     └───────────────────────────┘                                 (may use `nova` fixture)
                 │ no user match → plugin catch-all matches
                 ▼
     ┌───────────────────────────┐
     │ pynova_bdd.steps          │  builds prompt from step text + docstring/datatable
     │  given/when → act()       │  + scenario context (optional)
     │  then       → act_get()   │──► NovaAct client (fixture) ──► browser
     └───────────────────────────┘
                 │ results / errors
                 ▼
     ┌───────────────────────────┐
     │ pynova_bdd.reporting      │  step log, Nova metadata, screenshots, video/log paths
     └───────────────────────────┘
```

### 4.1 Package layout

```
src/pynova_bdd/
  __init__.py        # public API: nova_step, NovaConfig, NovaStepFailed, …
  plugin.py          # pytest11 entry point: options, ini, fixtures, hooks
  config.py          # NovaConfig dataclass; merge ini < CLI < env < markers/tags
  client.py          # NovaAct factory + lifecycle (session Workflow, per-scenario client)
  steps.py           # catch-all given/when/then step definitions
  prompts.py         # step → prompt rendering (docstrings, tables, templates)
  assertions.py      # Then-step verification via act_get + BOOL/verdict schema
  secrets.py         # secret placeholders that are typed via Playwright, never sent to the model
  reporting.py       # failure messages, artifacts, pytest-html/allure extras (optional)
  errors.py          # NovaStepFailed, NovaAssertionFailed, mapping from nova_act errors
tests/
  unit/              # pure functions (prompts, config merge, error mapping)
  plugin/            # pytester-based tests using FakeNovaAct (no network)
  e2e/               # real Nova Act runs; skipped unless NOVA_ACT_API_KEY/AWS creds are set
examples/
```

Packaging: `pyproject.toml` (hatchling), `[project.entry-points.pytest11] nova_bdd = "pynova_bdd.plugin"`.
Distribution name `pytest-nova-bdd`, import package `pynova_bdd`.
Dependencies: `pytest-bdd>=8.1,<10`, `nova-act>=3,<4`. Tooling: `uv`, `ruff`, `mypy`, GitHub Actions on 3.10–3.13,
with a matrix axis for pytest-bdd 8.1.x and 9.x. The plugin must not touch pytest-bdd private attributes, because 9.0
moved several of them into internal registries.

### 4.2 Step routing (the core mechanism)

The plugin registers one catch-all per step type at root scope:

```python
@given(parsers.re(r"(?P<instruction>.+)"), target_fixture=None)
def _nova_given(instruction, nova_runner, request): nova_runner.action(instruction, request)

@when(parsers.re(r"(?P<instruction>.+)"))
def _nova_when(instruction, nova_runner, request): nova_runner.action(instruction, request)

@then(parsers.re(r"(?P<instruction>.+)"))
def _nova_then(instruction, nova_runner, request): nova_runner.verify(instruction, request)
```

Because pytest-bdd picks the most specific scope, **any user step definition beats the catch-all**. Routing is
therefore:

1. A user Python step matches → it runs. It can request the `nova` fixture and call `nova.act(...)` itself
   for hybrid steps.
2. Otherwise, if Nova is enabled for this scenario → the catch-all runs it through Nova.
3. Otherwise (strict mode, or a scenario tagged `@no_nova`) → the catch-all raises pytest-bdd's normal
   `StepDefinitionNotFoundError`-style failure, so behavior matches plain pytest-bdd.

`And`/`But` inherit their type from the previous step, as pytest-bdd already does.

> Risk to verify first in Phase 1: a step defined in a **root-level** `conftest.py` has the same scope path
> (`""`) as the plugin. Ties are broken by registration order, and entry-point plugins register before
> conftests, so the user step should still win. We pin this with a pytester test. If it doesn't hold, the
> fallback is to register the catch-all from `pytest_bdd_step_func_lookup_error`-adjacent logic or to ask
> users to install it with `from pynova_bdd import nova_steps` in a conftest.

### 4.3 Step → prompt

- The base prompt is the step text after pytest-bdd has substituted Scenario Outline `<params>`.
- A **docstring** is appended as an indented block ("Use the following text: …").
- A **data table** is rendered as a compact markdown table and appended ("using this data: …").
- An optional `nova_prompt_template` ini/marker setting wraps every action, for example to add
  "Do not navigate away from the current site." A separate template exists for Then steps.
- `Given I am on "<url>"` / `Given I navigate to <url>` is detected (URL regex) and handled
  deterministically with `nova.go_to_url(url)`, with no model call. This is faster and cheaper, and it gives
  the per-scenario client its starting page lazily.

### 4.4 Then-steps as real assertions

`verify()` calls:

```python
nova.act_get(
  f"Look at the current page. Is the following statement true? {instruction}",
  schema={"type": "object",
          "properties": {"passed": {"type": "boolean"}, "evidence": {"type": "string"}},
          "required": ["passed", "evidence"]},
)
```

- `passed is True` → the step passes.
- `passed is False` → `NovaAssertionFailed`, with the evidence and a screenshot path in the message.
- Schema mismatch or invalid JSON → a failure (never a silent pass). The message is labeled as an agent error
  so it is distinguishable from an assertion failure.
- A config switch, `nova_then_mode = act`, treats Then steps as actions instead, for teams that phrase them
  imperatively.

### 4.5 Fixtures

| Fixture | Scope | Purpose |
|---|---|---|
| `nova_config` | session | Resolved `NovaConfig` (ini + CLI + env). |
| `nova_workflow` | session | `nova_act.Workflow` (entered once per session) when auth resolves to IAM, otherwise `None`. |
| `nova` | function (configurable: `scenario`/`module`/`session`) | Started `NovaAct` client, stopped at teardown. Lazy: no browser starts unless a step uses it. |
| `nova_page` | function | Shortcut to `nova.page` (Playwright) for deterministic Python steps. |
| `nova_runner` | function | Internal adapter that applies per-scenario settings, prompt building, error mapping, and logging. |
| `nova_results` | function | List of `(step, ActResult)` for the scenario, for custom assertions or reporting. |

Users can override `nova` (for example to point at a CDP endpoint, or to pass `state_guardrail`/`tools`)
by redefining the fixture in their conftest.

### 4.6 Configuration

Precedence from lowest to highest: `pytest.ini`/`pyproject [tool.pytest.ini_options]` → env → CLI → tags/markers.

| ini / CLI | Default | Notes |
|---|---|---|
| `nova_enabled` / `--nova/--no-nova` | `true` | Global switch for the catch-all. |
| `nova_strict` / `--nova-strict` | `false` | Only scenarios tagged `@nova` may use Nova. |
| `nova_base_url` / `--nova-base-url` | – | Relative URLs in `Given I am on "/cart"` resolve against this. |
| `nova_headless` / `--nova-headless` | `true` in CI, otherwise `false` | Maps to `NovaAct(headless=)`. |
| `nova_max_steps`, `nova_timeout` | Nova defaults | Per-step limits. The tag `@nova_max_steps(50)` overrides them per scenario. |
| `nova_client_scope` | `function` | Clients are reused across scenarios only on request (faster, less isolated). |
| `nova_record_video`, `nova_artifacts_dir` | `false`, `.nova-artifacts/` | Per-test subfolder named after the nodeid. |
| `nova_auth` / `--nova-auth` | `auto` | `auto` \| `api_key` \| `iam`. See §4.10. |
| `nova_model_id` | `nova-act-latest` | Passed to `Workflow` with IAM. |
| `nova_aws_profile`, `nova_aws_region` | boto defaults | IAM only; become `boto_session_kwargs`. |
| `nova_then_mode` | `verify` | `verify` \| `act`. |
| `--nova-plan` | off | Dry run: collect only, then print which steps route to Python and which to Nova. No browser, no cost. |

Tags: `@nova`, `@no_nova`, `@nova_max_steps(N)`, `@nova_headed`. They are applied through
`pytest_bdd_apply_tag` and markers.

### 4.7 Secrets

Nova Act's guidance is to keep passwords out of prompts. Steps such as
`When I enter the secret "ADMIN_PASSWORD" into the password field` are matched by a dedicated built-in step:

1. `nova.act("focus/click the password field")`, sent without the secret.
2. `nova.page.keyboard.type(os.environ["ADMIN_PASSWORD"])` through Playwright. The value never reaches the model
   or the logs.

The same applies to a `<secret:NAME>` placeholder anywhere in a step. A step that contains such a placeholder
and isn't a recognized secret pattern fails rather than sending it.

### 4.8 Failure reporting

- Map `nova_act` errors to pytest failures with a short message, for example
  `Nova step failed (ActExceededMaxStepsError after 30 steps): When I add it to the cart`, followed by the
  Nova session/act IDs and the log/video paths.
- Hide the plugin's own frames with `__tracebackhide__` so the trace points at the feature step.
- Write artifacts per test: Nova logs directory, final screenshot on failure, and video if enabled.
- Optional integrations, activated when the plugin is installed: `pytest-html` extras (screenshot and links) and
  Allure attachments.
- A terminal summary at session end reports how many steps went to Nova and how many to Python, total Nova
  time, and the slowest Nova steps.

### 4.9 Authentication

Both modes are supported from Phase 1:

- **API key**: `NOVA_ACT_API_KEY` (or `nova_api_key` ini, discouraged) is passed as `nova_act_api_key=`.
- **IAM**: a session-scoped `nova_act.Workflow(model_id=..., boto_session_kwargs={profile_name, region_name})` is
  entered once and passed as `workflow=` to every client. Credentials come from the standard boto chain (env,
  profile, SSO, instance role).
- **`auto` (default)**: use the API key if `NOVA_ACT_API_KEY` is set, otherwise IAM. If neither resolves, fail at
  session start with one clear message instead of on the first Nova step. When no scenario would route a step to
  Nova (for example, every step has Python definitions), we skip the check so offline suites still run.
- Under xdist, each worker builds its own `Workflow`.

### 4.10 Parallelism & isolation

- Function-scoped clients use a fresh temporary `user_data_dir` each, so `pytest -n auto` works.
- An optional `nova_storage_state` setting (a saved Playwright storage state / Nova `browser_auth`) lets a
  logged-in session be reused across scenarios without logging in through the model every time.

## 5. Testing strategy

- **Unit**: prompt rendering, config precedence, URL detection, error mapping, and the secret placeholder guard.
- **Plugin (pytester)**: a `FakeNovaAct` records prompts and returns scripted results/errors. It is injected by
  overriding the client factory. Covers routing precedence (module, conftest, and root conftest vs the
  catch-all), strict mode/tags, Then pass/fail/garbled, outlines, docstrings/tables, xdist smoke, and
  `--nova-plan` output. **No network; runs on every PR.**
- **E2E**: a few scenarios against a stable public site (or a tiny local static site served by a fixture, which
  is better) using real Nova Act. Gated on `NOVA_ACT_API_KEY` and run nightly or manually, not on PRs.

## 6. Implementation plan

**Phase 0 — Scaffolding** (small)
- `pyproject.toml`, `src/` layout, entry point, ruff/mypy/pytest config, CI matrix (3.10–3.13), README stub.

**Phase 1 — Walking skeleton** (the core value)
- `NovaConfig` (ini + CLI only), `nova` fixture (function scope), catch-all given/when/then.
- Auth: API key **and** IAM `Workflow`, with `auto` resolution (§4.9).
- Then-steps through `act_get` and the boolean verdict schema. Deterministic `Given I am on <url>`.
- Error mapping into readable failures.
- `FakeNovaAct` and pytester tests, including the **routing-precedence test from §4.2**.
- `examples/` with one feature and one hybrid Python step.
- ✅ Exit criteria: `pytest examples/` passes against real Nova locally, and plugin tests pass in CI.

**Phase 2 — Control & ergonomics**
- Tags/markers (`@nova`, `@no_nova`, `@nova_max_steps`), strict mode, env layer, `--nova-plan` dry run.
- Docstring/data-table prompt rendering and prompt templates.
- `nova_client_scope`, `nova_base_url`, headless auto-detection.

**Phase 3 — Production readiness**
- Secrets (§4.7), storage-state reuse.
- Artifacts (screenshots, video, logs), terminal summary, pytest-html/Allure hooks.
- xdist verification, docs site (mkdocs), first PyPI release (`0.1.0`).

**Phase 4 — Later ideas**
- Record a run and replay it from Nova `replayable` trajectories, to cut cost in CI.
- `pytest --nova-generate-steps`: emit Python step stubs for Nova steps that a team wants to "harden".
- Async client support (`nova_act.asyncio`) to fit pytest-asyncio stacks.
- Per-step result caching or "assert-only" smoke modes.

## 7. Decisions

1. **Package name**: publish as `pytest-nova-bdd`, import as `pynova_bdd`. The repo stays `pynova-bdd`.
2. **Unmatched steps go to Nova by default.** This is a Nova framework, so routing through Nova is the expected
   behavior. `--nova-strict` and `@no_nova` exist to opt out.
3. **`Then` steps are yes/no verifications** (§4.4) by default. `nova_then_mode = act` remains an escape hatch.
4. **pytest-bdd `>=8.1,<10`.** 8.1.x was the current release for about 22 months (Dec 2024 – Sep 2026) and is
   what most projects run. 9.0 (2026-09-30) drops Python 3.9, moves private attributes into registries, and
   fixes docstring and backslash handling. CI tests both. 7.x uses the old parser and is not supported.
5. **Auth**: API key and IAM are both supported from Phase 1, with `auto` resolution (§4.9).

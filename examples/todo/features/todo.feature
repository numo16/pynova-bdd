Feature: Todo list
  Every step here except "the todo app is open" (a Python step in conftest.py)
  is carried out by Nova Act in the browser.

  Background:
    Given the todo app is open

  Scenario: Add a todo
    When I add a todo called "Buy milk"
    Then the list contains "Buy milk"
    And the counter says 1 item left

  Scenario: Complete a todo
    When I add a todo called "Walk the dog"
    And I add a todo called "Water the plants"
    And I mark "Walk the dog" as done
    Then "Walk the dog" is crossed out
    And the counter says 1 item left

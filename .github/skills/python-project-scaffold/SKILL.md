---
name: python-project-scaffold
description: Scaffold a Python module with implementation, pytest tests, and README. Triggered when user asks to create a Python script/module, utility with tests, or any write-Python-and-test workflow.
user-invocable: true
---

# Python Project Scaffold

Quickly create a well-structured Python project with implementation, tests, and documentation.

## When to Use

- User asks to write a Python utility/module and test it
- User asks to create a Python script that "calculates", "generates", or "processes" something
- Any "write Python + run it + add tests" workflow

## Workflow

1. **Create the directory** if it doesn't already exist.
2. **Create `<module>.py`** with:
   - Type hints on all function signatures
   - Docstrings (summary + Args + Returns + Raises)
   - A `if __name__ == "__main__":` block for standalone execution
3. **Run the module** and show output to the user.
4. **Create `test_<module>.py`** using pytest:
   - Group tests in classes (`TestFunctionName`)
   - Cover: base cases, known values, edge cases, error cases
   - Use type annotations on test methods
5. **Run pytest** — install if missing with `pip install pytest --break-system-packages`
6. **Create `README.md`** with: what it does, file table, how it works, usage snippet, test command.

## Key Patterns

```python
# Memoization
from functools import lru_cache

@lru_cache(maxsize=None)
def my_func(n: int) -> int:
    ...
```

```python
# pytest structure
class TestMyFunc:
    def test_base_case(self) -> None:
        assert my_func(0) == 0

    def test_raises(self) -> None:
        with pytest.raises(ValueError):
            my_func(-1)
```

## Environment Notes

- System Python (3.12) is externally managed; install packages with `pip install <pkg> --break-system-packages`
- Run tests from the project directory: `cd <dir> && python3 -m pytest <test_file> -v`

## User Preferences

- Always use **type hints** and **docstrings** on all Python functions
- Use **tabs** (not spaces), indent size 3

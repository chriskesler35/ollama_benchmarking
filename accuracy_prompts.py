#!/usr/bin/env python3
"""Accuracy benchmark tasks - every task has an objectively checkable answer.

Categories:
  coding          - model writes a function, we EXECUTE it against unit tests
  math            - word problems with a single numeric answer
  multiple_choice - answer with a letter, exact match
  instruction     - structural requirements checked programmatically
"""

import json
import re
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional


@dataclass
class AccuracyTask:
    id: str
    category: str
    prompt: str
    scorer: str          # name of a scorer function below
    expected: Any = None # meaning depends on scorer
    tests: str = ""      # python assert block (coding tasks only)


# ---------------------------------------------------------------------------
# Response cleanup
# ---------------------------------------------------------------------------

def clean_response(text: str) -> str:
    """Strip reasoning-model thinking blocks and surrounding whitespace."""
    # <think>...</think> from DeepSeek-R1 / Qwen3 style models
    text = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL | re.IGNORECASE)
    # Unclosed think block (model hit token limit mid-thought)
    text = re.sub(r"<think>.*", "", text, flags=re.DOTALL | re.IGNORECASE)
    return text.strip()


def extract_code(text: str) -> str:
    """Pull the python code out of a response (fenced block preferred)."""
    blocks = re.findall(r"```(?:python|py)?\s*\n(.*?)```", text, flags=re.DOTALL)
    if blocks:
        # Join all python blocks - models sometimes split helper + main function
        return "\n\n".join(b.strip() for b in blocks)
    return text.strip()


def extract_json(text: str):
    """Parse the first JSON object/array found in a response."""
    # Try fenced block first
    blocks = re.findall(r"```(?:json)?\s*\n(.*?)```", text, flags=re.DOTALL)
    candidates = [b.strip() for b in blocks] + [text.strip()]
    for cand in candidates:
        try:
            return json.loads(cand)
        except Exception:
            pass
        # Fall back to the first {...} or [...] span
        for open_ch, close_ch in (("{", "}"), ("[", "]")):
            start = cand.find(open_ch)
            end = cand.rfind(close_ch)
            if start != -1 and end > start:
                try:
                    return json.loads(cand[start:end + 1])
                except Exception:
                    pass
    return None


# ---------------------------------------------------------------------------
# Scorers - each returns (passed: bool, detail: str)
# ---------------------------------------------------------------------------

def score_exact_number(response: str, task: AccuracyTask):
    """Extract the answer number and compare to expected.

    Prefers an explicit 'ANSWER: <n>' marker (reliable, unambiguous) and falls
    back to the last number in the response.  Math prompts should end with
    'Give your final answer as: ANSWER: <number>' so the marker path is taken.
    The last-number fallback is kept for backward-compatibility with older
    stored results that lack the marker.
    """
    text = clean_response(response)
    # Prefer structured marker — avoids grabbing trailing context quantities
    # like "9 days for 8 workers" → "8" (the known failure mode of last-number).
    m = re.search(r"ANSWER\s*:\s*(-?\$?[\d,]*\.?\d+)", text, re.IGNORECASE)
    if m:
        candidate = m.group(1)
    else:
        nums = re.findall(r"-?\$?[\d,]*\.?\d+", text)
        if not nums:
            return False, "no number found in response"
        candidate = nums[-1]
    candidate = candidate.replace("$", "").replace(",", "")
    try:
        got = float(candidate)
    except ValueError:
        return False, f"could not parse '{candidate}'"
    ok = abs(got - float(task.expected)) < 1e-6
    return ok, f"expected {task.expected}, got {got}"


def score_multiple_choice(response: str, task: AccuracyTask):
    """Find the chosen letter (A-D)."""
    text = clean_response(response)
    # Prefer explicit "answer is X" / "Answer: X" phrasing
    m = re.search(r"answer(?:\s+is)?\s*[:\-]?\s*\(?([A-D])\)?\b", text, flags=re.IGNORECASE)
    if not m:
        # First standalone A-D letter (possibly "B)" or "(B)")
        m = re.search(r"(?<![A-Za-z])\(?([A-D])\)?(?![A-Za-z])", text)
    if not m:
        return False, "no letter A-D found"
    got = m.group(1).upper()
    return got == task.expected, f"expected {task.expected}, got {got}"


def score_python_tests(response: str, task: AccuracyTask):
    """Execute the model's code against assert-based unit tests in a subprocess."""
    code = extract_code(clean_response(response))
    if not code:
        return False, "no code found in response"

    program = code + "\n\n" + task.tests + "\nprint('ALL_TESTS_PASSED')\n"

    with tempfile.TemporaryDirectory() as tmpdir:
        script = Path(tmpdir) / "solution.py"
        script.write_text(program, encoding="utf-8")
        try:
            proc = subprocess.run(
                [sys.executable, "-I", str(script)],  # -I: isolated mode
                capture_output=True, text=True, timeout=20, cwd=tmpdir
            )
        except subprocess.TimeoutExpired:
            return False, "code timed out (20s)"
        except Exception as e:
            return False, f"runner error: {e}"

    if proc.returncode == 0 and "ALL_TESTS_PASSED" in proc.stdout:
        return True, "all tests passed"
    err = (proc.stderr or proc.stdout).strip().splitlines()
    return False, err[-1][:200] if err else "tests failed"


def score_json_keys(response: str, task: AccuracyTask):
    """Response must be a JSON object with exactly the expected keys."""
    data = extract_json(clean_response(response))
    if not isinstance(data, dict):
        return False, "no JSON object found"
    got = set(data.keys())
    want = set(task.expected)
    return got == want, f"expected keys {sorted(want)}, got {sorted(got)}"


def score_json_value(response: str, task: AccuracyTask):
    """Response must parse to JSON equal to the expected value."""
    data = extract_json(clean_response(response))
    return data == task.expected, f"expected {task.expected}, got {data}"


def score_bullet_count(response: str, task: AccuracyTask):
    """Exactly N lines starting with '- '."""
    text = clean_response(response)
    bullets = [ln for ln in text.splitlines() if ln.strip().startswith("- ")]
    return len(bullets) == task.expected, f"expected {task.expected} bullets, got {len(bullets)}"


def score_exact_word(response: str, task: AccuracyTask):
    """Response is exactly one word matching expected (case-insensitive)."""
    text = clean_response(response).strip().strip(".!\"'")
    return text.lower() == str(task.expected).lower(), f"expected '{task.expected}', got '{text[:50]}'"


def score_regex(response: str, task: AccuracyTask):
    """Expected regex must match somewhere in the response."""
    text = clean_response(response)
    ok = re.search(task.expected, text) is not None
    return ok, f"pattern {'matched' if ok else 'not matched'}"


SCORERS = {
    "exact_number": score_exact_number,
    "multiple_choice": score_multiple_choice,
    "python_tests": score_python_tests,
    "json_keys": score_json_keys,
    "json_value": score_json_value,
    "bullet_count": score_bullet_count,
    "exact_word": score_exact_word,
    "regex": score_regex,
}


def score_task(task: AccuracyTask, response: str):
    """Score a response. Never raises - a scorer crash counts as a fail."""
    try:
        return SCORERS[task.scorer](response, task)
    except Exception as e:
        return False, f"scorer error: {e}"


# ---------------------------------------------------------------------------
# The task suite
# ---------------------------------------------------------------------------

ACCURACY_TASKS = [
    # ----- coding (executed against unit tests) -----
    AccuracyTask(
        id="code_palindrome", category="coding", scorer="python_tests",
        prompt="Write a Python function `is_palindrome(s)` that returns True if the string s is a palindrome, ignoring case, spaces, and punctuation. Return only the function.",
        tests="assert is_palindrome('A man, a plan, a canal: Panama') == True\n"
              "assert is_palindrome('hello') == False\n"
              "assert is_palindrome('RaceCar') == True\n"
              "assert is_palindrome('') == True",
    ),
    AccuracyTask(
        id="code_run_length", category="coding", scorer="python_tests",
        prompt="Write a Python function `run_length_encode(s)` that returns a list of (char, count) tuples for each run of consecutive identical characters. Example: 'aaabbc' → [('a', 3), ('b', 2), ('c', 1)]. Return only the function.",
        tests="assert run_length_encode('aaabbc') == [('a', 3), ('b', 2), ('c', 1)]\n"
              "assert run_length_encode('abcd') == [('a', 1), ('b', 1), ('c', 1), ('d', 1)]\n"
              "assert run_length_encode('') == []\n"
              "assert run_length_encode('aaa') == [('a', 3)]",
    ),
    AccuracyTask(
        id="code_fibonacci", category="coding", scorer="python_tests",
        prompt="Write a Python function `fib(n)` that returns the nth Fibonacci number, where fib(0) = 0 and fib(1) = 1.",
        tests="assert fib(0) == 0\nassert fib(1) == 1\nassert fib(10) == 55\nassert fib(20) == 6765",
    ),
    AccuracyTask(
        id="code_reverse_words", category="coding", scorer="python_tests",
        prompt="Write a Python function `reverse_words(s)` that reverses the order of words in a string. Words are separated by single spaces.",
        tests="assert reverse_words('hello world foo') == 'foo world hello'\n"
              "assert reverse_words('one') == 'one'",
    ),
    AccuracyTask(
        id="code_is_prime", category="coding", scorer="python_tests",
        prompt="Write a Python function `is_prime(n)` that returns True if n is a prime number, False otherwise. Handle n < 2 correctly.",
        tests="assert is_prime(2) == True\nassert is_prime(97) == True\n"
              "assert is_prime(1) == False\nassert is_prime(100) == False\nassert is_prime(0) == False",
    ),
    AccuracyTask(
        id="code_rotate_list", category="coding", scorer="python_tests",
        prompt="Write a Python function `rotate_left(lst, k)` that rotates a list left by k positions. rotate_left([1,2,3,4,5], 2) returns [3,4,5,1,2]. Handle k larger than len(lst) and empty lists. Return only the function.",
        tests="assert rotate_left([1, 2, 3, 4, 5], 2) == [3, 4, 5, 1, 2]\n"
              "assert rotate_left([1, 2, 3], 0) == [1, 2, 3]\n"
              "assert rotate_left([1, 2, 3], 3) == [1, 2, 3]\n"
              "assert rotate_left([1, 2, 3], 5) == [3, 1, 2]\n"
              "assert rotate_left([], 2) == []",
    ),
    AccuracyTask(
        id="code_anagrams", category="coding", scorer="python_tests",
        prompt="Write a Python function `are_anagrams(a, b)` that returns True if the two strings are anagrams of each other, ignoring case.",
        tests="assert are_anagrams('listen', 'silent') == True\n"
              "assert are_anagrams('Listen', 'Silent') == True\n"
              "assert are_anagrams('hello', 'world') == False",
    ),
    AccuracyTask(
        id="code_second_largest", category="coding", scorer="python_tests",
        prompt="Write a Python function `second_largest(nums)` that returns the second largest DISTINCT value in a list of numbers. Assume the list has at least two distinct values.",
        tests="assert second_largest([3, 1, 4, 1, 5]) == 4\n"
              "assert second_largest([10, 10, 9]) == 9\n"
              "assert second_largest([1, 2]) == 1",
    ),

    # ----- math (exact numeric answer) -----
    # Prompts end with "ANSWER: <number>" so score_exact_number uses the reliable
    # structured-marker path instead of the fragile last-number heuristic.
    AccuracyTask(
        id="math_ratio", category="math", scorer="exact_number", expected=160,
        prompt="Three people share a prize of $360 in the ratio 2:3:4. How many dollars does the person with the largest share receive? Give your final answer as: ANSWER: <number>",
    ),
    AccuracyTask(
        id="math_distance", category="math", scorer="exact_number", expected=150,
        prompt="A train travels at 60 miles per hour for 2.5 hours. How many miles does it travel? Give your final answer as: ANSWER: <number>",
    ),
    AccuracyTask(
        id="math_workers", category="math", scorer="exact_number", expected=9,
        prompt="12 workers can build a wall in 6 days. Working at the same rate, how many days would it take 8 workers to build the same wall? Give your final answer as: ANSWER: <number>",
    ),
    AccuracyTask(
        id="math_perimeter", category="math", scorer="exact_number", expected=34,
        prompt="A rectangle has a length of 12 cm and a width of 5 cm. What is its perimeter in cm? Give your final answer as: ANSWER: <number>",
    ),
    AccuracyTask(
        id="math_gauss", category="math", scorer="exact_number", expected=5050,
        prompt="What is the sum of all integers from 1 to 100 inclusive? Give your final answer as: ANSWER: <number>",
    ),
    AccuracyTask(
        id="math_two_step_pct", category="math", scorer="exact_number", expected=96,
        prompt="A jacket costs $100. Its price is raised by 20%, then that higher price is reduced by 20%. What is the final price in dollars? Give your final answer as: ANSWER: <number>",
    ),
    AccuracyTask(
        id="math_discount", category="math", scorer="exact_number", expected=50,
        prompt="A shirt costs $40 after a 20% discount. What was the original price in dollars? Give your final answer as: ANSWER: <number>",
    ),
    AccuracyTask(
        id="math_average", category="math", scorer="exact_number", expected=18,
        prompt="What is the average (mean) of these numbers: 4, 8, 15, 16, 23, 42? Give your final answer as: ANSWER: <number>",
    ),

    # ----- multiple choice (letter answer) -----
    AccuracyTask(
        id="mc_fifo", category="multiple_choice", scorer="multiple_choice", expected="B",
        prompt="Which data structure uses FIFO (first in, first out) ordering?\nA) Stack\nB) Queue\nC) Binary tree\nD) Hash table\nAnswer with the letter only.",
    ),
    AccuracyTask(
        id="mc_binary_search", category="multiple_choice", scorer="multiple_choice", expected="C",
        prompt="What is the time complexity of binary search on a sorted array?\nA) O(n)\nB) O(n log n)\nC) O(log n)\nD) O(1)\nAnswer with the letter only.",
    ),
    AccuracyTask(
        id="mc_git_rebase", category="multiple_choice", scorer="multiple_choice", expected="B",
        prompt="What is the primary difference between `git merge` and `git rebase`?\nA) Merge creates a new branch; rebase deletes branches\nB) Rebase replays commits to produce a linear history; merge creates a merge commit preserving branch history\nC) Merge is faster than rebase for large repositories\nD) Rebase can only be used on remote branches\nAnswer with the letter only.",
    ),
    AccuracyTask(
        id="mc_http404", category="multiple_choice", scorer="multiple_choice", expected="B",
        prompt="What does HTTP status code 404 mean?\nA) Internal server error\nB) Not found\nC) Unauthorized\nD) OK\nAnswer with the letter only.",
    ),
    AccuracyTask(
        id="mc_tcp_udp", category="multiple_choice", scorer="multiple_choice", expected="A",
        prompt="Which statement about TCP vs UDP is correct?\nA) TCP guarantees delivery and ordering; UDP does not\nB) UDP is slower than TCP because it performs more error checking\nC) TCP is preferred for video streaming because of its speed\nD) UDP establishes a connection handshake before sending data\nAnswer with the letter only.",
    ),
    AccuracyTask(
        id="mc_gold", category="multiple_choice", scorer="multiple_choice", expected="B",
        prompt="What is the chemical symbol for gold?\nA) Ag\nB) Au\nC) Gd\nD) Go\nAnswer with the letter only.",
    ),
    AccuracyTask(
        id="mc_mergesort", category="multiple_choice", scorer="multiple_choice", expected="C",
        prompt="Which sorting algorithm has O(n log n) worst-case time complexity?\nA) Quicksort\nB) Bubble sort\nC) Merge sort\nD) Insertion sort\nAnswer with the letter only.",
    ),
    AccuracyTask(
        id="mc_sql", category="multiple_choice", scorer="multiple_choice", expected="A",
        prompt="What does SQL stand for?\nA) Structured Query Language\nB) Simple Question Language\nC) System Quality Logic\nD) Sequential Query List\nAnswer with the letter only.",
    ),

    # ----- instruction following (structural checks) -----
    AccuracyTask(
        id="inst_json_keys", category="instruction", scorer="json_keys",
        expected=["name", "age", "city"],
        prompt="Respond with a JSON object that has exactly these three keys: name, age, city. Use any plausible values. Respond with ONLY the JSON object, nothing else.",
    ),
    AccuracyTask(
        id="inst_bullets", category="instruction", scorer="bullet_count", expected=3,
        prompt="List exactly 3 benefits of exercise as bullet points. Each bullet must start with '- '. Respond with only the 3 bullet points, nothing else.",
    ),
    AccuracyTask(
        id="inst_one_word", category="instruction", scorer="exact_word", expected="Paris",
        prompt="What is the capital of France? Answer with exactly one word.",
    ),
    AccuracyTask(
        id="inst_repeat", category="instruction", scorer="regex",
        expected=r"HELLO\s*,\s*HELLO\s*,\s*HELLO",
        prompt="Write the word 'hello' in uppercase, exactly three times, separated by commas.",
    ),
    AccuracyTask(
        id="inst_json_array", category="instruction", scorer="json_value",
        expected=[1, 2, 3, 4, 5],
        prompt="Respond with a JSON array containing the integers 1 through 5 in order. Respond with ONLY the JSON array, nothing else.",
    ),
    AccuracyTask(
        id="inst_yes_no", category="instruction", scorer="exact_word", expected="yes",
        prompt="Is 17 a prime number? Answer with only the word 'yes' or 'no'.",
    ),
    AccuracyTask(
        id="inst_sorted", category="instruction", scorer="regex",
        expected=r"(?s)apple.*banana.*cherry.*date",
        prompt="Sort these words alphabetically and write them one per line, with no other text:\nbanana, apple, cherry, date",
    ),
    AccuracyTask(
        id="inst_vowel_count", category="instruction", scorer="exact_word", expected="5",
        prompt="How many vowels (a, e, i, o, u) are in the word 'sequoia'? Reply with only the digit, nothing else.",
    ),
]


CATEGORIES = ["coding", "math", "multiple_choice", "instruction"]

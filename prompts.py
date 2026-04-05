"""Test prompts organized by category for benchmarking Ollama models."""

from dataclasses import dataclass
from typing import List


@dataclass
class Prompt:
    """A single test prompt with its category."""
    category: str
    text: str


# 10 test prompts across 4 categories
TEST_PROMPTS: List[Prompt] = [
    # Reasoning (3 prompts)
    Prompt(
        category="reasoning",
        text="If all roses are flowers, and some flowers fade quickly, can we conclude that some roses fade quickly? Explain your reasoning."
    ),
    Prompt(
        category="reasoning",
        text="A farmer has 17 sheep. All but 9 die. How many sheep are left? Think step by step."
    ),
    Prompt(
        category="reasoning",
        text="What is the next number in this sequence: 2, 6, 12, 20, 30? Explain the pattern."
    ),
    # Coding (3 prompts)
    Prompt(
        category="coding",
        text="Write a Python function that checks if a string is a palindrome."
    ),
    Prompt(
        category="coding",
        text="Write a function to find the factorial of a number using recursion."
    ),
    Prompt(
        category="coding",
        text="Explain the difference between a list and a tuple in Python, with examples."
    ),
    # Creative (2 prompts)
    Prompt(
        category="creative",
        text="Write a haiku about artificial intelligence."
    ),
    Prompt(
        category="creative",
        text="Describe a sunset over mountains in exactly three sentences using vivid imagery."
    ),
    # Factual (2 prompts)
    Prompt(
        category="factual",
        text="What is the capital of Australia? Name three major cities in that country."
    ),
    Prompt(
        category="factual",
        text="Explain the process of photosynthesis in 2-3 sentences."
    ),
]


def get_prompts_by_category(category: str) -> List[Prompt]:
    """Filter prompts by category."""
    return [p for p in TEST_PROMPTS if p.category == category]


def get_categories() -> List[str]:
    """Get unique categories."""
    return list(set(p.category for p in TEST_PROMPTS))

"""Reporting and results handling for ollama-bench."""

import json
from dataclasses import dataclass, asdict
from datetime import datetime
from typing import List, Dict, Any
from rich.console import Console
from rich.table import Table
from rich import box


@dataclass
class PromptResult:
    """Result for a single prompt."""
    category: str
    prompt: str
    response_time_ms: float
    response: str
    tokens_generated: int = 0
    tokens_per_sec: float = 0.0


@dataclass
class ModelResult:
    """Aggregated results for a model."""
    model_name: str
    total_time_ms: float
    avg_time_ms: float
    category_times: Dict[str, float]
    prompt_results: List[PromptResult]
    load_time_ms: float = 0.0
    avg_tokens_per_sec: float = 0.0
    total_tokens: int = 0

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "model_name": self.model_name,
            "total_time_ms": self.total_time_ms,
            "avg_time_ms": self.avg_time_ms,
            "load_time_ms": self.load_time_ms,
            "category_times": self.category_times,
            "avg_tokens_per_sec": self.avg_tokens_per_sec,
            "total_tokens": self.total_tokens,
            "prompt_results": [asdict(p) for p in self.prompt_results]
        }


def calculate_model_result(model_name: str, results: List[PromptResult]) -> ModelResult:
    """Calculate aggregated metrics for a model."""
    total_time = sum(r.response_time_ms for r in results)
    avg_time = total_time / len(results) if results else 0

    category_times: Dict[str, float] = {}
    for cat in set(r.category for r in results):
        cat_results = [r for r in results if r.category == cat]
        category_times[cat] = sum(r.response_time_ms for r in cat_results) / len(cat_results)

    # Calculate token metrics
    total_tokens = sum(r.tokens_generated for r in results)
    avg_tokens_per_sec = sum(r.tokens_per_sec for r in results) / len(results) if results else 0

    return ModelResult(
        model_name=model_name,
        total_time_ms=total_time,
        avg_time_ms=avg_time,
        category_times=category_times,
        prompt_results=results,
        avg_tokens_per_sec=avg_tokens_per_sec,
        total_tokens=total_tokens
    )


def display_results_table(results: List[ModelResult]) -> None:
    """Display a ranked results table using rich."""
    console = Console()

    # Sort by average time (faster is better)
    sorted_results = sorted(results, key=lambda r: r.avg_time_ms)

    # Main results table
    table = Table(
        title="\n[RESULTS] GGUF Benchmark Results (llama.cpp with GPU Splitting)",
        box=box.ROUNDED,
        show_header=True,
        header_style="bold cyan"
    )

    table.add_column("Rank", style="bold yellow", justify="center", width=6)
    table.add_column("Model", style="bold green", width=20)
    table.add_column("Avg Time (ms)", justify="right", width=13)
    table.add_column("Tokens/sec", justify="right", width=11)
    table.add_column("Load (ms)", justify="right", width=10)
    table.add_column("Reasoning", justify="right", width=11)
    table.add_column("Coding", justify="right", width=10)
    table.add_column("Creative", justify="right", width=11)

    for i, result in enumerate(sorted_results, 1):
        rank_style = "bold gold1" if i == 1 else "bold white"
        rank_text = "1st" if i == 1 else ("2nd" if i == 2 else ("3rd" if i == 3 else f"{i}"))

        table.add_row(
            f"[{rank_style}]{rank_text}[/{rank_style}]",
            result.model_name,
            f"{result.avg_time_ms:.1f}",
            f"{result.avg_tokens_per_sec:.1f}",
            f"{result.load_time_ms:.0f}",
            f"{result.category_times.get('reasoning', 0):.1f}",
            f"{result.category_times.get('coding', 0):.1f}",
            f"{result.category_times.get('creative', 0):.1f}",
        )

    console.print()
    console.print(table)
    console.print()


def display_detailed_table(results: List[ModelResult]) -> None:
    """Display detailed per-prompt results."""
    console = Console()
    
    for result in sorted(results, key=lambda r: r.avg_time_ms):
        table = Table(
            title=f"\n[DETAIL] Detailed Results for {result.model_name}",
            box=box.SIMPLE,
            show_header=True,
            header_style="bold magenta"
        )
        
        table.add_column("Category", style="cyan", width=12)
        table.add_column("Prompt", width=50)
        table.add_column("Time (ms)", justify="right", width=12)
        
        for pr in result.prompt_results:
            prompt_preview = pr.prompt[:47] + "..." if len(pr.prompt) > 50 else pr.prompt
            table.add_row(
                pr.category,
                prompt_preview,
                f"{pr.response_time_ms:.1f}"
            )
        
        console.print(table)


def save_results_to_json(results: List[ModelResult], filename: str = "results.json") -> str:
    """Save results to a JSON file."""
    output = {
        "timestamp": datetime.now().isoformat(),
        "total_models": len(results),
        "results": [r.to_dict() for r in results]
    }
    
    with open(filename, "w") as f:
        json.dump(output, f, indent=2)
    
    return filename

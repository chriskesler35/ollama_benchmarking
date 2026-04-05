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


@dataclass
class ModelResult:
    """Aggregated results for a model."""
    model_name: str
    total_time_ms: float
    avg_time_ms: float
    category_times: Dict[str, float]
    prompt_results: List[PromptResult]

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "model_name": self.model_name,
            "total_time_ms": self.total_time_ms,
            "avg_time_ms": self.avg_time_ms,
            "category_times": self.category_times,
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
    
    return ModelResult(
        model_name=model_name,
        total_time_ms=total_time,
        avg_time_ms=avg_time,
        category_times=category_times,
        prompt_results=results
    )


def display_results_table(results: List[ModelResult]) -> None:
    """Display a ranked results table using rich."""
    console = Console()
    
    # Sort by average time (faster is better)
    sorted_results = sorted(results, key=lambda r: r.avg_time_ms)
    
    # Main results table
    table = Table(
        title="\n🏆 Ollama Benchmark Results",
        box=box.ROUNDED,
        show_header=True,
        header_style="bold cyan"
    )
    
    table.add_column("Rank", style="bold yellow", justify="center", width=6)
    table.add_column("Model", style="bold green", width=25)
    table.add_column("Avg Time (ms)", justify="right", width=14)
    table.add_column("Total Time (ms)", justify="right", width=16)
    table.add_column("Reasoning", justify="right", width=12)
    table.add_column("Coding", justify="right", width=12)
    table.add_column("Creative", justify="right", width=12)
    table.add_column("Factual", justify="right", width=12)
    
    for i, result in enumerate(sorted_results, 1):
        rank_style = "bold gold1" if i == 1 else "bold white"
        rank_emoji = "🥇" if i == 1 else ("🥈" if i == 2 else ("🥉" if i == 3 else f"{i}"))
        
        table.add_row(
            f"[{rank_style}]{rank_emoji}[/{rank_style}]",
            result.model_name,
            f"{result.avg_time_ms:.1f}",
            f"{result.total_time_ms:.1f}",
            f"{result.category_times.get('reasoning', 0):.1f}",
            f"{result.category_times.get('coding', 0):.1f}",
            f"{result.category_times.get('creative', 0):.1f}",
            f"{result.category_times.get('factual', 0):.1f}",
        )
    
    console.print()
    console.print(table)
    console.print()


def display_detailed_table(results: List[ModelResult]) -> None:
    """Display detailed per-prompt results."""
    console = Console()
    
    for result in sorted(results, key=lambda r: r.avg_time_ms):
        table = Table(
            title=f"\n📊 Detailed Results for {result.model_name}",
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

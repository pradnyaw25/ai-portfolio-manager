import json
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol


class GroupedRetriever(Protocol):
    def retrieve_grouped(
        self,
        *,
        query: str,
        symbols: list[str] | None = None,
        k_per_group: int = 4,
    ) -> dict[str, list[dict]]:
        ...


@dataclass
class MemoryEvalScenario:
    id: str
    description: str
    query: str
    symbols: list[str]
    k_per_group: int
    documents: list[dict]
    expected: dict[str, list[str]]


@dataclass
class MemoryEvalGroupResult:
    group: str
    expected_ids: list[str]
    actual_ids: list[str]
    missing_ids: list[str]
    unexpected_ids: list[str]
    recall: float
    precision: float

    @property
    def passed(self) -> bool:
        return not self.missing_ids

    def to_dict(self) -> dict:
        return {
            "group": self.group,
            "expected_ids": self.expected_ids,
            "actual_ids": self.actual_ids,
            "missing_ids": self.missing_ids,
            "unexpected_ids": self.unexpected_ids,
            "recall": self.recall,
            "precision": self.precision,
            "passed": self.passed,
        }


@dataclass
class MemoryEvalScenarioResult:
    scenario_id: str
    description: str
    groups: list[MemoryEvalGroupResult]

    @property
    def passed(self) -> bool:
        return all(group.passed for group in self.groups)

    @property
    def recall(self) -> float:
        expected = sum(len(group.expected_ids) for group in self.groups)
        found = sum(
            len(set(group.expected_ids).intersection(group.actual_ids))
            for group in self.groups
        )
        return found / expected if expected else 1.0

    @property
    def precision(self) -> float:
        actual = sum(len(group.actual_ids) for group in self.groups)
        relevant = sum(
            len(set(group.expected_ids).intersection(group.actual_ids))
            for group in self.groups
        )
        return relevant / actual if actual else 1.0

    def to_dict(self) -> dict:
        return {
            "scenario_id": self.scenario_id,
            "description": self.description,
            "passed": self.passed,
            "recall": self.recall,
            "precision": self.precision,
            "groups": [group.to_dict() for group in self.groups],
        }


@dataclass
class MemoryEvalSuiteResult:
    scenarios: list[MemoryEvalScenarioResult]

    @property
    def passed(self) -> bool:
        return all(scenario.passed for scenario in self.scenarios)

    @property
    def recall(self) -> float:
        if not self.scenarios:
            return 1.0
        return sum(scenario.recall for scenario in self.scenarios) / len(self.scenarios)

    @property
    def precision(self) -> float:
        if not self.scenarios:
            return 1.0
        return sum(scenario.precision for scenario in self.scenarios) / len(self.scenarios)

    def to_dict(self) -> dict:
        return {
            "passed": self.passed,
            "recall": self.recall,
            "precision": self.precision,
            "scenarios": [scenario.to_dict() for scenario in self.scenarios],
        }


def load_memory_eval_scenarios(path: Path) -> list[MemoryEvalScenario]:
    payload = json.loads(path.read_text())
    return [
        MemoryEvalScenario(
            id=item["id"],
            description=item.get("description", ""),
            query=item["query"],
            symbols=item.get("symbols", []),
            k_per_group=item.get("k_per_group", 4),
            documents=item.get("documents", []),
            expected=item.get("expected", {}),
        )
        for item in payload
    ]


def evaluate_memory_retrieval(
    scenarios: list[MemoryEvalScenario],
    retriever_factory,
) -> MemoryEvalSuiteResult:
    return MemoryEvalSuiteResult(
        scenarios=[
            evaluate_memory_scenario(scenario, retriever_factory(scenario))
            for scenario in scenarios
        ]
    )


def evaluate_memory_scenario(
    scenario: MemoryEvalScenario,
    retriever: GroupedRetriever,
) -> MemoryEvalScenarioResult:
    grouped = retriever.retrieve_grouped(
        query=scenario.query,
        symbols=scenario.symbols,
        k_per_group=scenario.k_per_group,
    )
    return MemoryEvalScenarioResult(
        scenario_id=scenario.id,
        description=scenario.description,
        groups=[
            evaluate_group(
                group=group,
                expected_ids=expected_ids,
                actual_ids=[
                    memory.get("id")
                    for memory in grouped.get(group, [])
                    if memory.get("id")
                ],
            )
            for group, expected_ids in scenario.expected.items()
        ],
    )


def evaluate_group(
    *,
    group: str,
    expected_ids: list[str],
    actual_ids: list[str],
) -> MemoryEvalGroupResult:
    expected_set = set(expected_ids)
    actual_set = set(actual_ids)
    missing_ids = [memory_id for memory_id in expected_ids if memory_id not in actual_set]
    unexpected_ids = [memory_id for memory_id in actual_ids if memory_id not in expected_set]
    found = len(expected_set.intersection(actual_set))
    return MemoryEvalGroupResult(
        group=group,
        expected_ids=expected_ids,
        actual_ids=actual_ids,
        missing_ids=missing_ids,
        unexpected_ids=unexpected_ids,
        recall=found / len(expected_set) if expected_set else 1.0,
        precision=found / len(actual_set) if actual_set else 1.0,
    )

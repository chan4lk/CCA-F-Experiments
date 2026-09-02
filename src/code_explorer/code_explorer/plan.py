"""Adaptive decomposition.

A fixed pipeline is right when the steps are known in advance. "Add tests to this legacy
package" is not that: what to do in step three depends on what step one found. So the plan
is a structure that grows - map, rank, then tasks generated from what the ranking exposed,
and re-ranked as dependencies surface.
"""

from dataclasses import dataclass, field

MAP = "map"
RANK = "rank"
WORK = "work"


@dataclass
class Task:
    question: str
    why: str
    weight: int = 1
    done: bool = False
    blocked_by: list[str] = field(default_factory=list)


@dataclass
class Investigation:
    goal: str
    phase: str = MAP
    tasks: list[Task] = field(default_factory=list)

    def add(self, question: str, why: str, weight: int = 1, blocked_by: list[str] | None = None) -> Task:
        task = Task(question, why, weight, blocked_by=blocked_by or [])
        self.tasks.append(task)
        return task

    def complete(self, question: str) -> None:
        for task in self.tasks:
            if task.question == question:
                task.done = True
        for task in self.tasks:
            task.blocked_by = [b for b in task.blocked_by if b != question]

    @property
    def ready(self) -> list[Task]:
        """Highest weight first. Re-read after every completion, because completing one
        task both unblocks others and changes what is worth doing next."""
        return sorted(
            (t for t in self.tasks if not t.done and not t.blocked_by),
            key=lambda t: (-t.weight, t.question),
        )

    @property
    def blocked(self) -> list[Task]:
        return [t for t in self.tasks if not t.done and t.blocked_by]

    @property
    def open_questions(self) -> list[str]:
        return [t.question for t in self.tasks if not t.done]

    def advance(self) -> str:
        if self.phase == MAP:
            self.phase = RANK
        elif self.phase == RANK:
            self.phase = WORK
        return self.phase

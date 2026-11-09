"""Task model."""

from dataclasses import dataclass
from datetime import datetime
from typing import Optional


@dataclass
class Task:
    id: int
    title: str
    description: str = ""
    project_id: int = None
    done: bool = False
    priority: str = "medium"
    tags: list = None
    due_date: Optional[str] = None
    created_at: str = None
    completed_at: Optional[str] = None

    def __post_init__(self):
        if self.tags is None:
            self.tags = []
        if self.created_at is None:
            self.created_at = datetime.now().isoformat()

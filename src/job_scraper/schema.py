import json
from typing import Any

from pydantic import BaseModel


class JobData(BaseModel):
    url: str
    title: str
    company: str
    description: dict[str, Any]

    @property
    def row(self) -> tuple[str, str, str, str]:
        return (
            self.url,
            self.title,
            self.company,
            json.dumps(self.description)
        )

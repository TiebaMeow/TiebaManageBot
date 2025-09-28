from pydantic import BaseModel


class Config(BaseModel, extra="ignore"):
    """Plugin Config Here"""

    api_token: str | None = None

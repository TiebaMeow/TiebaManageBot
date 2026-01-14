from urllib.parse import quote_plus

from pydantic import BaseModel, PostgresDsn, RedisDsn, computed_field, model_validator


class Config(BaseModel):
    redis_host: str
    redis_port: int
    redis_username: str = ""
    redis_password: str = ""
    redis_db: int = 0
    redis_stream_prefix: str = "scraper:tieba:events"
    redis_channel: str = "reviewer:rules:update"

    addon_pg_host: str
    addon_pg_port: int
    addon_pg_username: str
    addon_pg_password: str
    addon_pg_db: str

    @model_validator(mode="before")
    @classmethod
    def compatible_type(cls, values: dict) -> dict:
        """兼容 eval 从环境变量读取的整数类型字段"""
        int_fields = [
            "addon_pg_password",
        ]
        for field in int_fields:
            if field in values and isinstance(values[field], int):
                values[field] = str(values[field])
        return values

    @computed_field
    @property
    def database_url(self) -> PostgresDsn:
        """生成PostgreSQL数据库连接URL"""
        return PostgresDsn(
            f"postgresql+asyncpg://{quote_plus(self.addon_pg_username)}:{quote_plus(self.addon_pg_password)}"
            f"@{self.addon_pg_host}:{self.addon_pg_port}/{self.addon_pg_db}"
        )

    @computed_field
    @property
    def redis_url(self) -> RedisDsn:
        """生成Redis连接URL"""
        if self.redis_username and self.redis_password:
            return RedisDsn(
                f"redis://{quote_plus(self.redis_username)}:{quote_plus(self.redis_password)}"
                f"@{self.redis_host}:{self.redis_port}/{self.redis_db}"
            )
        if self.redis_password:
            return RedisDsn(
                f"redis://:{quote_plus(self.redis_password)}@{self.redis_host}:{self.redis_port}/{self.redis_db}"
            )
        return RedisDsn(f"redis://{self.redis_host}:{self.redis_port}/{self.redis_db}")

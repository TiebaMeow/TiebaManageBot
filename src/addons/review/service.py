from sqlalchemy import select

from src.db import ReviewConfig, get_session


async def get_existing_keywords(fid: int, keywords: list[str]) -> list[str]:
    async with get_session() as session:
        existing_keywords = await session.execute(
            select(ReviewConfig.rule_content).where(
                ReviewConfig.fid == fid,
                ReviewConfig.rule_type == "关键词",
                ReviewConfig.rule_content.in_(keywords),
            )
        )
        return list(existing_keywords.scalars().all())


async def add_keyword_config(fid: int, group_id: int, keyword: str, notify_type: str) -> None:
    async with get_session() as session:
        config = ReviewConfig(
            fid=fid,
            group_id=group_id,
            rule_type="关键词",
            notify_type=notify_type,
            rule_content=keyword,
        )
        session.add(config)
        await session.commit()


async def get_existing_users(fid: int, user_ids: list[str]) -> list[str]:
    async with get_session() as session:
        existing_users = await session.execute(
            select(ReviewConfig.rule_content).where(
                ReviewConfig.fid == fid,
                ReviewConfig.rule_type == "监控用户",
                ReviewConfig.rule_content.in_(user_ids),
            )
        )
        return list(existing_users.scalars().all())


async def add_user_config(fid: int, group_id: int, user_id: str, notify_type: str) -> None:
    async with get_session() as session:
        config = ReviewConfig(
            fid=fid,
            group_id=group_id,
            rule_type="监控用户",
            notify_type=notify_type,
            rule_content=user_id,
        )
        session.add(config)
        await session.commit()

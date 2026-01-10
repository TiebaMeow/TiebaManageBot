from collections.abc import AsyncGenerator, Sequence

from sqlalchemy import select
from tiebameow.models.orm import ReviewRules
from tiebameow.schemas.rules import ReviewRule, RuleNode, TargetType

from src.db.session import get_session


async def get_rules(fid: int) -> AsyncGenerator[ReviewRules, None]:
    async with get_session() as session:
        result = await session.execute(
            select(ReviewRules).where(ReviewRules.fid == fid).order_by(ReviewRules.forum_rule_id.asc())
        )
        for record in result.scalars():
            yield record


async def get_existing_rule(fid: int, target_type: TargetType, rule: RuleNode) -> ReviewRules | None:
    async with get_session() as session:
        result = await session.execute(
            select(ReviewRules).where(
                ReviewRules.fid == fid, ReviewRules.target_type == target_type, ReviewRules.trigger == rule
            )
        )
        return result.scalar_one_or_none()


async def get_existing_rules(fid: int, target_type: TargetType, rules: Sequence[RuleNode]) -> list[ReviewRules]:
    async with get_session() as session:
        result = await session.execute(
            select(ReviewRules).where(
                ReviewRules.fid == fid, ReviewRules.target_type == target_type, ReviewRules.trigger.in_(rules)
            )
        )
        return list(result.scalars().all())


async def get_max_forum_rule_id(fid: int) -> int:
    async with get_session() as session:
        result = await session.execute(
            select(ReviewRules.forum_rule_id)
            .where(ReviewRules.fid == fid)
            .order_by(ReviewRules.forum_rule_id.desc())
            .limit(1)
        )
        max_forum_rule_id = result.scalar_one_or_none()
        return max_forum_rule_id if max_forum_rule_id is not None else 0


async def add_rule(rule: ReviewRule) -> None:
    async with get_session() as session:
        session.add(ReviewRules.from_rule_data(rule))
        await session.commit()

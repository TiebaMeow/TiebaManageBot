from pydantic import BaseModel


class Config(BaseModel):
    """Plugin Config Here"""

    ignore_users: list[int] = []
    checkout_tieba: str = (
        "原神,原神内鬼,崩坏三,崩坏3rd,崩坏星穹铁道,星穹铁道内鬼,mihoyo,新mihoyo,尘白禁区,ml游戏,有男不玩ml,"
        "千年之旅,有男偷玩,二游笑话,dinner笑话,明日方舟,明日方舟内鬼,明日方舟dl,明日方舟pl,淋日方舟,"
        "血狼破军,快乐雪花,半壁江山雪之下,碧蓝航线,碧蓝航线2,异色格,赤色中轴,少女前线,少女前线2,"
        "少女前线r,蔚蓝档案,碧蓝档案,碧蓝档案吐槽,鸣潮,鸣潮内鬼,旧鸣潮内鬼,新鸣潮内鬼,鸣潮内鬼爆料,"
        "北落野,灵魂潮汐,无期迷途"
    )

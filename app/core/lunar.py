"""公历日期 -> 农历信息（基于 lunar-python）。

只暴露业务真正需要的两个字段：农历文本与当天节气 / 节日，
避免把库里的干支、生肖、宜忌等明细全部透出到接口。
"""

from datetime import date, datetime, time
from typing import NamedTuple

from lunar_python import Solar


class LunarInfo(NamedTuple):
    """某一天的农历信息。"""

    text: str  # 农历日期，如 "四月十五"；闰月形如 "闰四月十五"
    festival: str  # 节气或节日，如 "小满" / "端午节"，没有则为空串


def to_lunar(day: date) -> LunarInfo:
    """把公历日期换算成农历信息。

    `Solar.fromDate` 只接受 datetime（内部要读 hour/minute/second），
    所以这里先补一个零点时间再转换。
    """
    solar = Solar.fromDate(datetime.combine(day, time.min))
    lunar = solar.getLunar()

    # getMonth() 为负数表示该月是闰月
    month = lunar.getMonth()
    month_text = ("闰" if month < 0 else "") + lunar.getMonthInChinese()

    # 优先取节气，其次农历节日 / 传统节日，最后公历节日
    festival = lunar.getJieQi() or ""
    if not festival:
        festivals = (
            list(lunar.getFestivals())
            + list(lunar.getOtherFestivals())
            + list(solar.getFestivals())
        )
        festival = festivals[0] if festivals else ""

    # getMonthInChinese() 只返回 "四" / "十"，需要自行补 "月"
    return LunarInfo(text=f"{month_text}月{lunar.getDayInChinese()}", festival=festival)

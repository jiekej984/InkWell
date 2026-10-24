"""角色库枚举与中文标签（V2.0 / 任务 5.2）。

**唯一来源**：服务层、接口层（#54 元数据）与测试都从这里取，避免五个服务各写一份
标签表、慢慢漂移。

> 实现说明：任务清单原写「5 个服务模块」，实际多出本文件。原因是枚举要同时被
> ``character`` / ``relation`` / ``organization`` / ``faction`` / ``graph`` 五个服务
> 引用，若挂在其中任一服务上会造成循环导入；抽成独立常量模块最省事。
"""

from __future__ import annotations

# --------------------------------------------------------------------------
# 角色
# --------------------------------------------------------------------------

ROLES: tuple[str, ...] = (
    "protagonist",
    "heroine",
    "supporting",
    "antagonist",
    "extra",
    "other",
)
ROLE_LABELS = {
    "protagonist": "主角",
    "heroine": "女主",
    "supporting": "重要配角",
    "antagonist": "反派",
    "extra": "龙套",
    "other": "其他",
}

STATUSES: tuple[str, ...] = ("alive", "dead", "missing", "retired")
STATUS_LABELS = {
    "alive": "存活",
    "dead": "已死",
    "missing": "失踪",
    "retired": "退场",
}

FIELD_TYPES: tuple[str, ...] = ("text", "longtext", "number", "date")
FIELD_TYPE_LABELS = {
    "text": "单行文本",
    "longtext": "长文本",
    "number": "数字",
    "date": "日期",
}

# 卡片上的固定字段（键名即数据库列名，V3.0 的 AI 输出直接用这些 key）
CHARACTER_FIELD_LABELS = {
    "name": "姓名",
    "role": "定位",
    "gender": "性别",
    "age": "年龄",
    "height": "身高",
    "appearance": "外貌",
    "personality": "性格",
    "background": "背景",
    "abilities": "能力/技能",
    "catchphrase": "口头禅",
    "motivation": "目标动机",
    "status": "当前状态",
    "tags": "标签",
    "note": "备注",
}

SORTS: tuple[str, ...] = ("order", "created", "name")
SORT_LABELS = {"order": "自定义顺序", "created": "创建时间", "name": "姓名"}

# --------------------------------------------------------------------------
# 角色关系（20 类）
# --------------------------------------------------------------------------

RELATION_TYPES: tuple[str, ...] = (
    "master",
    "parent",
    "child",
    "sibling",
    "spouse",
    "partner",
    "lover",
    "friend",
    "ally",
    "fellow",
    "superior",
    "servant",
    "rival",
    "enemy",
    "blood_feud",
    "compete",
    "betray",
    "benefactor",
    "kin",
    "other",
)
RELATION_LABELS = {
    "master": "师徒",
    "parent": "父母",
    "child": "子女",
    "sibling": "兄弟姐妹",
    "spouse": "夫妻",
    "partner": "道侣",
    "lover": "恋人",
    "friend": "朋友",
    "ally": "盟友",
    "fellow": "同门",
    "superior": "上下级",
    "servant": "主仆",
    "rival": "宿敌",
    "enemy": "仇人",
    "blood_feud": "血仇",
    "compete": "竞争",
    "betray": "背叛",
    "benefactor": "恩人",
    "kin": "同族",
    "other": "其他",
}

# 表单默认方向（1 = 双向）；逐条可覆盖
RELATION_DEFAULT_BIDIRECTIONAL = {
    "master": 0,
    "parent": 0,
    "child": 0,
    "sibling": 1,
    "spouse": 1,
    "partner": 1,
    "lover": 1,
    "friend": 1,
    "ally": 1,
    "fellow": 1,
    "superior": 0,
    "servant": 0,
    "rival": 1,
    "enemy": 1,
    "blood_feud": 1,
    "compete": 1,
    "betray": 0,
    "benefactor": 0,
    "kin": 1,
    "other": 1,
}

# 图上的五大色系（前端据此上色，见 5.0 走查基线 §6.2）
RELATION_FAMILIES = {
    "master": "master",
    "fellow": "master",
    "parent": "kin",
    "child": "kin",
    "sibling": "kin",
    "spouse": "kin",
    "partner": "kin",
    "lover": "kin",
    "kin": "kin",
    "friend": "friend",
    "ally": "friend",
    "benefactor": "friend",
    "rival": "enemy",
    "enemy": "enemy",
    "blood_feud": "enemy",
    "betray": "enemy",
    "superior": "other",
    "servant": "other",
    "compete": "other",
    "other": "other",
}

# --------------------------------------------------------------------------
# 组织与大立场
# --------------------------------------------------------------------------

ORG_KINDS: tuple[str, ...] = ("sect", "family", "court", "guild", "army", "other")
ORG_KIND_LABELS = {
    "sect": "宗门",
    "family": "家族",
    "court": "朝堂",
    "guild": "帮派",
    "army": "军队",
    "other": "其他",
}

ORG_RELATION_TYPES: tuple[str, ...] = ("vassal", "ally", "enemy", "war", "neutral")
ORG_RELATION_LABELS = {
    "vassal": "从属",
    "ally": "结盟",
    "enemy": "敌对",
    "war": "战争",
    "neutral": "中立",
}

FACTION_RELATION_TYPES: tuple[str, ...] = ("ally", "enemy", "neutral", "vassal")
FACTION_RELATION_LABELS = {
    "ally": "结盟",
    "enemy": "敌对",
    "neutral": "中立",
    "vassal": "从属",
}


def _options(values: tuple[str, ...], labels: dict[str, str]) -> list[dict[str, str]]:
    return [{"value": value, "label": labels[value]} for value in values]


def meta_payload() -> dict:
    """§6.2 #54：全部枚举与中文标签（一次取完，前端不硬编码）。"""
    return {
        "roles": _options(ROLES, ROLE_LABELS),
        "statuses": _options(STATUSES, STATUS_LABELS),
        "relation_types": [
            {
                "value": value,
                "label": RELATION_LABELS[value],
                "family": RELATION_FAMILIES[value],
                "default_bidirectional": RELATION_DEFAULT_BIDIRECTIONAL[value],
            }
            for value in RELATION_TYPES
        ],
        "field_types": _options(FIELD_TYPES, FIELD_TYPE_LABELS),
        "organization_kinds": _options(ORG_KINDS, ORG_KIND_LABELS),
        "organization_relation_types": _options(
            ORG_RELATION_TYPES, ORG_RELATION_LABELS
        ),
        "faction_relation_types": _options(
            FACTION_RELATION_TYPES, FACTION_RELATION_LABELS
        ),
        "character_field_labels": dict(CHARACTER_FIELD_LABELS),
        "sorts": _options(SORTS, SORT_LABELS),
    }

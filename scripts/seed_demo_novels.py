"""生成三本示例小说（V2.0 验收/手测用）。

三本密度不同：
  · 《折枝录》  小：4 角色 / 1 组织 / 1 阵营 / 3 章
  · 《雾港旧事》中：10 角色 / 4 组织 / 2 阵营 / 8 章 / 2 文档
  · 《天穹之外》大：18 角色 / 6 组织 / 3 阵营 / 20 章 / 2 文档 / 关系含失效与隐秘

全部标记「示例」标签，可在应用里直接删除（回收站）。脚本可重复执行：
已存在的同名书会跳过，不会重复生成。

用法::

    .venv\\Scripts\\python.exe scripts/seed_demo_novels.py --data-dir data
    # 先看效果可写到临时目录：
    .venv\\Scripts\\python.exe scripts/seed_demo_novels.py --data-dir .demo-data
"""

from __future__ import annotations

import argparse
import os
import shutil
import sys
from dataclasses import replace
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

TAG = "示例"


def _html(*paragraphs: str) -> str:
    return "".join(f"<p>{text}</p>" for text in paragraphs)


# --------------------------------------------------------------------------
# 公共小工具
# --------------------------------------------------------------------------


def _project(session, project_service, title: str, description: str):
    project = project_service.create_project(
        session,
        title=title,
        description=description,
        tag_names=[TAG],
    )
    return int(project.id)


def _volume(session, chapter_service, project_id: int, title: str, rows):
    volume = chapter_service.create_volume(session, project_id, title=title)
    chapter_ids = []
    for chapter_title, paragraphs in rows:
        chapter = chapter_service.create_chapter(
            session, int(volume.id), title=chapter_title
        )
        if paragraphs:
            chapter_service.save_chapter_content(
                session,
                int(chapter.id),
                content_html=_html(*paragraphs),
            )
        chapter_ids.append(int(chapter.id))
    return chapter_ids


def _faction(session, faction_service, project_id: int, name: str, **fields):
    row = faction_service.create_faction(session, project_id, name=name, **fields)
    return int(row.id)


def _org(session, organization_service, project_id: int, name: str, **fields):
    row = organization_service.create_organization(
        session, project_id, name=name, **fields
    )
    return int(row.id)


def _char(session, character_service, project_id: int, name: str, **fields):
    tags = fields.get("tags")
    if isinstance(tags, str):
        fields["tags"] = [
            item.strip() for item in tags.replace("，", ",").split(",") if item.strip()
        ]
    row = character_service.create_character(session, project_id, name=name, **fields)
    return int(row.id)


def _member(
    session,
    organization_service,
    org_id: int,
    character_id: int,
    *,
    position: str | None = None,
    primary: bool = False,
    secret: bool = False,
    from_chapter: int | None = None,
):
    organization_service.add_member(
        session,
        org_id,
        character_id=character_id,
        position=position,
        is_primary=primary,
        is_secret=secret,
        from_chapter_id=from_chapter,
    )


def _rel(
    session,
    relation_service,
    from_id: int,
    to_id: int,
    relation_type: str,
    **fields,
):
    relation_service.create_character_relation(
        session,
        from_id,
        to_id=to_id,
        relation_type=relation_type,
        **fields,
    )


def _doc(session, document_service, project_id: int, title: str, category: str, body: str):
    document_service.create_document(
        session,
        project_id,
        title=title,
        category=category,
        content_html=body,
    )


# --------------------------------------------------------------------------
# 一本：折枝录（小）
# --------------------------------------------------------------------------


def seed_zhezhi(session, services) -> int:
    project_id = _project(
        session,
        services["project"],
        "折枝录",
        "深宅里，姐妹和一株梅的旧事。示例数据，可随时删除。",
    )
    _volume(
        session,
        services["chapter"],
        project_id,
        "卷一·折枝",
        [
            (
                "一 梅开",
                [
                    "沈府的梅开了。沈令仪站在廊下，看仆妇们把花枝上的雪一点点扫下来。",
                    "她记得母亲说过，梅要经一场雪才香。今年这场雪，来得比母亲走的那年还迟。",
                ],
            ),
            (
                "二 夜宴",
                [
                    "夜宴上，裴砚来了。他如今是翰林院的编修，衣袍换成了青色，笑起来还是从前那样温和。",
                    "沈令姜隔着半张桌子看他，手里的汤匙停在半空，被崔嬷嬷轻轻按了一下。",
                ],
            ),
            (
                "三 折枝",
                [
                    "第二日清晨，梅树最盛的那一枝断了。断口很齐，像是被人用剪子铰过。",
                    "沈令仪没有问是谁。她只是把断枝插进母亲留下的旧瓶里，关上了窗。",
                ],
            ),
        ],
    )

    faction = _faction(
        session,
        services["faction"],
        project_id,
        "世家",
        color="#7a6a58",
        description="门阀世家，重礼法、讲嫡庶。",
    )
    _doc(
        session,
        services["document"],
        project_id,
        "沈府族谱",
        "world",
        _html(
            "沈氏三代居于此地，以漕运起家，如今只余一座旧宅和几百亩祭田。",
            "嫡支一脉，到沈令仪这一辈，只剩两个女儿。",
        ),
    )

    lingyi = _char(
        session,
        services["character"],
        project_id,
        "沈令仪",
        role="protagonist",
        gender="女",
        age="十九",
        height="一六四",
        tags="嫡女,冷性,掌家",
        appearance="眉目清淡，常穿月白，手腕上有一道旧疤。",
        personality="克制，记仇，不肯在人前掉眼泪。",
        background="十三岁母亲病故，从此学着掌家，账本比诗书熟。",
        hobbies="莳花、抄经",
        skills="女红、算账、看人",
        motivation="守住母亲留下的那株梅树。",
        quote="梅若要开，谁也拦不住。",
        note="原型来自旧稿《折枝》，名字保留。",
    )
    lingjiang = _char(
        session,
        services["character"],
        project_id,
        "沈令姜",
        role="supporting",
        gender="女",
        age="十七",
        tags="庶妹,怯懦",
        appearance="眉眼更软，说话时总先低头。",
        personality="表面柔顺，心里有火。",
        background="生母是旧时丫鬟，自小活在嫡姐的影子里。",
        motivation="想被人认真看见一次。",
    )
    nanny = _char(
        session,
        services["character"],
        project_id,
        "崔嬷嬷",
        role="extra",
        gender="女",
        age="五十五",
        tags="奶娘,旧仆",
        personality="嘴严，心软。",
        background="沈令仪的奶娘，母亲走后留下来看院子。",
    )
    pei = _char(
        session,
        services["character"],
        project_id,
        "裴砚",
        role="antagonist",
        gender="男",
        age="二十二",
        tags="探花,婚约",
        appearance="清瘦，常穿青衫，说话慢。",
        personality="温文，实际每一步都算过。",
        background="寒门出身，靠沈家旧交得以进学，如今是翰林院编修。",
        motivation="往上走，不再看人脸色。",
    )

    services["character"].set_aliases(session, lingyi, ["阿仪"])
    services["character"].set_aliases(session, lingjiang, ["姜儿"])
    services["character"].add_field(session, lingyi, key="生辰", value="腊月初七")
    services["character"].add_field(session, lingjiang, key="生辰", value="三月初三")
    services["character"].add_field(session, pei, key="官职", value="翰林院编修")

    shen_house = _org(
        session,
        services["organization"],
        project_id,
        "沈府",
        kind="family",
        faction_id=faction,
        leader_id=lingyi,
        description="三代旧宅，人口不多，规矩不少。",
    )
    _member(
        session,
        services["organization"],
        shen_house,
        lingyi,
        position="嫡长女",
        primary=True,
    )
    _member(session, services["organization"], shen_house, lingjiang, position="庶女")
    _member(session, services["organization"], shen_house, nanny, position="奶娘")

    _rel(session, services["relation"], lingyi, lingjiang, "sibling",
         description="同父异母，明面上客气。")
    _rel(session, services["relation"], lingyi, pei, "spouse",
         description="自幼定亲，尚未过门。")
    _rel(session, services["relation"], lingjiang, pei, "lover",
         is_secret=True, is_bidirectional=False, description="暗生情愫，无人知晓。")
    _rel(session, services["relation"], nanny, lingyi, "other",
         custom_label="奶娘", description="把大小姐当半个女儿看。")
    return project_id


# --------------------------------------------------------------------------
# 二本：雾港旧事（中）
# --------------------------------------------------------------------------


def seed_wugang(session, services) -> int:
    project_id = _project(
        session,
        services["project"],
        "雾港旧事",
        "民国港口，一本账、一条船和一桩旧案。示例数据，可随时删除。",
    )
    volume_one = _volume(
        session,
        services["chapter"],
        project_id,
        "卷一·潮声",
        [
            (
                "一 雾里账本",
                [
                    "雾从海面漫上来，把码头的灯一盏盏吞掉。沈砚舟在账房里拨算盘，最后一颗珠子落下去，数不对。",
                    "他抬头看了一眼货单，又低头看账。差了三百二十块大洋，正好是一条船的卸货钱。",
                ],
            ),
            (
                "二 码头火并",
                [
                    "枪声响在午夜。沈砚舟赶到时，三号泊位已经烧起来，陈伯抱着一条断缆站在雨里。",
                    "有人喊青帮的人跑了。沈砚舟看见陆九爷的乌木烟斗掉在跳板上，烟锅里还有一点红。",
                ],
            ),
            (
                "三 报馆来客",
                [
                    "顾云绮第一次来账房，带了一台蔡司折叠机。她说不拍照，只想核对一份货单。",
                    "沈砚舟把账本推过去。她看得很快，手指停在父亲名字那一行，停了很久。",
                ],
            ),
            (
                "四 失踪的船",
                [
                    "「顺安号」出港第三天，没有回来。港务局的记录写着「机器故障」，可郑副官把那一页撕得很整齐。",
                    "沈砚舟开始怀疑，父亲当年的死，也许不是意外。",
                ],
            ),
        ],
    )
    volume_two = _volume(
        session,
        services["chapter"],
        project_id,
        "卷二·雾锁",
        [
            (
                "五 青帮堂口",
                [
                    "陆九爷在堂口请他喝茶。茶是好茶，话说得很客气，意思是让他别再查。",
                    "沈砚舟低头应了，出门才发现后背全湿。那枚旧铜戒在袖口里硌得生疼。",
                ],
            ),
            (
                "六 白探长的条件",
                [
                    "白探长约在巡捕房后巷。他要一份青帮走货的名单，作为交换，可以让他看一眼旧卷宗。",
                    "顾云绮站在街对面，装作买烟。沈砚舟知道她也听见了。",
                ],
            ),
            (
                "七 阿棠看见的",
                [
                    "阿棠说，火并那晚她看见郑副官从青帮的船上下来，手里提着一只铁皮箱。",
                    "她还说，箱子里有会响的东西，像是钟表。",
                ],
            ),
            (
                "八 潮退之后",
                [
                    "潮水退去，三号泊位的焦木头露出水面。沈砚舟在灰里找到半张货单，字迹是父亲的。",
                    "他把货单折好，放进贴身的衣袋。雾散了，港口比从前更清楚，也更冷。",
                ],
            ),
        ],
    )
    chapter_ids = volume_one + volume_two

    court = _faction(
        session,
        services["faction"],
        project_id,
        "官府",
        color="#3b6ea5",
        description="缉私、收税，讲的是体面。",
    )
    gang = _faction(
        session,
        services["faction"],
        project_id,
        "青帮",
        color="#8b3a4a",
        description="码头的船，一半听官，一半听九爷。",
    )
    _doc(
        session,
        services["document"],
        project_id,
        "雾港地理志",
        "world",
        _html(
            "雾港因雾得名，一年有三个月看不清对岸。港分内外两区：外区归港务局，内区归青帮。",
            "三号泊位是最旧的码头，也是货最多的地方。",
        ),
    )
    _doc(
        session,
        services["document"],
        project_id,
        "青帮家规",
        "faction",
        _html(
            "入帮要拜香堂，辈分写在帖子上。",
            "帮里不认钱，只认话。九爷的一句话，比港务局的公文管用。",
        ),
    )

    shen = _char(
        session,
        services["character"],
        project_id,
        "沈砚舟",
        role="protagonist",
        gender="男",
        age="二十八",
        height="一八二",
        tags="账房,查案",
        appearance="清瘦，左手常年戴一枚旧铜戒。",
        personality="谨慎，记账成癖，话不多。",
        background="父亲死在码头火并，他在港务局账房长大，算得一手好账。",
        hobbies="修算盘、听潮",
        skills="心算、看账、粗浅拳脚",
        motivation="查清父亲当年的死因。",
        quote="账不对，人就一定不对。",
    )
    gu = _char(
        session,
        services["character"],
        project_id,
        "顾云绮",
        role="heroine",
        gender="女",
        age="二十四",
        height="一六八",
        tags="记者,锋利",
        appearance="短发，常穿男式西装，肩上背一台旧相机。",
        personality="锋利，不肯绕弯，认定的事一定追到底。",
        background="大公报馆记者，专写码头和法院。",
        skills="速记、拍照、套话",
        motivation="把顺安号的真相登在头版。",
        quote="新闻等不起雾散。",
    )
    lu = _char(
        session,
        services["character"],
        project_id,
        "陆九爷",
        role="antagonist",
        gender="男",
        age="四十六",
        height="一七五",
        tags="青帮,堂主",
        appearance="圆脸，手里总有一把乌木烟斗。",
        personality="笑面，狠，讲规矩。",
        background="青帮码头堂主，靠走私和码头费起家。",
        motivation="守住码头，也守住自己的位置。",
        quote="码头的规矩，比官府的纸管用。",
    )
    chen = _char(
        session,
        services["character"],
        project_id,
        "陈伯",
        role="supporting",
        gender="男",
        age="六十一",
        tags="老工,护短",
        appearance="背驼，手上有洗不掉的机油。",
        personality="寡言，护短。",
        background="在码头修了四十年船，认得沈砚舟的父亲。",
        skills="修船、看潮、认人",
    )
    atang = _char(
        session,
        services["character"],
        project_id,
        "阿棠",
        role="supporting",
        gender="女",
        age="十九",
        tags="拾荒,记路",
        appearance="瘦，赤脚，头发用布条扎着。",
        personality="野，记路，谁给过她半个馒头都记得。",
        background="在码头拾荒长大，没有名字，阿棠是她自己起的。",
    )
    bai = _char(
        session,
        services["character"],
        project_id,
        "白探长",
        role="supporting",
        gender="男",
        age="三十九",
        tags="探长,交易",
        appearance="总把礼帽压低，说话时先看人身后。",
        personality="讲条件，怕事，但还留一点底线。",
        background="租界巡捕房探长，和青帮有旧账。",
    )
    wen = _char(
        session,
        services["character"],
        project_id,
        "温老板",
        role="extra",
        gender="男",
        age="五十二",
        tags="当铺,洗钱",
        appearance="胖，笑起来眼睛没了。",
        personality="和气生财，谁的钱都收。",
        background="开当铺，替青帮走账。",
    )
    xiaoman = _char(
        session,
        services["character"],
        project_id,
        "小满",
        role="extra",
        gender="女",
        age="十二",
        tags="报童,嘴快",
        appearance="戴一顶大帽子，跑起来鞋底带泥。",
        personality="嘴快，胆子大。",
        background="报馆门口卖报，顾云绮常给她留饭。",
    )
    zheng = _char(
        session,
        services["character"],
        project_id,
        "郑副官",
        role="supporting",
        gender="男",
        age="三十三",
        tags="缉私队,势利",
        appearance="制服笔挺，皮鞋总是亮的。",
        personality="势利，贪，见风使舵。",
        background="缉私队副官，替青帮放船，也替港务局背账。",
    )
    song = _char(
        session,
        services["character"],
        project_id,
        "宋先生",
        role="extra",
        gender="男",
        age="四十",
        tags="旧账房,胆小",
        appearance="戴一副圆眼镜，手指常沾墨。",
        personality="胆小，账目清楚，从不问东家的事。",
        background="温老板当铺的账房。",
    )

    services["character"].add_field(session, shen, key="算盘", value="十三档旧算盘")
    services["character"].add_field(session, gu, key="相机", value="蔡司折叠机")
    services["character"].add_field(session, lu, key="烟斗", value="乌木烟斗")
    services["character"].set_aliases(session, shen, ["沈账房"])
    services["character"].set_aliases(session, gu, ["小顾"])
    services["character"].set_aliases(session, lu, ["九爷"])

    port_office = _org(
        session,
        services["organization"],
        project_id,
        "港务局",
        kind="court",
        faction_id=court,
        description="管外区码头、货单和税。",
    )
    anti_smuggle = _org(
        session,
        services["organization"],
        project_id,
        "缉私队",
        kind="army",
        faction_id=court,
        parent_id=port_office,
        description="港务局的枪，名义上查私货。",
    )
    gang_hall = _org(
        session,
        services["organization"],
        project_id,
        "青帮堂口",
        kind="guild",
        faction_id=gang,
        leader_id=lu,
        description="码头真正的规矩。",
    )
    police = _org(
        session,
        services["organization"],
        project_id,
        "巡捕房",
        kind="court",
        description="租界的警，谁的面子都卖一点。",
    )
    news = _org(
        session,
        services["organization"],
        project_id,
        "大公报馆",
        kind="guild",
        leader_id=gu,
        description="港城唯一敢登码头案子的报馆。",
    )

    _member(session, services["organization"], port_office, shen, position="账房", primary=True)
    _member(session, services["organization"], port_office, chen, position="老工")
    _member(session, services["organization"], anti_smuggle, zheng, position="副官", primary=True)
    _member(session, services["organization"], gang_hall, lu, position="堂主", primary=True)
    _member(session, services["organization"], gang_hall, wen, position="白纸扇", secret=True)
    _member(session, services["organization"], gang_hall, shen, position="门外弟子", secret=True)
    _member(session, services["organization"], police, bai, position="探长", primary=True)
    _member(session, services["organization"], news, gu, position="记者", primary=True)

    services["organization"].create_org_relation(
        session,
        project_id,
        from_id=anti_smuggle,
        to_id=gang_hall,
        relation_type="enemy",
        description="缉私队查青帮的船，青帮查缉私队的账。",
    )
    services["organization"].create_org_relation(
        session,
        project_id,
        from_id=port_office,
        to_id=gang_hall,
        relation_type="neutral",
        description="台面上互不干涉。",
    )
    services["organization"].create_org_relation(
        session,
        project_id,
        from_id=police,
        to_id=gang_hall,
        relation_type="ally",
        description="巡捕房收青帮的月钱。",
    )
    services["faction"].create_faction_relation(
        session,
        project_id,
        from_id=court,
        to_id=gang,
        relation_type="enemy",
        description="官面上势不两立。",
    )

    _rel(session, services["relation"], shen, chen, "master",
         description="陈伯教他看潮、认船，也教他闭嘴。")
    _rel(session, services["relation"], shen, gu, "lover",
         from_chapter_id=chapter_ids[2], description="从一份货单开始。")
    _rel(session, services["relation"], shen, lu, "blood_feud",
         description="父亲死在码头火并，账却记在九爷头上。")
    _rel(session, services["relation"], gu, lu, "enemy",
         from_chapter_id=chapter_ids[1], description="她查他，他也在查她。")
    _rel(session, services["relation"], gu, bai, "ally",
         is_secret=True, description="线人关系，见不得光。")
    _rel(session, services["relation"], shen, atang, "benefactor",
         description="给过她一碗饭，她记了很多年。")
    _rel(session, services["relation"], lu, zheng, "superior",
         is_secret=True, description="每月十五，郑副官来堂口拿钱。")
    _rel(session, services["relation"], bai, lu, "rival",
         from_chapter_id=chapter_ids[4], description="旧账没清，谁也不敢先动。")
    _rel(session, services["relation"], wen, lu, "servant",
         description="当铺替青帮走账，温老板替九爷挡事。")
    _rel(session, services["relation"], song, wen, "fellow",
         description="账房和东家，一个装糊涂，一个真糊涂。")
    _rel(session, services["relation"], xiaoman, gu, "friend",
         description="报馆门口的小报童，替她跑腿。")
    _rel(session, services["relation"], chen, atang, "kin",
         custom_label="爷孙", description="陈伯在码头捡到她，养到十二岁。")
    _rel(session, services["relation"], zheng, shen, "enemy",
         description="怕他查旧账，处处使绊。")
    _rel(session, services["relation"], atang, xiaoman, "friend",
         description="两个在码头讨生活的小姑娘。")
    return project_id


# --------------------------------------------------------------------------
# 三本：天穹之外（大）
# --------------------------------------------------------------------------


def seed_tianqiong(session, services) -> int:
    project_id = _project(
        session,
        services["project"],
        "天穹之外",
        "九域星海，一个遗孤从废星走进星门。示例数据，可随时删除。",
    )
    volume_one = _volume(
        session,
        services["chapter"],
        project_id,
        "卷一·星落",
        [
            ("一 废星上的孩子", ["废星的白天很短。顾长庚蹲在锈船壳下分拣零件，妹妹顾小满在远处喊他回家。"]),
            ("二 玄甲卫的遗孤", ["玄甲卫的旧甲被翻出来时，上面还刻着父亲的编号。萧承煜看了很久，只说了一句「像」。"]),
            ("三 星枢院来客", ["秦照踏着星尘走进废星，问顾长庚愿不愿意看真正的星图。"]),
            ("四 观海试炼", ["试炼那天，顾长庚第一次听见自己的剑鸣。"]),
            ("五 剑鸣照夜", ["照夜出鞘，整座星枢院的灯都暗了一瞬。"]),
            ("六 商队入港", ["星海盟的商队靠港，云未晞站在船头，没看货单，先看了顾长庚一眼。"]),
            ("七 雾里交易", ["雾港的交易不谈钱，谈命。"]),
            ("八 第一次并肩", ["星盗的刀劈下来时，顾长庚挡在云未晞前面。"]),
            ("九 监正的影子", ["裴玄枢在星图上画了一个圈，圈住归墟的方向。"]),
            ("十 星图失窃", ["星图丢了。守夜的弟子说，只看见一道白影。"]),
        ],
    )
    volume_two = _volume(
        session,
        services["chapter"],
        project_id,
        "卷二·归墟",
        [
            ("十一 归墟来信", ["信是从星门另一边寄来的，落款是顾小满。"]),
            ("十二 白霜", ["白霜在废星等他们，穿一身雪色，像归墟里唯一的灯。"]),
            ("十三 旧案重启", ["玄甲卫旧案被重新翻开，萧承煜的签名在最下面。"]),
            ("十四 阿九的船", ["阿九把拾光号改成了能穿星门的样子，代价是整船的货。"]),
            ("十五 星海盟之变", ["云望舒把商队交出去的那天，云未晞没有哭。"]),
            ("十六 顾小满的下落", ["顾小满在归墟教总坛，被关在一间没有门的屋子里。"]),
            ("十七 玄甲卫出征", ["玄甲卫的战舰遮住了半颗星。"]),
            ("十八 星门开", ["星门开的时候，所有人都听见了水声。"]),
            ("十九 无咎上人", ["厉无咎摘下面具，露出一张和画像上完全不同的脸。"]),
            ("二十 天穹之外", ["顾长庚站在星门之外，第一次看见没有边界的黑。"]),
        ],
    )
    chapter_ids = volume_one + volume_two

    empire = _faction(
        session,
        services["faction"],
        project_id,
        "天枢帝国",
        color="#5b5b8a",
        description="九域名义上的共主，玄甲卫与星枢院皆在其下。",
    )
    league = _faction(
        session,
        services["faction"],
        project_id,
        "星海盟",
        color="#3b6ea5",
        description="商队结成的联盟，不站队，只做生意。",
    )
    cult = _faction(
        session,
        services["faction"],
        project_id,
        "归墟教",
        color="#8b3a4a",
        description="信奉星门之外有归处的教派。",
    )
    _doc(
        session,
        services["document"],
        project_id,
        "九域星图",
        "world",
        _html(
            "九域以星门相连，天枢居中，归墟在最外。",
            "星图每隔百年重绘一次，上一次重绘的监正，正是裴玄枢的师父。",
        ),
    )
    _doc(
        session,
        services["document"],
        project_id,
        "归墟教义",
        "faction",
        _html(
            "星门不是边界，是门。门后没有归处，只有更远的星。",
            "教中称掌教为「无咎上人」，圣女掌钥匙，影卫掌灯。",
        ),
    )

    role_of = {
        "顾长庚": dict(role="protagonist", gender="男", age="二十一", height="一八五"),
        "云未晞": dict(role="heroine", gender="女", age="二十", height="一七零"),
        "裴玄枢": dict(role="antagonist", gender="男", age="五十八", height="一七八"),
        "秦照": dict(role="supporting", gender="男", age="七十", height="一七二"),
        "苏绾": dict(role="supporting", gender="女", age="十八", height="一六二"),
        "陆青野": dict(role="supporting", gender="男", age="二十二", height="一八零"),
        "萧承煜": dict(role="supporting", gender="男", age="三十五", height="一八八"),
        "宁贵妃": dict(role="extra", gender="女", age="三十三", height="一六八"),
        "云望舒": dict(role="supporting", gender="男", age="四十八", height="一七六"),
        "阿九": dict(role="extra", gender="女", age="十六", height="一五八"),
        "厉无咎": dict(role="antagonist", gender="男", age="四十四", height="一八三"),
        "白霜": dict(role="supporting", gender="女", age="二十七", height="一七二"),
        "玄十三": dict(role="extra", gender="男", age="三十", height="一八六"),
        "老陶": dict(role="extra", gender="男", age="六十", height="一七零"),
        "小灯": dict(role="extra", gender="女", age="十", height="一三二"),
        "顾小满": dict(role="extra", gender="女", age="十五", height="一五八", status="missing"),
        "温大学士": dict(role="supporting", gender="男", age="五十五", height="一七四"),
        "刀疤七": dict(role="extra", gender="男", age="三十八", height="一八一"),
    }
    ids: dict[str, int] = {}
    for name, fields in role_of.items():
        status = fields.pop("status", "alive")
        ids[name] = _char(
            session,
            services["character"],
            project_id,
            name,
            status=status,
            tags="示例角色",
            **fields,
        )

    services["character"].set_aliases(session, ids["顾长庚"], ["阿庚", "星枢刀"])
    services["character"].set_aliases(session, ids["云未晞"], ["未未"])
    services["character"].set_aliases(session, ids["厉无咎"], ["无咎上人"])
    services["character"].add_field(session, ids["顾长庚"], key="灵根", value="单系剑灵根")
    services["character"].add_field(session, ids["顾长庚"], key="境界", value="观海三层")
    services["character"].add_field(session, ids["顾长庚"], key="本命剑", value="照夜")
    services["character"].add_field(session, ids["云未晞"], key="灵根", value="双系水系")
    services["character"].add_field(session, ids["云未晞"], key="境界", value="观海一层")
    services["character"].add_field(session, ids["裴玄枢"], key="暗子身份", value="归墟教暗子")

    empire_org = _org(
        session,
        services["organization"],
        project_id,
        "天枢皇廷",
        kind="court",
        faction_id=empire,
        description="九域共主，朝堂在星枢城。",
    )
    guard = _org(
        session,
        services["organization"],
        project_id,
        "玄甲卫",
        kind="army",
        faction_id=empire,
        parent_id=empire_org,
        leader_id=ids["萧承煜"],
        description="帝国的刀，只听兵符。",
    )
    academy = _org(
        session,
        services["organization"],
        project_id,
        "星枢院",
        kind="sect",
        faction_id=empire,
        parent_id=empire_org,
        leader_id=ids["秦照"],
        description="教星图与剑的地方，也替帝国看星门。",
    )
    league_org = _org(
        session,
        services["organization"],
        project_id,
        "星海盟商会",
        kind="guild",
        faction_id=league,
        leader_id=ids["云望舒"],
        description="商队的总号，只认契约，不认旗帜。",
    )
    ship = _org(
        session,
        services["organization"],
        project_id,
        "拾光号",
        kind="guild",
        faction_id=league,
        parent_id=league_org,
        description="星海盟最快的一条船，也是阿九的家。",
    )
    cult_org = _org(
        session,
        services["organization"],
        project_id,
        "归墟教总坛",
        kind="sect",
        faction_id=cult,
        leader_id=ids["厉无咎"],
        description="建在星门之外的黑色神殿。",
    )

    memberships = [
        ("顾长庚", academy, "弟子", True, False),
        ("秦照", academy, "院长", True, False),
        ("苏绾", academy, "弟子", False, False),
        ("陆青野", academy, "弟子", False, False),
        ("裴玄枢", academy, "监正", True, False),
        ("裴玄枢", cult_org, "暗子", False, True),
        ("萧承煜", guard, "指挥使", True, False),
        ("宁贵妃", empire_org, "贵妃", True, False),
        ("温大学士", empire_org, "大学士", False, False),
        ("云未晞", league_org, "少主", True, False),
        ("云望舒", league_org, "首领", True, False),
        ("阿九", ship, "机械师", True, False),
        ("刀疤七", league_org, "外聘船长", False, True),
        ("厉无咎", cult_org, "教主", True, False),
        ("白霜", cult_org, "圣女", True, False),
        ("玄十三", cult_org, "影卫", False, False),
        ("顾小满", cult_org, "囚徒", False, True),
    ]
    for name, org_id, position, primary, secret in memberships:
        _member(
            session,
            services["organization"],
            org_id,
            ids[name],
            position=position,
            primary=primary,
            secret=secret,
        )

    services["organization"].create_org_relation(
        session, project_id, from_id=guard, to_id=cult_org,
        relation_type="war", description="玄甲卫年年出征，星门那边从没退过。"
    )
    services["organization"].create_org_relation(
        session, project_id, from_id=academy, to_id=cult_org,
        relation_type="enemy", description="星枢院封了归墟的星图。"
    )
    services["organization"].create_org_relation(
        session, project_id, from_id=empire_org, to_id=league_org,
        relation_type="neutral", description="帝国收税，商队交钱。"
    )
    services["organization"].create_org_relation(
        session, project_id, from_id=guard, to_id=league_org,
        relation_type="ally", description="商队替玄甲卫运过军械。"
    )
    services["faction"].create_faction_relation(
        session, project_id, from_id=empire, to_id=cult,
        relation_type="enemy", description="帝国称归墟为邪教。"
    )
    services["faction"].create_faction_relation(
        session, project_id, from_id=empire, to_id=league,
        relation_type="neutral", description="互不干涉。"
    )
    services["faction"].create_faction_relation(
        session, project_id, from_id=league, to_id=cult,
        relation_type="enemy", description="归墟劫过星海盟的船。"
    )

    chapters = chapter_ids

    def chapter(index: int) -> int:
        return chapters[index]

    _rel(session, services["relation"], ids["顾长庚"], ids["秦照"], "master",
         from_chapter_id=chapter(0), description="秦照把他从废星带进星枢院。")
    _rel(session, services["relation"], ids["顾长庚"], ids["苏绾"], "fellow",
         from_chapter_id=chapter(2), description="同门，苏绾替他挡过罚。")
    _rel(session, services["relation"], ids["顾长庚"], ids["陆青野"], "rival",
         from_chapter_id=chapter(2), to_chapter_id=chapter(8),
         description="同门竞争，后来只在明面上客气。")
    _rel(session, services["relation"], ids["顾长庚"], ids["云未晞"], "lover",
         from_chapter_id=chapter(7), description="第一次并肩之后。")
    _rel(session, services["relation"], ids["顾长庚"], ids["顾小满"], "sibling",
         description="相依为命的妹妹，如今下落不明。")
    _rel(session, services["relation"], ids["顾长庚"], ids["裴玄枢"], "enemy",
         is_secret=True, from_chapter_id=chapter(8),
         description="监正一直在暗处看着他。")
    _rel(session, services["relation"], ids["萧承煜"], ids["顾长庚"], "benefactor",
         is_secret=True, description="玄甲卫遗孤，不能明着护。")
    _rel(session, services["relation"], ids["老陶"], ids["顾长庚"], "benefactor",
         description="废星上给过他一口热汤。")
    _rel(session, services["relation"], ids["云望舒"], ids["云未晞"], "parent",
         description="父女，也是首领与少主。")
    _rel(session, services["relation"], ids["云未晞"], ids["阿九"], "friend",
         description="一起长大的船伴。")
    _rel(session, services["relation"], ids["阿九"], ids["刀疤七"], "rival",
         description="抢过同一条航道。")
    _rel(session, services["relation"], ids["刀疤七"], ids["云未晞"], "enemy",
         from_chapter_id=chapter(5), description="劫过星海盟的货船。")
    _rel(session, services["relation"], ids["秦照"], ids["裴玄枢"], "rival",
         is_secret=True, description="同僚多年，彼此都知道对方在查什么。")
    _rel(session, services["relation"], ids["厉无咎"], ids["裴玄枢"], "superior",
         is_secret=True, description="暗子的上线，从不见面。")
    _rel(session, services["relation"], ids["裴玄枢"], ids["白霜"], "ally",
         is_secret=True, description="监正替归墟开过一次星门。")
    _rel(session, services["relation"], ids["厉无咎"], ids["玄十三"], "servant",
         description="影卫掌灯，也掌命。")
    _rel(session, services["relation"], ids["白霜"], ids["顾长庚"], "rival",
         from_chapter_id=chapter(11), description="圣女与遗孤，都在找同一扇门。")
    _rel(session, services["relation"], ids["陆青野"], ids["裴玄枢"], "superior",
         is_secret=True, description="替监正递过一封信，从此脱不了身。")
    _rel(session, services["relation"], ids["宁贵妃"], ids["萧承煜"], "rival",
         description="朝堂上争兵符。")
    _rel(session, services["relation"], ids["温大学士"], ids["萧承煜"], "ally",
         description="文官与武将，暂时同路。")
    _rel(session, services["relation"], ids["云望舒"], ids["萧承煜"], "rival",
         description="军械生意上的旧怨。")
    _rel(session, services["relation"], ids["苏绾"], ids["阿九"], "friend",
         description="在雾港修船时认识。")
    _rel(session, services["relation"], ids["老陶"], ids["小灯"], "kin",
         custom_label="爷孙", description="废星上相依为命。")
    _rel(session, services["relation"], ids["小灯"], ids["阿九"], "friend",
         description="阿九教她认星图。")
    _rel(session, services["relation"], ids["白霜"], ids["顾小满"], "other",
         custom_label="看押", is_secret=True, description="圣女奉命看守，却给她留过灯。")
    return project_id


# --------------------------------------------------------------------------
# 入口
# --------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="生成示例小说")
    parser.add_argument("--data-dir", default=str(ROOT / "data"))
    parser.add_argument("--skip-backup", action="store_true")
    parser.add_argument(
        "--only",
        choices=["zhezhi", "wugang", "tianqiong"],
        help="只生成其中一本",
    )
    args = parser.parse_args(argv)

    data_dir = Path(args.data_dir).expanduser().resolve()
    data_dir.mkdir(parents=True, exist_ok=True)
    db_path = data_dir / "inkwell.db"
    os.environ["INKWELL_DATA_DIR"] = str(data_dir)

    from sqlalchemy import func, select

    from backend.config import ensure_data_dirs, load_config
    from backend.database import Database
    from backend.migrate import apply_migrations
    from backend.models import (
        Chapter,
        Character,
        CharacterRelation,
        Document,
        Faction,
        Organization,
        Project,
        Volume,
        session_scope,
    )
    from backend.services import (
        chapter_service,
        character_service,
        document_service,
        faction_service,
        organization_service,
        project_service,
        relation_service,
    )

    config = replace(
        load_config(),
        data_dir=data_dir,
        db_path=db_path,
    )
    ensure_data_dirs(config)

    if db_path.exists() and not args.skip_backup:
        backup_dir = data_dir / "backups"
        backup_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        target = backup_dir / f"seed-demo-{stamp}.db"
        shutil.copy2(db_path, target)
        print(f"已备份数据库：{target}")

    database = Database(config.db_path)
    apply_migrations(database, config.data_dir)

    services = {
        "project": project_service,
        "chapter": chapter_service,
        "character": character_service,
        "document": document_service,
        "faction": faction_service,
        "organization": organization_service,
        "relation": relation_service,
    }

    novels = [
        ("zhezhi", "折枝录", seed_zhezhi),
        ("wugang", "雾港旧事", seed_wugang),
        ("tianqiong", "天穹之外", seed_tianqiong),
    ]

    created: list[int] = []
    with session_scope(database.engine) as session:
        existing = {
            row.title
            for row in session.execute(
                select(Project).where(Project.is_deleted == 0)
            ).scalars()
        }
        for key, title, seed in novels:
            if args.only and key != args.only:
                continue
            if title in existing:
                print(f"跳过《{title}》：书库中已存在")
                continue
            project_id = seed(session, services)
            created.append(project_id)
            print(f"已生成《{title}》 project_id={project_id}")

        print("-" * 72)
        for project_id in created:
            project = session.get(Project, project_id)
            title = project.title
            characters = session.execute(
                select(func.count())
                .select_from(Character)
                .where(
                    Character.project_id == project_id,
                    Character.is_deleted == 0,
                )
            ).scalar_one()
            orgs = session.execute(
                select(func.count())
                .select_from(Organization)
                .where(
                    Organization.project_id == project_id,
                    Organization.is_deleted == 0,
                )
            ).scalar_one()
            factions = session.execute(
                select(func.count())
                .select_from(Faction)
                .where(
                    Faction.project_id == project_id,
                    Faction.is_deleted == 0,
                )
            ).scalar_one()
            relations = session.execute(
                select(func.count())
                .select_from(CharacterRelation)
                .where(
                    CharacterRelation.project_id == project_id,
                    CharacterRelation.is_deleted == 0,
                )
            ).scalar_one()
            chapters = session.execute(
                select(func.count())
                .select_from(Chapter)
                .join(Volume, Volume.id == Chapter.volume_id)
                .where(Volume.project_id == project_id)
            ).scalar_one()
            documents = session.execute(
                select(func.count())
                .select_from(Document)
                .where(
                    Document.project_id == project_id,
                    Document.is_deleted == 0,
                )
            ).scalar_one()
            print(
                f"《{title}》 角色 {characters} / 组织 {orgs} / 阵营 {factions}"
                f" / 关系 {relations} / 章 {chapters} / 文档 {documents}"
            )
    if not created:
        print("没有新建任何书。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

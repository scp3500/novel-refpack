# -*- coding: utf-8 -*-
"""合成一本约 105 章的小说（extract_txt 能认的「第N卷 / 第N章」格式）。"""
from .helpers import cn_num

VOLS = 5
CH_PER_VOL = 21  # 5×21 = 105
PLACES = [
    "青石镇", "黑松林", "渡口", "北门客栈", "旧庙", "粮仓", "河滩", "城墙根",
    "猎户小屋", "官道岔口", "破驿站", "山坳", "盐市", "码头", "城隍庙",
    "西巷", "赌坊后门", "药铺", "城南坟地", "烽火台", "界碑",
]


def chapter_body(vi, ci, tag, place):
    su = ("今晚就住这儿吧。", "水我去打。", "别逞强。")[ci % 3]
    chen = ("后面没人。", "路标还在。", "风大了。")[ci % 3]
    lin = ("我们走吧。", "先把门关上。", "歇半个时辰。")[ci % 3]
    return "\n".join([
        "林舟在%s停住脚步，把手按在刀柄上。招牌在风里晃，泥路上还留着车辙。" % place,
        "苏晚跟上来，低声道：「%s」" % su,
        "陈衡在后面喊：“%s”" % chen,
        "林舟说：“%s”" % lin,
        "他推开门，在门槛上坐下，笑了笑。灯火一盏一盏灭下去。",
        "苏晚知道今晚不会再有别的客栈，把行囊放到桌上，没有再开口。",
        "“我先去打水。”",
        "苏晚问道：“要不要我跟着？”",
        "林舟看着窗外：",
        "“不用。你歇着。”",
        "陈衡靠在门框上，朝林舟道：「我去巷口看一眼。」",
        "第一回合并没有人倒下，只是风灌进巷口，把灯吹歪了。",
        "尾句标记：%s 此地的鼓声从城墙根传过来，三人谁都没有再说话。" % tag,
        "",
    ])


def generate_novel(n_vol=VOLS, ch_per=CH_PER_VOL):
    """返回 (全文, 章数, 最后一章尾记)。"""
    parts = ["简介", "这是一本用来跑流水线冒烟的合成长篇，不是正文。", ""]
    last_tag = ""
    n = 0
    for vi in range(1, n_vol + 1):
        parts.append("第%s卷 %s" % (cn_num(vi), ["北境", "风雪", "渡河", "旧城", "回声"][vi - 1]))
        parts.append("")
        for ci in range(1, ch_per + 1):
            n += 1
            place = PLACES[(n - 1) % len(PLACES)]
            tag = "【尾记V%02dC%02dN%03d】" % (vi, ci, n)
            last_tag = tag
            title = "第%s章 %s夜话" % (cn_num(ci), place)
            parts.append(title)
            parts.append(chapter_body(vi, ci, tag, place))
    return "\n".join(parts).strip() + "\n", n, last_tag

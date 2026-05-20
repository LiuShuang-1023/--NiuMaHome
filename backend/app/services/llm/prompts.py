"""AI 对话理解层 - 核心 Prompt"""
import json

SYSTEM_PROMPT = """你是「牛马归栏」AI 租房助理，帮打工人快速找到合适的房子。

## 第一原则：用户说什么就是什么

**用户的话是最高指令**。你不是审核员，不要质疑用户的需求。

- 用户说"广州"→ 就搜全广州，不要追问"番禺还是天河？"
- 用户说"不限"→ 就当不限，不要再问预算/户型
- 用户说"不要之前的"→ **立即清空**之前的需求，重新理解
- 用户说"我不想说预算"→ 不要再问预算

只在**绝对没法搜**时才追问（即没城市），其他都不必问。

---

## 第二原则：能搜就立刻设 is_ready=true

is_ready=true 的**唯一硬性条件**：destination.city 有值。

满足这一条 → is_ready=true，立刻开搜，不要追问任何"你确定吗"。

---

## 输出格式（严格遵守）

返回**单层** JSON 对象：

- `reply` (字符串)：给用户看的中文自然语言。**纯文本，不能含 JSON**
- `requirement` (对象)：结构化需求
- `is_ready` (布尔)
- `clarifying_questions` (字符串数组)：0-1 个追问，能搜就留空数组

---

## requirement 字段定义

```
{
  "destination": {
    "city": "城市名，如 广州/深圳/北京",
    "district": "区，如 番禺区/南山区。用户没说就空字符串",
    "landmark": "地标/园区/公司，如 南村万博。用户没说或要求清空就空字符串",
    "address": "可推断的完整地址。用户没说或要求清空就空字符串"
  },
  "commute": {
    "max_minutes": 数字。用户没说就 60,
    "modes": ["transit", "riding", "walking"],
    "maps": ["amap", "baidu"]
  },
  "rental_type": {
    "include": [],
    "exclude": []
  },
  "price": {
    "base_rent_max": null,
    "base_rent_min": null,
    "total_cost_max": null,
    "total_cost_min": null
  },
  "soft_preferences": [],
  "hard_excludes": []
}
```

可选 rental_type 值：entire / entire_1b1b / entire_2b1b / entire_3b1b / single_room / shared / urban_village / basement / old_building

---

## 何时设 is_ready=true

**只看一个条件**：destination.city 有没有值。

- 有 city → is_ready=true，立刻开搜
- 没 city → is_ready=false，问城市

**禁止**因为以下原因把 is_ready 设为 false：
- 用户没说预算
- 用户没说户型
- 用户没说精确地址（有 city 就够了）
- 用户没说通勤时长
- "我觉得用户应该再想想"——不！相信用户

---

## 何时清空字段（重置）

用户出现以下表达 → 清空之前的对应字段，重新理解：
- "不要之前的" / "重新来" / "换一下" / "改一下"
- "我不想要 X 了" → 把 X 相关字段清空
- "广州的什么房子都行" / "广州随便看" → **清空 landmark/district/address**，只留 city="广州"

---

## reply 字段写法

- 中文自然语言，简洁
- 即将开搜时：直接说"好的，马上去搜！"或"收到，正在为你搜索 [城市]+[条件]..."
- 需要追问时（仅当连城市都没有）：友好地问一次城市
- 可以**温和地建议**用户补充信息让结果更准（但不强求），比如："如果你能告诉我具体公司位置，我可以帮你算通勤时间，不过现在直接搜也可以。"
- 不超过 100 字
- 不能含 JSON、不能含字段名、不能含大括号

---

## 多轮对话规则

- 用户追加信息时，requirement 返回**完整的合并后版本**
- 用户说"不要之前的"/"换一下" → 该清空的字段必须清空
- 用户说"对"/"是的"/"开始搜" → 立即 is_ready=true
- 不要重复问已经回答过或表态"不限"的问题

---

## 重要禁令

❌ 不要在 reply 里粘贴 JSON
❌ 不要追问预算/户型/通勤时长（用户主动说才记，不主动问）
❌ 不要在 clarifying_questions 里写无关问题
❌ 不要因为字段缺失就 is_ready=false（只要有 city 就 true）
❌ 不要忽略用户的"重置"指令（"不要之前的"必须清空相应字段）
❌ 不要多轮重复问同一件事
"""


def build_messages_payload(history: list[dict], current_req: dict | None = None) -> list[dict]:
    """组装发给 LLM 的消息列表"""
    messages = []

    # 如果有当前已解析的需求，作为上下文附在最新一条 user 消息前
    if current_req and history:
        history = list(history)
        for i in range(len(history) - 1, -1, -1):
            if history[i].get("role") == "user":
                ctx = (
                    f"[系统提示] 之前已收集到的需求（你可以基于此修改/重置）：\n"
                    f"{json.dumps(current_req, ensure_ascii=False, indent=2)}\n\n"
                    f"用户新消息：\n{history[i]['content']}"
                )
                history[i] = {**history[i], "content": ctx}
                break

    for msg in history:
        messages.append({
            "role": msg["role"],
            "content": msg["content"],
        })

    return messages


# ============================================================
# 房源 AI 点评（v0.2 新增）
# ============================================================

LISTING_REVIEW_SYSTEM_PROMPT = """你是「牛马归栏」AI 租房顾问，帮打工人客观分析每套房源的优缺点。

## 输出格式（严格 JSON 单层对象）

```
{
  "score": 数字 0-10，保留1位小数。综合评分（性价比 + 通勤 + 信息透明度）,
  "summary": "一句话总结，30字以内，告诉用户最该关注什么",
  "pros": ["优点1", "优点2", ...],   // 3-5 条，每条 15 字以内
  "cons": ["缺点1或风险点", ...],     // 2-4 条，每条 15 字以内
  "tags": ["性价比高" / "通勤友好" / "信息不全" / "价格异常" 等, ...]  // 0-3 个
}
```

## 评分准则

- 8-10 分：性价比好、通勤近、信息齐全、无明显风险
- 6-8 分：满足基本需求，有一定权衡
- 4-6 分：有明显短板（贵 / 远 / 信息缺失）
- <4 分：极度不推荐（疑似引流帖、超预算、关键信息缺失）

## 写作风格

- **直给**，像同事在群里聊天，别官腔
- 用打工人能直接 get 的语言（"通勤 25min 还行"、"押 2 付 3 真离谱"）
- 优点缺点要**具体**，不要"位置好"这种废话；要写"距万博地铁 8min 步行"
- 风险点要警示：装修信息缺失、价格远低于周边、户型异常等
- ⚠️ 不要瞎编不存在的信息。数据没有的就明确说"未公开"

## 严禁

❌ 不要返回 markdown 代码块，直接返回 JSON
❌ 不要在 reply 里嵌套 JSON
❌ 不要写超过 15 字的pros/cons 单条
❌ 不要使用 emoji（除非 tag 里）
"""


def build_listing_review_user_prompt(
    listing: dict,
    cost: dict,
    commute: dict | None,
    requirement: dict | None,
) -> str:
    """组装房源点评的 user 消息"""
    parts = ["请点评下面这套房源（结合用户需求和真实成本/通勤数据）：\n"]

    # 用户需求摘要
    if requirement:
        dest = requirement.get("destination", {})
        price = requirement.get("price", {})
        commute_req = requirement.get("commute", {})
        parts.append("【用户需求】")
        if dest.get("city"):
            parts.append(
                f"- 通勤目的地: {dest.get('city', '')}{dest.get('district', '')}{dest.get('landmark', '')}"
            )
        if commute_req.get("max_minutes"):
            parts.append(f"- 期望通勤 ≤ {commute_req['max_minutes']} 分钟")
        if price.get("base_rent_max"):
            parts.append(f"- 房租上限 ¥{price['base_rent_max']}")
        if price.get("total_cost_max"):
            parts.append(f"- 全包月支出上限 ¥{price['total_cost_max']}")
        excludes = requirement.get("hard_excludes") or []
        if excludes:
            parts.append(f"- 不要：{', '.join(excludes)}")
        parts.append("")

    # 房源信息
    parts.append("【房源信息】")
    parts.append(f"- 平台: {listing.get('platform', '?')}")
    parts.append(f"- 标题: {listing.get('title', '')}")
    if listing.get("community"):
        parts.append(f"- 小区: {listing['community']}")
    if listing.get("address"):
        parts.append(f"- 地址: {listing['address']}")
    if listing.get("layout"):
        parts.append(f"- 户型: {listing['layout']}")
    if listing.get("area"):
        parts.append(f"- 面积: {listing['area']}㎡")
    if listing.get("floor"):
        parts.append(f"- 楼层: {listing['floor']}")
    if listing.get("orientation"):
        parts.append(f"- 朝向: {listing['orientation']}")
    if listing.get("rental_type_tag"):
        parts.append(f"- 租赁形态: {listing['rental_type_tag']}")
    parts.append(f"- 基础租金: ¥{listing.get('price_base', 0)}/月")
    missing = listing.get("missing_fields") or []
    if missing:
        parts.append(f"- ⚠️ 列表页未提供: {', '.join(missing)}")
    parts.append("")

    # 成本
    parts.append("【真实月支出估算】")
    parts.append(f"- 合计: ¥{cost.get('total', 0)}/月")
    items = [
        ("基础房租", cost.get("base_rent", 0)),
        ("物业费", cost.get("property_fee", 0)),
        ("水电燃气", cost.get("water", 0) + cost.get("electricity", 0) + cost.get("gas", 0)),
        ("网络", cost.get("internet", 0)),
        ("中介摊销", cost.get("agency_fee_monthly", 0)),
        ("押金占用", cost.get("deposit_cost", 0)),
    ]
    for label, val in items:
        if val:
            parts.append(f"  · {label}: ¥{val}")
    parts.append("")

    # 通勤
    if commute and commute.get("results"):
        parts.append("【通勤数据】")
        parts.append(f"- 最快: {commute.get('best_duration_min', 0)} 分钟")
        if commute.get("nearest_metro"):
            metro_min = commute.get("metro_walk_min")
            metro_str = f"步行 {metro_min}min" if metro_min else "距离未知"
            parts.append(f"- 最近地铁: {commute['nearest_metro']}（{metro_str}）")
        # 按 mode 取均值（避免 prompt 太长）
        by_mode: dict[str, list[int]] = {}
        for r in commute["results"]:
            by_mode.setdefault(r.get("mode", "?"), []).append(r.get("duration_min", 0))
        mode_label = {"transit": "公交", "riding": "骑行", "walking": "步行", "driving": "驾车"}
        for mode, durs in by_mode.items():
            avg = round(sum(durs) / len(durs))
            parts.append(f"  · {mode_label.get(mode, mode)}: 约 {avg} 分钟")
        parts.append("")
    else:
        parts.append("【通勤数据】未测算（无目的地或地图 API 失败）\n")

    parts.append("现在请输出 JSON 点评（严格按系统提示的格式）：")
    return "\n".join(parts)

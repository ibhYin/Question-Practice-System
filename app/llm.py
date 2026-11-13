"""LLM 客户端：OpenAI 兼容接口（DeepSeek / Kimi / 通义 / OpenAI 均适用）。

未配置 key 时 is_enabled() 返回 False，所有上层逻辑自动走离线题库降级。
配置优先级：Redis 覆盖值（设置页保存）> .env。
"""

import json
import time

import httpx

from .config import settings
from .redis_client import rdb

LLM_CONFIG_KEY = "config:llm"


def get_llm_config() -> dict:
    cfg = {
        "base_url": settings.llm_base_url.rstrip("/"),
        "api_key": settings.llm_api_key,
        "model": settings.llm_model,
    }
    stored = rdb.hgetall(LLM_CONFIG_KEY)
    if stored:
        for k in ("base_url", "api_key", "model"):
            if stored.get(k):
                cfg[k] = stored[k]
    return cfg


def is_enabled() -> bool:
    cfg = get_llm_config()
    return bool(cfg["api_key"] and cfg["base_url"] and cfg["model"])


def save_config(base_url: str, api_key: str, model: str) -> None:
    rdb.hset(
        LLM_CONFIG_KEY,
        mapping={"base_url": base_url.strip(), "api_key": api_key.strip(), "model": model.strip()},
    )


def _chat(messages: list[dict], temperature: float = 0.6, timeout: int = 90) -> str:
    cfg = get_llm_config()
    if not (cfg["api_key"] and cfg["base_url"] and cfg["model"]):
        raise RuntimeError("LLM 未配置")
    body = {"model": cfg["model"], "messages": messages, "temperature": temperature}
    headers = {"Authorization": f"Bearer {cfg['api_key']}"}
    # 网络抖动/网关 5xx 重试一次；4xx（如 key 无效）不重试
    last_exc: Exception | None = None
    for attempt in range(2):
        try:
            resp = httpx.post(
                f"{cfg['base_url']}/chat/completions", json=body, headers=headers, timeout=timeout
            )
            if resp.status_code >= 500:
                raise httpx.HTTPStatusError(
                    f"LLM 网关 {resp.status_code}", request=resp.request, response=resp
                )
            resp.raise_for_status()
            return resp.json()["choices"][0]["message"]["content"]
        except (httpx.TransportError, httpx.HTTPStatusError) as e:
            last_exc = e
            if attempt == 0:
                time.sleep(1)
    raise last_exc  # type: ignore[misc]


def test_connection() -> str:
    return _chat(
        [{"role": "user", "content": "请只回复两个字母：ok"}], temperature=0, timeout=20
    ).strip()


def _parse_json(text: str) -> dict:
    """容错解析：剥离 markdown 代码块、截取首尾大括号"""
    t = text.strip()
    if t.startswith("```"):
        t = t.strip("`").strip()
        if t.startswith("json"):
            t = t[4:].strip()
    start, end = t.find("{"), t.rfind("}")
    if start == -1 or end == -1 or end <= start:
        raise ValueError(f"LLM 返回中未找到 JSON：{text[:200]}")
    return json.loads(t[start : end + 1])


# ---------- 出题 ----------

GEN_QUESTIONS_SYSTEM = (
    "你是一位资深的中文技术面试官，负责为候选人生成高质量的模拟面试题。"
    "只输出 JSON，不要输出其他内容。"
)


def generate_questions(
    position: str, categories: list[str], category_names: dict[str, str], n: int, avoid_titles: list[str]
) -> list[dict]:
    avoid = "、".join(avoid_titles[-30:]) if avoid_titles else "（无）"
    cats = "、".join(f"{c}({category_names.get(c, c)})" for c in categories)
    user = (
        f"候选人应聘岗位：{position}\n"
        f"考察类别（category 字段只能从括号前的英文编码中选）：{cats}\n"
        f"请生成 {n} 道面试题，要求：\n"
        "1. 题目是真实面试中常问的经典题，或紧贴该岗位的高频考点\n"
        "2. 难度分布合理：difficulty 用 1(易)/2(中)/3(难)\n"
        "3. tags 给出 2-4 个知识点标签\n"
        f"4. 严禁与这些已有题目重复：{avoid}\n"
        '5. 返回 JSON：{"questions": [{"title": "...", "category": "MYSQL", "difficulty": 2, "tags": ["索引"]}]}'
    )
    text = _chat(
        [{"role": "system", "content": GEN_QUESTIONS_SYSTEM}, {"role": "user", "content": user}]
    )
    data = _parse_json(text)
    return data.get("questions", [])


RESUME_QUESTIONS_SYSTEM = (
    "你是一位资深的中文技术面试官，正在对候选人做简历深挖面试："
    "围绕简历上写的项目、数据与技能逐层追问，验证候选人的真实掌握程度。"
    "只输出 JSON，不要输出其他内容。"
)


def generate_resume_questions(resume_text: str, n: int, avoid_titles: list[str]) -> list[dict]:
    """基于简历生成个人化深挖题（含建议回答要点）。题目必须锚定简历事实，不编造。"""
    avoid = "、".join(avoid_titles[-30:]) if avoid_titles else "（无）"
    user = (
        "以下是候选人的完整简历：\n\n"
        f"{resume_text.strip()}\n\n"
        f"请基于这份简历生成 {n} 道简历深挖面试题，要求：\n"
        "1. 题干必须锚定简历中的具体事实（项目名、技术选型、量化指标、架构细节），"
        "让候选人解释'怎么做的/为什么这么做/数据怎么测出来的'；严禁编造简历中没有的内容，"
        "也不要出与简历无关的通用八股题\n"
        "2. 覆盖多类追问：项目架构与决策（如'为什么选 Django 而不是 FastAPI 做 Agent'）、"
        "量化指标的真实性验证（如'执行准确率 57.7%→65.1% 的消融是怎么做的'）、"
        "最难的问题与踩坑、安全设计（如 MCP 的 Host 白名单/沙箱）、可复用组件的边界\n"
        "3. 难度分布合理：difficulty 用 1(易)/2(中)/3(难)，深挖细节的题给 3\n"
        "4. tags 给 2-4 个技术标签（如 MCP、A2A、引用校验、Text-to-SQL）\n"
        "5. answer 给出'建议回答要点'：基于简历事实，用 STAR 框架"
        "（情境-任务-行动-结果）组织，列出面试官期待的得分点，300 字以内\n"
        f"6. 严禁与这些已有题目重复：{avoid}\n"
        '7. 返回 JSON：{"questions": [{"title": "...", "difficulty": 2, '
        '"tags": ["MCP"], "answer": "..."}]}'
    )
    text = _chat(
        [{"role": "system", "content": RESUME_QUESTIONS_SYSTEM}, {"role": "user", "content": user}],
        temperature=0.4,
        timeout=180,
    )
    data = _parse_json(text)
    return data.get("questions", [])


# ---------- 满分答案 ----------

GEN_ANSWER_SYSTEM = (
    "你是技术面试辅导专家，给出的答案必须结构化、要点式，覆盖面试官期待的得分点。"
)


def generate_model_answer(title: str, category: str) -> str:
    user = (
        f"面试题：{title}\n"
        f"题目类别：{category}\n"
        "请给出这份题的面试满分答案：\n"
        "- 用 1. 2. 3. 要点式作答，可含短横线子要点\n"
        "- 覆盖关键概念 + 原理 + 实践要点，突出得分点\n"
        "- 中文，控制在 350 字以内，不要开场白和结束语"
    )
    return _chat(
        [{"role": "system", "content": GEN_ANSWER_SYSTEM}, {"role": "user", "content": user}],
        temperature=0.3,
    ).strip()


# ---------- 评分 ----------

EVAL_SYSTEM = (
    "你是严格的面试评分官，客观公正，既不放过缺失的要点也不吝啬对亮点肯定。"
    "只输出 JSON，不要输出其他内容。"
)


def evaluate_answer(title: str, model_answer: str, user_answer: str) -> dict:
    user = (
        f"面试题：{title}\n\n"
        f"【满分答案（评分参考）】\n{model_answer}\n\n"
        f"【候选人回答】\n{user_answer}\n\n"
        "请按满分 100 分打分，并给出简短点评（先说答到了什么，再说遗漏什么，最后一句建议）。\n"
        '返回 JSON：{"score": 75, "comment": "..."}，comment 控制在 120 字内。'
    )
    messages = [
        {"role": "system", "content": EVAL_SYSTEM},
        {"role": "user", "content": user},
    ]
    data = None
    for attempt in range(2):  # JSON 解析失败重试一次
        text = _chat(messages, temperature=0.2)
        try:
            data = _parse_json(text)
            break
        except ValueError:
            if attempt == 1:
                raise
    score = max(0, min(100, int(data.get("score", 0))))  # type: ignore[union-attr]
    comment = str(data.get("comment", "")).strip()  # type: ignore[union-attr]
    return {"score": score, "comment": comment}


# ---------- 知识点：知识包 / 诊断 / 变体 ----------

PACK_SYSTEM = (
    "你是资深技术面试教练。你将拿到一个知识点的名称、所属方向，以及候选人在该知识点下的"
    "真实作答记录（含分数与点评）。请生成一份系统、全面的知识文档——这不是背诵卡，"
    "而是能支撑候选人应对该知识点任何问法的完整知识来源。只输出 JSON。"
)


def generate_knowledge_pack(tag: str, category: str, evidence: list[dict]) -> dict:
    """为知识点生成系统知识包：完整原理 + 边界细节 + 变体问法清单 + 识别信号。

    evidence 是候选人在该知识点下的真实作答（题目/回答/分数/点评）——
    生成内容必须针对性覆盖候选人暴露的弱点，而不是泛泛的百科。
    返回 {content: markdown 文档, variant_questions: 变体问法清单}。
    """
    ev_lines = []
    for e in evidence[:5]:
        ev_lines.append(
            f"- 题：{e['title']}（得分 {e.get('score', '未评')}）\n"
            f"  我的回答摘要：{str(e.get('user_answer', ''))[:300]}\n"
            f"  点评：{str(e.get('comment', ''))[:200]}"
        )
    ev_text = "\n".join(ev_lines) if ev_lines else "（暂无作答记录，请按通用高频考点组织）"
    user = (
        f"知识点：{tag}\n所属方向：{category}\n\n"
        f"候选人在该知识点下的真实作答：\n{ev_text}\n\n"
        "请生成该知识点的系统知识包（Markdown），结构如下：\n"
        "## 核心原理\n（完整讲透该知识点：是什么、为什么这么设计、底层机制推导）\n"
        "## 关键细节与边界\n（容易忽略的细节、特殊情况、与其他知识的交界）\n"
        "## 实战要点\n（真实工作中怎么用、和面试官互动时的加分表达）\n"
        "## 常见变体问法\n（列出 5~8 种该知识点的不同问法/角度，让候选人见到换装题也能认出）\n"
        "## 识别信号\n（题干出现什么关键词时应立刻想到这个知识点）\n\n"
        "要求：① 必须针对上面候选人暴露的弱点重点补强；② 内容完整系统，不要写成要点罗列；"
        "③ 1200 字以内。\n"
        '同时返回该知识点的变体问法题（可作为面试题练习）：'
        '{"content": "markdown", "variant_questions": [{"title": "变体题干", "difficulty": 2}]}'
    )
    text = _chat(
        [{"role": "system", "content": PACK_SYSTEM}, {"role": "user", "content": user}],
        temperature=0.4,
        timeout=120,
    )
    data = _parse_json(text)
    return {
        "content": str(data.get("content", "")).strip(),
        "variant_questions": data.get("variant_questions") or [],
    }


DIAG_SYSTEM = (
    "你是面试诊断教练。根据候选人在一个知识点下的真实作答（含分数与点评），"
    "诊断具体欠缺。只输出 JSON。"
)


def diagnose_tag(tag: str, category: str, evidence: list[dict]) -> dict:
    """基于真实作答诊断该知识点的具体欠缺（区别于知识包的通用知识）。"""
    ev_lines = []
    for e in evidence[:5]:
        ev_lines.append(
            f"- 题：{e['title']}（得分 {e.get('score', '未评')}）\n"
            f"  我的回答：{str(e.get('user_answer', ''))[:300]}\n"
            f"  点评：{str(e.get('comment', ''))[:200]}"
        )
    user = (
        f"知识点：{tag}（{category}）\n候选人作答：\n" + "\n".join(ev_lines) + "\n\n"
        "请诊断：候选人在这个知识点上具体缺什么、有什么误区、下一步怎么补。\n"
        '返回 JSON：{"gap_summary": "缺什么（80字内）", "missed_points": ["遗漏要点", ...], '
        '"misconception": "需要纠正的误区（没有则为空字符串）", '
        '"review_advice": "具体复习路径（80字内）", "severity": "high|medium|low"}'
    )
    text = _chat(
        [{"role": "system", "content": DIAG_SYSTEM}, {"role": "user", "content": user}],
        temperature=0.2,
    )
    return _parse_json(text)


VARIANT_SYSTEM = (
    "你是面试出题官。围绕一个知识知识点生成多道变体面试题——同一核心知识、"
    "不同问法/角度/场景，用于训练候选人识别换装题。只输出 JSON。"
)


def generate_variants(tag: str, category: str, base_titles: list[str], n: int) -> list[dict]:
    avoid = "、".join(base_titles[:8]) if base_titles else "（无）"
    user = (
        f"知识点：{tag}（{category}）\n"
        f"已有原题（严禁重复或近似改写）：{avoid}\n\n"
        f"请生成 {n} 道该知识点的变体面试题：不同问法、不同切入角度、或结合真实场景提问，"
        "但核心考点不变。难度覆盖 1~3。\n"
        '返回 JSON：{"questions": [{"title": "...", "difficulty": 2, "tags": ["..."]}]}'
    )
    text = _chat(
        [{"role": "system", "content": VARIANT_SYSTEM}, {"role": "user", "content": user}],
        temperature=0.7,
    )
    data = _parse_json(text)
    return data.get("questions", [])


# ---------- 知识框架（每题树状大纲） ----------

FRAMEWORK_SYSTEM = (
    "你是技术知识体系架构师。给定一道面试题、满分答案要点、以及候选人的历史作答证据，"
    "请输出这道题的知识框架——树状大纲，把这道题放进完整的知识体系里："
    "懂什么才能答好它、答题的骨架、面试官会往哪里追问、它与哪些知识相邻。"
    "用 Markdown 嵌套列表输出，总长 600 字内，不要开场白。"
)


def generate_framework(title: str, model_answer: str, evidence: list[dict], tags: list[str]) -> str:
    ev_lines = []
    for e in evidence[:3]:
        ev_lines.append(f"- 候选人作答（{e.get('score', '未评')} 分）：{str(e.get('user_answer', ''))[:200]}")
    ev_text = "\n".join(ev_lines) if ev_lines else "（暂无作答记录）"
    user = (
        f"面试题：{title}\n"
        f"知识点标签：{'、'.join(tags or [])}\n"
        f"满分答案要点：\n{model_answer[:1200] or '（略）'}\n\n"
        f"候选人历史作答：\n{ev_text}\n\n"
        "请输出如下结构（嵌套列表，每项一句话）：\n"
        "**本题核心**：一句话\n"
        "- 前置知识\n  - …（2~3 条，不懂这些就答不好本题）\n"
        "- 答题骨架\n  - …（3~5 条，按得分点组织）\n"
        "- 易错点与追问方向\n  - …（2~4 条，面试官最可能深挖的地方）\n"
        "- 延伸关联\n  - …（2~3 条相邻知识点，标注与本题的关系）"
    )
    return _chat(
        [{"role": "system", "content": FRAMEWORK_SYSTEM}, {"role": "user", "content": user}],
        temperature=0.3,
        timeout=120,
    ).strip()


# ---------- 知识关联 ----------

LINK_SYSTEM = (
    "你是技术知识图谱专家，判断两道面试题在知识体系上是否相邻"
    "（同一知识点的不同侧面、原理与应用的关系、或有直接的推导依赖）。"
    "只输出 JSON，不要输出其他内容。"
)


def judge_question_pairs(pairs: list[dict]) -> list[dict]:
    """批量判断题目对是否知识相邻。pairs: [{a_id, a_title, b_id, b_title}]，跨类别配对。
    返回 [{a_id, b_id, linked: true/false}]。
    """
    listing = "\n".join(
        f'{p["a_id"]}. {p["a_title"][:50]} ||| {p["b_id"]}. {p["b_title"][:50]}' for p in pairs
    )
    user = (
        f"以下是面试题配对（左边题id与标题 ||| 右边题id与标题）：\n{listing}\n\n"
        "判断每对在知识体系上是否值得关联（同知识点不同侧面/原理与应用/直接依赖）。"
        "标准从严：只在确信有实质知识联系时关联。"
        '返回 JSON：{"results": [{"pair": "a_id-b_id", "linked": true}]}'
    )
    text = _chat(
        [{"role": "system", "content": LINK_SYSTEM}, {"role": "user", "content": user}],
        temperature=0.1,
    )
    data = _parse_json(text)
    out = []
    for r in data.get("results", []):
        pair = str(r.get("pair", ""))
        if "-" not in pair:
            continue
        a_id, b_id = pair.split("-", 1)
        if a_id.isdigit() and b_id.isdigit():
            out.append({"a_id": int(a_id), "b_id": int(b_id), "linked": bool(r.get("linked"))})
    return out


CARD_PICK_SYSTEM = (
    "你是知识映射专家。给定面试题和同一方向下的知识点卡片列表，"
    "挑出能帮助回答该题的卡片（知识相邻或互补）。只输出 JSON。"
)


def pick_cards_for_question(questions: list, cards_by_cat: dict) -> list[dict]:
    """批量：为无规则边的题目挑选相关八股卡。
    questions: [Question]，cards_by_cat: {category: [StudyCard]}。
    返回 [{question_id: int, card_ids: [int]}]。
    """
    out = []
    for q in questions:
        cards = cards_by_cat.get(q.category, [])
        if not cards:
            continue
        listing = "\n".join(f"{c.id}. {c.title}" for c in cards[:30])
        user = (
            f"面试题：{q.title}\n题目标签：{'、'.join(q.tags or [])}\n\n"
            f"候选知识点卡：\n{listing}\n\n"
            "挑出 1~5 张能帮助回答该题的卡（id 列表），无关则返回空。"
            '返回 JSON：{"question_id": %d, "card_ids": [1, 2]}' % q.id
        )
        text = _chat(
            [{"role": "system", "content": CARD_PICK_SYSTEM}, {"role": "user", "content": user}],
            temperature=0.1,
        )
        try:
            data = _parse_json(text)
            if data.get("question_id") == q.id:
                out.append({"question_id": q.id, "card_ids": data.get("card_ids", [])})
        except ValueError:
            continue
    return out


# ---------- 总评 ----------

SUMMARY_SYSTEM = "你是面试复盘教练，点评一针见血，给出可执行的改进建议。"


def summarize_session(position: str, records: list[dict]) -> str:
    lines = [
        f"- [{r['category']}] {r['title']}｜得分：{r['score']}｜点评：{r['comment']}"
        for r in records
    ]
    user = (
        f"候选人应聘岗位：{position}\n本场逐题表现：\n" + "\n".join(lines) + "\n\n"
        "请给出本场面试总评（150 字内）：整体水平判断、最薄弱的 1-2 个方向、下一步复习建议。"
    )
    return _chat(
        [{"role": "system", "content": SUMMARY_SYSTEM}, {"role": "user", "content": user}],
        temperature=0.4,
    ).strip()

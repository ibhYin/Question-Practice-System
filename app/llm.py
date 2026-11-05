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

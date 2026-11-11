# AGENTS.md — 项目约定与新会话必读

> 面试刷题系统（MySQL + Redis 实战项目）。新会话开始工作前先读本文件，可无缝接上。

## 项目概述

输入应聘岗位 → 按岗位画像抽题 → 逐题作答 → 与「满分答案」对比 + AI 异步评分 → 弱点诊断与变体训练。
两大学习板块**数据分离**：面试题库（question 表，作答+评分）与八股文库（study_doc/study_card 表，背诵+标记）。

## 技术栈与架构

- **后端**: FastAPI + SQLAlchemy + PyMySQL，入口 `app/main.py`（启动时 create_all 建表 + 智能备份检查）
- **前端**: Vue 3 + ECharts + Mermaid（全部 vendor 本地 `web/vendor/`，无构建），由 FastAPI 托管
- **存储**: MySQL 8.4 + Redis 7（docker-compose 容器，数据 bind mount 到 `data/mysql`、`data/redis`）
- **LLM**: OpenAI 兼容接口（`app/llm.py`，httpx 带 5xx 重试），配置存 Redis `config:llm`（优先于 .env）；无 key 自动降级离线模式
- **核心模块**: `app/question_bank.py`（岗位画像+抽题）/ `app/interview.py`（面试流程+异步评分）/ `app/analysis.py`（弱点诊断+知识点图谱）/ `app/backup.py`（智能备份）/ `app/review.py`（错题遗忘曲线）

## 本机环境约定（重要）

- **容器引擎是 OrbStack，不是 Docker Desktop**（已卸载）。`docker` 命令正常可用，引擎随任意 docker 命令自动拉起；`orb stop` 可省内存
- **应用端口 8010**（8000 被用户其他进程占用），见 `.env` 的 APP_PORT
- **项目在外置盘** `/Volumes/xiaoPai/Documents/MySQL+Redis`；MySQL/Redis 数据 bind mount 在 `data/`，Docker 数据在 `/Volumes/xiaoPai/OrbStackData`——外置盘必须挂载
- 智能备份：应用启动/结束面试/题目增删时检查，距上次备份 >24h 则后台 mysqldump 到 `data/backups/`（保留 10 份）；手动 `./scripts/backup.sh`
- 用户有其他服务在跑（langchain graphrag、boss 自动投递等）——**清理进程时绝不能动它们**

## 常用命令

```bash
./scripts/start.sh                     # 一键启动（自动拉起引擎+容器，自动清端口残留）
./scripts/backup.sh                    # 手动备份
.venv/bin/python -m seed.check_seed    # 面试题库自检（新加题后必跑）
.venv/bin/python -m seed.load_seed     # 面试题库幂等导入
.venv/bin/python -m seed.check_study   # 八股文库自检
.venv/bin/python -m seed.load_study    # 八股文库幂等导入（文档按 title 覆盖更新）
.venv/bin/python -m scripts.build_knowledge_links --llm   # 重建知识关联图
.venv/bin/python -m scripts.build_question_card_links --llm  # 重建题↔八股卡映射
```

## 数据规模与结构（截至 2026-11-11）

- 面试题库 345 题 / 15 类（MYSQL/REDIS/JAVA/JVM/CONCURRENT/SPRING/NETWORK/SCENARIO/AI_APP/AGENT/FULLSTACK/OS/DISTRIBUTED/ALGO/PYTHON）；含 SSE/WebSocket 实时通信与 Agent Harness 专题批次（seed/extras_realtime.yaml、extras_harness.yaml）
- 八股文库：15 篇体系文档（13 篇含 Mermaid 图）+ 342 张背诵卡
- **八股卡 content 是 YAML 纯标量**：正文里不能出现 ASCII「冒号+空格」（写成 = 或全角：），否则 safe_load 直接炸
- MySQL 7 张表：question / interview_session / interview_answer / chat_message(AI 追问持久化) / study_doc / study_card / knowledge_pack(每知识点系统知识包)
- Redis 键：`interview:session:{id}`(进度) / `interview:lock`(全场锁,TTL+自愈) / `review:queue`+`review:stage`(遗忘曲线) / `question:hot`(错题榜) / `cache:bank:{cat}`(抽题池) / `stats:category` / `serve:recent`(出题冷却) / `weakness:cache` / `config:llm`

## 本项目踩过的坑（改代码前必读）

- **DOM 模板必须用 kebab-case** `<keep-alive>`：浏览器会把 `<KeepAlive>` 小写成 `keepalive`，Vue 内置组件静默失效
- **zset member 类型**：写入 int、读回是 str——`q.id not in recent` 这类判断必须先统一 `int(m)`，否则过滤永远失效
- **`match_profile` 顺序敏感**：`"开发"` 兜底分支必须放最后；`\b` 词边界对中文失效，AI 匹配用 `(?<![a-z0-9])ai(?![a-z0-9])`
- **REPEATABLE READ 快照**：等待后台线程写库后，当前请求需 `db.commit() + db.expire_all()` 才能看到新数据
- **异步评分收口**：finish 用 `_wait_session_scoring`（30s 截止，不取消），未评完的稍后在复盘中可见；总评基于已出分数
- **前端缓存**：`app/main.py` 已对 /、/index.html、/app.js、/style.css 发 no-cache 头——别删，否则浏览器缓存旧 JS 导致页面空白
- 满分答案/知识包生成走懒加载（答题时/按钮触发），创建面试只生成题干——避免长阻塞

## 用户偏好

- 中文交流；方案先确认再实施（plan mode）
- 质量优先：新内容逐题撰写+自检脚本校验；所有功能改动必须实测验证后如实汇报
- 数据安全：一切有价值的产出都要有备份/持久化路径

## 路线图（未实现）

多用户/多设备同步、岗位画像自定义权重、每日学习报告、题目收藏夹、语音作答（Web Speech API）

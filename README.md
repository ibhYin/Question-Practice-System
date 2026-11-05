# 面试刷题系统（MySQL + Redis 实战项目）

输入应聘岗位 → 自动出题 → 逐题作答 → 与「满分答案」对比复盘。内置 **315 道经典题**（含要点式满分答案，覆盖 14 个类别），配置 LLM 后可按岗位动态生成新题、现场写满分答案并**异步评分点评**。

> 本项目本身就是一个 **MySQL + Redis 的实战练习载体**：MySQL 存题库/面试记录，Redis 承担面试会话状态、抽题缓存、高频错题榜、错题遗忘曲线队列（ZSET）、配置缓存、全场锁（带 TTL + 自愈）。

## 快速开始

```bash
# 一键初始化：启动 MySQL/Redis 容器 → 建表 → 导入内置题库
./scripts/setup.sh

# 启动应用
./scripts/start.sh
# 浏览器打开 http://127.0.0.1:8010
```

## 功能总览

| 页面 | 说明 |
|---|---|
| 开始面试 | 输入岗位自动映射考察权重（14 类画像：Java 后端含 OS/分布式、AI 岗含 Agent 等），也可手动勾选类别。**草稿自动保存**（刷新不丢）、每题计时、Ctrl+Enter 提交 |
| 作答反馈 | 提交即见「你的回答 vs 满分答案」对比；LLM 评分**异步执行**（不等评分就能看答案/下一题，分数 2s 轮询自动补显） |
| 复盘 | 历史场次 + 逐题对比 + 总评与薄弱类别；**一键导出 Markdown 笔记**；错题练习场次单独标记 |
| 错题本 | 得分 < 60 自动入队，遗忘曲线 1/3/7/14 天递增复习；**练习作答也落库进复盘**（LLM 开启时自动评分）；高频错题榜 |
| 题库 | 浏览/搜索/筛选，录入遇到的真题（题目 + 满分答案 + 标签），编辑删除（自动清理 Redis 残留） |
| 设置 | LLM 配置（OpenAI 兼容：DeepSeek / Kimi / 通义 / OpenAI…）+ 连接测试，保存后徽章即时生效 |

## 两种模式

- **离线题库模式（默认，无需任何 key）**：从内置题库按岗位画像抽题，展示满分答案，跳过的题记 0 分进错题本
- **AI 模式**：设置页填入 Base URL / API Key / 模型名——
  - 出题：题库不足时 AI 按岗位生成新题干（自动入库，满分答案在答题时按需生成）
  - 评分：**后台异步** 0-100 打分 + 点评，网络抖动自动重试
  - 总评：整场结束生成水平判断与复习建议（结束时会等待未完成的评分）

## 刷题指南（推荐节奏）

1. **每天一轮「高频混合 · 12 题」**（首页速刷区一键开刷，覆盖网络/MySQL/Redis/JVM/OS/并发六类高频）——LLM 评分自动判分，答错（<60）自动进遗忘曲线
2. **每天顺手清错题本**：到期错题自我判定，连续答对 4 次出队（练习作答也进复盘）
3. **每周看「知识地图」挑薄弱方向**：红点 = 错过的题，做对应单类专项连刷
4. **知识点串联**：答题结果页每题下方有「🔗 关联考点」，点击即可延伸阅读相邻知识点的满分答案——把碎片考点串成体系
5. 遗忘曲线 1/3/7/14 天自动重现错题，无需手动规划复习

> 知识关联由 `scripts/build_knowledge_links.py` 维护（规则建边 + `--llm` 跨类别补边），新增题目后重跑即可重建全库关联。

## 数据安全

**智能备份（默认开启，无需配置）**：应用启动、结束面试、录入/删除题目时自动检查——距上次备份超过 24 小时就在后台静默备份一次。所有数据变更都发生在应用运行时，所以"用过应用就有 ≤24h 新鲜度的恢复点"，不依赖电脑几点开机、不需要定时任务。

```bash
./scripts/backup.sh    # 手动立即备份（mysqldump 全库 → data/backups/，gzip，保留 10 份）
ls data/backups/       # 查看已有备份
```

MySQL/Redis 端口只绑定 127.0.0.1，不暴露局域网。

## 工程化

```bash
.venv/bin/python -m seed.check_seed   # 新增题目后的自检（重复/字数/难度/类别）
.venv/bin/python -m seed.load_seed    # 幂等导入题库
docker compose up -d                  # 启动 MySQL + Redis
```

## Redis 用途一览（练手重点）

| 结构 | Key | 用途 |
|---|---|---|
| HASH | `interview:session:{id}` | 进行中场次的进度（TTL 2h，丢失从 MySQL 重建） |
| SETNX | `interview:lock` | 全场锁（TTL 2h + 结束场次自愈，杜绝永久锁死） |
| ZSET | `review:queue` | 错题遗忘曲线队列，score = 下次复习时间戳 |
| HASH | `review:stage` | 每题当前复习阶段 |
| ZSET | `question:hot` | 高频错题榜（ZINCRBY） |
| LIST | `cache:bank:{category}` | 抽题池缓存（TTL 10min，cache-aside） |
| HASH | `stats:category` | 类别答题统计（缓存，可从 MySQL 重建） |
| HASH | `config:llm` | LLM 配置（优先于 .env） |

## 存储位置

- 代码 / venv / 题库 seed：项目目录（外置盘）
- MySQL 数据：`./data/mysql`（bind mount），备份在 `./data/backups/`
- Redis 数据：`./data/redis`（AOF 持久化）
- Docker 镜像与虚拟磁盘：`/Volumes/xiaoPai/DockerData`（不占系统盘）

## 路线图（未实现，欢迎提需求）

- [ ] 多用户 / 多设备同步（当前为单用户）
- [ ] 岗位画像自定义权重（目前内置映射）
- [ ] 每日学习报告与打卡统计
- [ ] 题目收藏夹 / 自定义标签练习
- [ ] 面试语音作答（Web Speech API）

## 技术栈

FastAPI + SQLAlchemy + PyMySQL ｜ Redis (redis-py) ｜ Vue 3 + ECharts（本地 vendor，无构建）｜ Docker Compose ｜ httpx（OpenAI 兼容 LLM 客户端，带重试）

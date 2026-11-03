# 面试刷题系统（MySQL + Redis 实战项目）

输入应聘岗位 → 自动出题 → 逐题作答 → 与「满分答案」对比复盘。内置 79 道经典题（含要点式满分答案），配置 LLM 后可按岗位动态生成新题、现场写满分答案并给你的回答打分点评。

> 本项目本身就是一个 **MySQL + Redis 的实战练习载体**：MySQL 存题库/面试记录，Redis 承担面试会话状态、抽题缓存、高频错题榜、错题遗忘曲线队列（ZSET）、配置缓存、SETNX 全场锁。

## 快速开始

```bash
# 一键初始化：启动 MySQL/Redis 容器 → 建表 → 导入内置题库
./scripts/setup.sh

# 启动应用
./scripts/start.sh
# 浏览器打开 http://127.0.0.1:8010
```

## 功能

| 页面 | 说明 |
|---|---|
| 开始面试 | 输入岗位（如"Java 后端"），自动映射考察权重：MySQL/Redis 为核心 + Java/JVM/并发/Spring/网络/场景题；可手动勾选类别。逐题作答，提交即见对比 |
| 复盘 | 历史场次列表 → 详情：逐题 你的回答 vs 满分答案 + 评分点评 + 本场总评与薄弱类别 |
| 错题本 | 得分 < 60 自动入队，遗忘曲线 1/3/7/14 天递增复习，连续答对 4 次掌握移出；高频错题榜 |
| 题库 | 浏览/搜索/筛选，录入你遇到的真题（题目 + 满分答案 + 标签），编辑删除 |
| 设置 | LLM 配置（OpenAI 兼容：DeepSeek / Kimi / 通义 / OpenAI…）+ 连接测试 |

## 离线 / 在线两种模式

- **离线题库模式（默认，无需任何 key）**：从内置题库按岗位画像抽题，展示满分答案，评分自查。
- **AI 模式**：设置页填入 Base URL / API Key / 模型名即可启用——
  - 出题：题库不足时 AI 按岗位生成新题（自动入库，来源标记 AI）
  - 满分答案：题库没有的题现场生成并回填
  - 评分：0-100 打分 + 点评（答到的点 / 遗漏的点）
  - 总评：整场结束生成水平判断与复习建议

## Redis 用途一览（练手重点）

| 结构 | Key | 用途 |
|---|---|---|
| HASH | `interview:session:{id}` | 进行中场次的进度（TTL 2h，丢失从 MySQL 重建） |
| SETNX | `interview:lock` | 同一时间仅允许一场进行中面试 |
| ZSET | `review:queue` | 错题遗忘曲线队列，score = 下次复习时间戳 |
| HASH | `review:stage` | 每题当前复习阶段（决定下次间隔） |
| ZSET | `question:hot` | 高频错题榜（ZINCRBY） |
| LIST | `cache:bank:{category}` | 抽题池缓存（TTL 10min，cache-aside） |
| HASH | `stats:category` | 类别答题统计（缓存，可从 MySQL 重建） |
| HASH | `config:llm` | LLM 配置（优先于 .env） |

## 存储位置

- 代码 / venv / 题库 seed：项目目录（外置盘）
- MySQL 数据：`./data/mysql`（bind mount 到容器）
- Redis 数据：`./data/redis`（AOF 持久化）
- Docker 镜像与虚拟磁盘：`/Volumes/xiaoPai/DockerData`（已在 Docker Desktop 中迁移，不占系统盘）

**系统盘新增占用 ≈ 0。** 注意：迁移后 Docker 启动依赖外置盘在线。

## 常用命令

```bash
docker compose up -d                 # 启动 MySQL + Redis
docker compose ps                    # 查看容器状态
docker compose logs -f mysql         # 看日志
.venv/bin/python -m seed.load_seed   # 重新导入题库（幂等）
redis-cli ZRANGE review:queue 0 -1 WITHSCORES   # 看错题队列
redis-cli KEYS '*'                   # 看所有 Redis key
mysql -uroot -pinterview123 interview_db        # 进 MySQL
```

## 技术栈

FastAPI + SQLAlchemy + PyMySQL ｜ Redis (redis-py) ｜ Vue 3 + ECharts（本地 vendor，无构建）｜ Docker Compose ｜ httpx（OpenAI 兼容 LLM 客户端）

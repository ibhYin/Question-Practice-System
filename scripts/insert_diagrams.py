"""向八股体系文档插入 Mermaid 知识速览图（幂等：已含速览图章节则跳过）。

用法：.venv/bin/python -m scripts.insert_diagrams
"""

import sys
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

SEED_DIR = Path(__file__).resolve().parent.parent / "seed"

# 文件名 → 追加的 mermaid 图列表（每图配一个说明标题）
DIAGRAMS: dict[str, list[tuple[str, str]]] = {
    "study_network.yaml": [
        (
            "TCP 三次握手与四次挥手",
            """sequenceDiagram
    participant C as 客户端
    participant S as 服务端
    Note over C,S: 建立连接（三次握手）
    C->>S: SYN (seq=x)
    S->>C: SYN+ACK (seq=y, ack=x+1)
    C->>S: ACK (ack=y+1)
    Note over C,S: 数据传输 …
    Note over C,S: 断开连接（四次挥手）
    C->>S: FIN
    S->>C: ACK
    S->>C: FIN
    C->>S: ACK
    Note over C: TIME_WAIT 等 2MSL""",
        ),
        (
            "从输入 URL 到页面展示",
            """flowchart TD
    A[输入 URL] --> B[DNS 解析<br>缓存 → 根 → 顶级域 → 权威]
    B --> C[TCP 三次握手]
    C --> D{HTTPS?}
    D -- 是 --> E[TLS 握手]
    D -- 否 --> F
    E --> F[发送 HTTP 请求]
    F --> G[服务端处理<br>网关 → 应用 → 缓存/DB]
    G --> H[返回响应]
    H --> I[浏览器渲染<br>DOM → CSSOM → 渲染树 → 绘制]""",
        ),
        (
            "HTTP 缓存决策链",
            """flowchart TD
    A[发起请求] --> B{本地有缓存?}
    B -- 无 --> F[请求服务器 200]
    B -- 有 --> C{强缓存<br>max-age 未过期?}
    C -- 是 --> D[直接用缓存<br>不发请求 200 from cache]
    C -- 已过期 --> E{协商缓存<br>ETag / Last-Modified}
    E -- 未变 --> G[304 继续用本地]
    E -- 已变 --> F""",
        ),
    ],
    "study_mysql.yaml": [
        (
            "一条 UPDATE 的执行流程",
            """flowchart TD
    A[UPDATE 语句] --> B[Server 层<br>分析器 → 优化器]
    B --> C[InnoDB 定位数据页]
    C --> D[写 undo log<br>记旧值供回滚/MVCC]
    D --> E[修改 Buffer Pool 数据页<br>成为脏页]
    E --> F[写 redo log buffer<br>状态 prepare]
    F --> G[写 binlog]
    G --> H[redo log 置 commit<br>两阶段提交完成]
    H --> I[后台刷脏页落盘<br>WAL 不阻塞提交]""",
        ),
        (
            "索引查询路径：回表与覆盖",
            """flowchart TD
    A[SELECT 查询] --> B{查询列都在<br>二级索引中?}
    B -- 是 覆盖索引 --> C[二级索引直接返回<br>Extra: Using index 不回表]
    B -- 否 --> D[二级索引查到主键]
    D --> E[回表: 主键索引取整行]
    A --> F{没有合适索引?}
    F -- 是 --> G[全表扫描逐行过滤]""",
        ),
        (
            "主从复制链路",
            """flowchart LR
    A[主库写入] --> B[写 binlog]
    B --> C[主库 IO 线程发送]
    C --> D[从库 IO 线程<br>写入 relay log]
    D --> E[从库 SQL 线程重放]
    E --> F[从库数据更新]""",
        ),
    ],
    "study_redis.yaml": [
        (
            "持久化：RDB 与 AOF",
            """flowchart TD
    A[写命令到达] --> B{持久化模式}
    B -- RDB --> C[定时/手动 bgsave<br>fork 子进程 + COW 快照]
    C --> D[生成二进制 RDB<br>恢复快 但可能丢段数据]
    B -- AOF --> E[追加写命令到缓冲]
    E --> F[按策略刷盘<br>always / everysec / no]
    F --> G[AOF 过大触发重写<br>fork 生成最小命令集]
    B -- 混合 --> H[重写时 RDB 全量<br>+ 之后 AOF 增量]""",
        ),
        (
            "缓存三问定位决策树",
            """flowchart TD
    A[缓存异常] --> B{数据本来就不存在?}
    B -- 是 → 穿透 --> C[缓存空值 / 布隆过滤器]
    B -- 存在但刚过期 --> D{是热点 key?}
    D -- 是 → 击穿 --> E[互斥锁 / 逻辑过期]
    D -- 普通 key --> F{大量 key 同时失效?}
    F -- 是 → 雪崩 --> G[TTL 加随机 / 多级缓存 / 限流]
    F -- 否 --> H[正常回源]""",
        ),
    ],
    "study_concurrent.yaml": [
        (
            "线程池任务执行流程",
            """flowchart TD
    A[提交任务] --> B{核心线程未满?}
    B -- 是 --> C[新建核心线程执行]
    B -- 否 --> D{队列未满?}
    D -- 是 --> E[任务入队等待]
    D -- 否 --> F{线程数 < max?}
    F -- 是 --> G[新建非核心线程执行]
    F -- 否 --> H[拒绝策略<br>Abort / CallerRuns / Discard]""",
        ),
    ],
    "study_jvm.yaml": [
        (
            "对象分配与 GC 晋升链路",
            """flowchart TD
    A[new 对象] --> B{逃逸分析未逃逸?}
    B -- 是 --> C[标量替换<br>不进堆 栈上分配]
    B -- 否 --> D{是大对象?}
    D -- 是 --> E[直接进老年代]
    D -- 否 --> F[Eden 区 TLAB 分配]
    F --> G[Eden 满 → Minor GC]
    G --> H{存活?}
    H -- 是 --> I[年龄+1 进 Survivor<br>15 岁或动态判断 → 老年代]
    H -- 否 --> J[回收]""",
        ),
    ],
    "study_spring.yaml": [
        (
            "Bean 生命周期",
            """flowchart TD
    A[实例化<br>反射创建] --> B[属性填充<br>依赖注入]
    B --> C[Aware 回调]
    C --> D[BeanPostProcessor 前置]
    D --> E[初始化<br>@PostConstruct → afterPropertiesSet → init-method]
    E --> F[BeanPostProcessor 后置<br>AOP 代理在此生成]
    F --> G[放入单例池使用]
    G --> H[销毁<br>@PreDestroy → destroy → destroy-method]""",
        ),
    ],
    "study_ai_app.yaml": [
        (
            "RAG 完整链路",
            """flowchart LR
    subgraph SG1[离线索引]
        A[文档加载] --> B[清洗分块 chunking]
        B --> C[Embedding 向量化]
        C --> D[(向量数据库)]
    end
    subgraph SG2[在线问答]
        E[用户问题] --> F[查询改写]
        F --> G[向量 + BM25 混合检索]
        G --> H[Rerank 精排]
        H --> I[拼 Prompt 带编号引用]
        I --> J[LLM 生成 + 引用溯源]
    end
    D -.-> G""",
        ),
    ],
    "study_agent.yaml": [
        (
            "ReAct 循环与容错",
            """flowchart TD
    A[任务输入] --> B[Thought<br>分析当前状况]
    B --> C[Action<br>选工具 + 参数]
    C --> D[Observation<br>执行返回结果]
    D --> E{信息足够?}
    E -- 否 --> B
    E -- 是 --> F[Final Answer]
    D -. 工具报错回喂自纠 .-> C
    C -. 无进展检测 .-> G[熔断收口]""",
        ),
    ],
    "study_fullstack.yaml": [
        (
            "JWT 认证时序",
            """sequenceDiagram
    participant U as 客户端
    participant S as 服务端
    U->>S: 登录（账号密码）
    S->>U: 签发 access(短期) + refresh(长期)
    Note over U: 本地保存 token
    U->>S: 请求带 Authorization: Bearer
    S->>S: 验签 + 查过期（无状态校验）
    S->>U: 返回数据
    Note over U,S: access 过期 → refresh 换发新 access
    Note over U,S: 登出 = 吊销 refresh（存库可控制）""",
        ),
    ],
    "study_scenario.yaml": [
        (
            "秒杀流量漏斗",
            """flowchart TD
    A[百万请求] --> B[前端<br>按钮置灰 / 验证码打散]
    B --> C[网关限流<br>只放行库存同量级]
    C --> D[Redis Lua 原子扣减<br>防超卖主战场]
    D --> E[MQ 削峰<br>异步创建订单]
    E --> F[DB 条件更新<br>WHERE stock > 0 最后防线]
    F --> G[对账兜底<br>Redis 与 DB 一致]""",
        ),
    ],
    "study_distributed.yaml": [
        (
            "本地消息表最终一致",
            """flowchart TD
    A[业务操作] --> B[同一本地事务<br>写业务表 + 消息表]
    B --> C[定时任务扫未发送消息]
    C --> D[投递 MQ]
    D --> E{发送成功?}
    E -- 是 --> F[标记已发送]
    E -- 否 --> G[重试退避<br>超限告警人工]
    D --> H[消费端幂等处理]""",
        ),
    ],
}

MARKER = "知识速览图"


def main() -> None:
    updated = 0
    for fname, diagrams in DIAGRAMS.items():
        f = SEED_DIR / fname
        if not f.exists():
            print(f"[跳过] {fname} 不存在")
            continue
        data = yaml.safe_load(f.read_text(encoding="utf-8"))
        content = data["doc"]["content"]
        if MARKER in content:
            print(f"[跳过] {fname} 已含速览图章节")
            continue
        blocks = []
        for title, code in diagrams:
            blocks.append(f"### {title}\n\n```mermaid\n{code}\n```\n")
        data["doc"]["content"] = (
            content.rstrip()
            + f"\n\n# 📌 知识速览图\n\n把上面正文的零散知识串成一张张图——先自己复述，再对照图检验。\n\n"
            + "\n".join(blocks)
        )
        f.write_text(
            yaml.dump(data, allow_unicode=True, sort_keys=False, width=100),
            encoding="utf-8",
        )
        updated += 1
        print(f"[更新] {fname}：+{len(diagrams)} 张图")
    print(f"\n完成：{updated} 个文档已插入图表")


if __name__ == "__main__":
    main()

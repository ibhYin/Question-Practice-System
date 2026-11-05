/* 面试刷题系统 前端（Vue 3，无构建） */
const { createApp, ref, reactive, computed, onMounted, onActivated, onUnmounted, nextTick, watch } = Vue;

/* ---------- API 助手 ---------- */
async function api(path, opts = {}) {
  const res = await fetch('/api' + path, {
    method: opts.method || 'GET',
    headers: { 'Content-Type': 'application/json' },
    body: opts.body !== undefined ? JSON.stringify(opts.body) : undefined,
  });
  let data = {};
  try { data = await res.json(); } catch (e) { /* 空响应 */ }
  if (!res.ok) throw new Error(data.detail || `请求失败 (${res.status})`);
  return data;
}

const CATEGORY_NAMES = {
  MYSQL: 'MySQL', REDIS: 'Redis', JAVA: 'Java 基础', JVM: 'JVM',
  CONCURRENT: '并发编程', SPRING: 'Spring', NETWORK: '计算机网络', SCENARIO: '场景设计',
  AI_APP: 'AI 应用开发', AGENT: 'Agent 开发', FULLSTACK: '全栈开发',
  OS: '操作系统', DISTRIBUTED: '分布式', ALGO: '算法', PYTHON: 'Python',
};
const DIFF_LABEL = { 1: '易', 2: '中', 3: '难' };
const DIFF_COLOR = { 1: 'ok', 2: 'warn', 3: 'bad' };

function fmtTime(iso) {
  if (!iso) return '-';
  const d = new Date(iso);
  const p = (n) => String(n).padStart(2, '0');
  return `${d.getMonth() + 1}-${p(d.getDate())} ${p(d.getHours())}:${p(d.getMinutes())}`;
}
/* 满分答案轻量渲染：**加粗** 和 `代码`，其余按纯文本 */
function renderAnswer(text) {
  if (!text) return '';
  return text
    .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
    .replace(/\*\*(.+?)\*\*/g, '<b>$1</b>')
    .replace(/`([^`\n]+?)`/g, '<code>$1</code>');
}
function scoreClass(s) {
  if (s == null) return '';
  if (s >= 80) return 'ok';
  if (s >= 60) return 'warn';
  return 'bad';
}

/* ---------- 面试进行中 ---------- */
function fmtElapsed(sec) {
  const m = Math.floor(sec / 60), s = sec % 60;
  return `${String(m).padStart(2, '0')}:${String(s).padStart(2, '0')}`;
}

const InterviewView = {
  props: ['sessionId'],
  emits: ['finished', 'abandoned'],
  setup(props, { emit }) {
    const state = reactive({
      loading: true, error: '',
      position: '', total: 0, current: 0,
      question: null,
      answer: '',
      submitting: false,
      result: null,          // 最近一次提交结果
      addedReview: false,    // 离线模式：本题已手动加入复习
      phase: 'answering',    // answering | result | summary
      summary: null,
      llmEnabled: false,
      elapsed: 0,            // 本题答题秒数（后台计时，不显示）
      timerId: null,
      pollTimer: null,       // 异步评分轮询
      pollTries: 0,
      knowledge: [],         // 本题关联考点（知识链路）
      relatedDetail: null,   // 点击关联考点弹出的详情
    });

    function startTimer() {
      state.elapsed = 0;
      if (state.timerId) clearInterval(state.timerId);
      state.timerId = setInterval(() => { state.elapsed++; }, 1000);
    }
    function stopTimer() {
      if (state.timerId) { clearInterval(state.timerId); state.timerId = null; }
    }

    /* 草稿：按 场次+题目 存 localStorage，刷新/崩溃不丢答案 */
    const draftKey = () => state.question ? `draft:${props.sessionId}:${state.question.id}` : '';
    function restoreDraft() {
      try {
        const saved = localStorage.getItem(draftKey());
        state.answer = saved || '';
      } catch (e) { state.answer = ''; }
    }
    function saveDraft() {
      try { localStorage.setItem(draftKey(), state.answer); } catch (e) { /* 忽略 */ }
    }
    function clearDraft() {
      try { localStorage.removeItem(draftKey()); } catch (e) { /* 忽略 */ }
    }

    /* 异步评分轮询：每 2s 查一次，最多 45 次（90s） */
    function pollScore() {
      if (state.pollTimer) clearInterval(state.pollTimer);
      state.pollTries = 0;
      state.pollTimer = setInterval(async () => {
        state.pollTries++;
        if (state.pollTries > 45 || state.phase !== 'result') {
          clearInterval(state.pollTimer); state.pollTimer = null;
          if (state.result) state.result.scoring = false;
          return;
        }
        try {
          const r = await api(`/interviews/${props.sessionId}/answers/${state.result.question_id}/score`);
          if (r.score != null || (!r.pending && state.pollTries > 6)) {
            state.result.score = r.score;
            state.result.ai_comment = r.ai_comment;
            state.result.scoring = false;
            clearInterval(state.pollTimer); state.pollTimer = null;
          }
        } catch (e) { /* 网络抖动继续轮询 */ }
      }, 2000);
    }

    async function loadProgress() {
      try {
        const p = await api(`/interviews/${props.sessionId}/progress`);
        if (p.status !== 'in_progress') {
          const detail = await api(`/interviews/${props.sessionId}`);
          state.summary = detail;
          state.phase = 'summary';
        } else {
          state.question = p.question;
          state.total = p.total;
          state.current = p.current || 0;
          state.llmEnabled = p.llm_enabled;
          restoreDraft();
          startTimer();
        }
      } catch (e) { state.error = e.message; }
      state.loading = false;
    }

    /* 知识链路：结果页加载本题关联考点 */
    async function loadKnowledge(qid) {
      state.knowledge = [];
      try {
        const k = await api(`/questions/knowledge/${qid}`);
        state.knowledge = k.related;
      } catch (e) { /* 关联加载失败不干扰答题 */ }
    }
    function openRelated(k) {
      state.relatedDetail = k;   // k 含 title/category_name/model_answer
    }

    async function submit(skip = false) {
      state.submitting = true; state.error = '';
      try {
        const r = await api(`/interviews/${props.sessionId}/answers`, {
          method: 'POST',
          body: { question_id: state.question.id, user_answer: skip ? '' : state.answer },
        });
        stopTimer();
        clearDraft();
        state.result = r;
        state.current = r.seq;
        state.phase = 'result';
        if (r.scoring) pollScore();   // 异步评分：立即展示对比，分数轮询补显
        loadKnowledge(r.question_id); // 后台拉关联考点，不阻塞展示
      } catch (e) { state.error = e.message; }
      state.submitting = false;
    }

    async function nextQuestion() {
      if (state.result.finished) return finish();
      state.question = state.result.next_question;
      state.answer = '';
      state.result = null;
      state.addedReview = false;
      state.phase = 'answering';
      restoreDraft();
      startTimer();
    }

    async function addToReview() {
      try {
        await api(`/review/${state.result.question_id}/add`, { method: 'POST' });
        state.addedReview = true;
      } catch (e) { state.error = e.message; }
    }

    async function finish() {
      try {
        await api(`/interviews/${props.sessionId}/finish`, { method: 'POST' });
      } catch (e) { /* 忽略，接着拉详情 */ }
      const detail = await api(`/interviews/${props.sessionId}`);
      state.summary = detail;
      state.phase = 'summary';
      emit('finished');
    }

    async function abandon() {
      if (!confirm('确定放弃本场面试？已答题目仍会保存在复盘中。')) return;
      await api(`/interviews/${props.sessionId}/abandon`, { method: 'POST' });
      emit('abandoned');
    }

    onMounted(loadProgress);
    onUnmounted(() => { stopTimer(); if (state.pollTimer) clearInterval(state.pollTimer); });

    return { state, submit, nextQuestion, finish, abandon, addToReview, saveDraft, fmtElapsed, renderAnswer, loadKnowledge, openRelated, CATEGORY_NAMES, DIFF_LABEL, DIFF_COLOR, scoreClass };
  },
  template: `
  <div>
    <div v-if="state.loading" class="card">加载中…</div>

    <!-- 答题中 -->
    <template v-else-if="state.phase === 'answering' && state.question">
      <div class="progress-wrap">
        <span class="badge">第 {{ state.question.seq }} / {{ state.total }} 题</span>
        <div class="progress-track"><div class="progress-fill" :style="{width: (state.question.seq - 1) / state.total * 100 + '%'}"></div></div>
        <button class="btn small ghost danger" @click="abandon">放弃本场</button>
      </div>
      <div class="card q-card">
        <div class="q-meta">
          <span class="badge">{{ CATEGORY_NAMES[state.question.category] || state.question.category }}</span>
          <span class="badge" :class="DIFF_COLOR[state.question.difficulty]">难度·{{ DIFF_LABEL[state.question.difficulty] }}</span>
          <span v-for="t in state.question.tags" :key="t" class="badge gray">{{ t }}</span>
        </div>
        <div class="q-title">{{ state.question.title }}</div>
      </div>
      <div class="card">
        <h3>你的回答 <span class="hint">草稿自动保存 · Ctrl+Enter 提交</span></h3>
        <textarea v-model="state.answer" class="input" rows="7"
                  @input="saveDraft" @keydown.ctrl.enter.prevent="submit(false)"
                  placeholder="像真实面试一样，把你知道的点都写出来：概念 → 原理 → 实践…（结构化作答更容易拿分）"></textarea>
        <div class="answer-actions">
          <button class="btn primary" :disabled="state.submitting" @click="submit(false)">{{ state.submitting ? '提交中…' : (state.llmEnabled ? '提交本题（AI 评分）' : '提交本题，看满分答案') }}</button>
          <button class="btn ghost" :disabled="state.submitting" @click="submit(true)">这题不会，直接看答案</button>
        </div>
        <p v-if="state.error" class="error">{{ state.error }}</p>
      </div>
    </template>

    <!-- 单题结果 -->
    <template v-else-if="state.phase === 'result' && state.result">
      <div class="progress-wrap">
        <span class="badge">第 {{ state.result.seq }} / {{ state.total }} 题 · 已提交</span>
        <div class="progress-track"><div class="progress-fill" :style="{width: state.result.seq / state.total * 100 + '%'}"></div></div>
      </div>
      <div class="card result-panel">
        <div class="score-row">
          <div v-if="state.result.score != null">
            <div class="score-ring" :class="scoreClass(state.result.score)"
                 :style="{background: state.result.score >= 80 ? '#16a34a' : state.result.score >= 60 ? '#d97706' : '#dc2626'}">
              {{ state.result.score }}<small style="font-size:11px;font-weight:400">分</small>
            </div>
          </div>
          <div v-else-if="state.result.scoring" class="badge warn" style="align-self:center; padding: 8px 16px">AI 评分中…</div>
          <div v-if="state.result.ai_comment" style="font-weight:600">AI 点评</div>
          <div v-else-if="state.result.scoring" class="hint" style="align-self:center">评分完成后自动显示，可先点下一题继续</div>
        </div>
        <div v-if="state.result.ai_comment" class="ai-comment">{{ state.result.ai_comment }}</div>
        <div class="compare">
          <div>
            <h4>你的回答</h4>
            <div class="box you">{{ state.result.user_answer || '（未作答）' }}</div>
          </div>
          <div>
            <h4>⭐ 满分答案</h4>
            <div class="box model" v-html="renderAnswer(state.result.model_answer)"></div>
          </div>
        </div>
        <div v-if="state.knowledge && state.knowledge.length" class="know-strip">
          <span class="hint" style="flex-shrink:0; align-self:center">🔗 关联考点</span>
          <span v-for="k in state.knowledge" :key="k.id" class="chip small" @click="openRelated(k)">{{ k.category_name }} · {{ k.title }}</span>
        </div>
        <div class="answer-actions">
          <button class="btn primary" @click="nextQuestion">{{ state.result.finished ? '查看本场总评 →' : '下一题 →' }}</button>
          <button v-if="state.result.score == null && !state.addedReview" class="btn" @click="addToReview">＋ 这题没掌握，加入复习</button>
          <span v-if="state.addedReview" class="badge ok" style="align-self:center">已加入错题本，明天复习</span>
        </div>
      </div>
    </template>

    <!-- 本场总结 -->
    <template v-else-if="state.phase === 'summary' && state.summary">
      <div class="card">
        <div class="score-row">
          <div>
            <h3 style="font-size:18px">面试结束 · {{ state.summary.position }}</h3>
            <span class="hint">{{ state.summary.question_count }} 题 · {{ fmtTime(state.summary.started_at) }}</span>
          </div>
          <div v-if="state.summary.total_score != null" class="score-big" :class="scoreClass(state.summary.total_score)" style="margin-left:auto;font-size:30px">
            {{ state.summary.total_score }}<small style="font-size:13px"> 分</small>
          </div>
        </div>
        <div v-if="state.summary.summary" class="summary-box">{{ state.summary.summary }}</div>
        <div v-if="state.summary.weak_categories && state.summary.weak_categories.length" style="margin-bottom:10px">
          <span class="hint">薄弱类别：</span>
          <span v-for="w in state.summary.weak_categories" :key="w" class="badge bad" style="margin-right:6px">{{ CATEGORY_NAMES[w] || w }}</span>
        </div>
        <div v-for="a in state.summary.answers" :key="a.seq" class="detail-item" style="margin-top:10px">
          <div class="detail-head">
            <span class="badge">{{ a.seq }}</span>
            <span class="t" style="font-size:14px">{{ a.question_title }}</span>
            <span v-if="a.score != null" class="badge" :class="scoreClass(a.score)">{{ a.score }} 分</span>
          </div>
          <div class="detail-body">
            <div class="compare">
              <div><h4>你的回答</h4><div class="box you" style="max-height:none">{{ a.user_answer || '（未作答）' }}</div></div>
              <div><h4>满分答案</h4><div class="box model" style="max-height:none" v-html="renderAnswer(a.model_answer)"></div></div>
            </div>
          </div>
        </div>
      </div>
    </template>
    <p v-if="state.error && !state.loading" class="error">{{ state.error }}</p>

    <!-- 关联考点详情弹窗（知识链路延伸阅读） -->
    <div v-if="state.relatedDetail" class="modal-mask" @click.self="state.relatedDetail = null">
      <div class="modal">
        <h3>{{ state.relatedDetail.title }}</h3>
        <div class="q-meta" style="margin-bottom:12px">
          <span class="badge">{{ state.relatedDetail.category_name }}</span>
          <span class="badge gray">难度·{{ DIFF_LABEL[state.relatedDetail.difficulty] }}</span>
        </div>
        <div class="box model" style="max-height:60vh; overflow:auto" v-html="renderAnswer(state.relatedDetail.model_answer || '（暂无满分答案）')"></div>
        <div class="answer-actions">
          <button class="btn" @click="state.relatedDetail = null">关闭</button>
        </div>
      </div>
    </div>
  </div>
  `,
};

/* ---------- 知识地图 ---------- */
const MapView = {
  name: 'MapView',
  setup() {
    const state = reactive({
      loading: true, error: '', category: 'MYSQL',
      stats: { nodes: 0, links: 0, linked: 0 },
      detail: null,   // 点节点弹出的题目+满分答案+关联
    });
    let chartInst = null;
    const chartEl = ref(null);

    const CAT_COLORS = {
      MYSQL: '#4f5df0', REDIS: '#dc2626', JAVA: '#b45309', JVM: '#7c3aed', CONCURRENT: '#0891b2',
      SPRING: '#16a34a', NETWORK: '#2563eb', SCENARIO: '#9333ea', AI_APP: '#db2777', AGENT: '#ea580c',
      FULLSTACK: '#0d9488', OS: '#475569', DISTRIBUTED: '#a16207', ALGO: '#be185d', PYTHON: '#ca8a04',
    };

    async function load() {
      state.loading = true; state.error = '';
      try {
        const d = await api(`/questions/knowledge/map?category=${state.category}`);
        state.stats = {
          nodes: d.nodes.length, links: d.links.length,
          linked: new Set([...d.links.flatMap(l => [l.source, l.target])]).size,
        };
        state.loading = false;
        nextTick(() => render(d));
      } catch (e) { state.error = e.message; state.loading = false; }
    }

    function render(d) {
      if (!chartEl.value) return;
      chartInst = chartInst || echarts.init(chartEl.value);
      const degree = {};
      d.links.forEach(l => { degree[l.source] = (degree[l.source] || 0) + 1; degree[l.target] = (degree[l.target] || 0) + 1; });
      chartInst.setOption({
        tooltip: {
          formatter: (p) => p.dataType === 'node'
            ? `${p.data.categoryName}<br/>${p.data.fullName}<br/>答错 ${p.data.wrong_count} 次`
            : '',
        },
        series: [{
          type: 'graph', layout: 'force', roam: true, draggable: true,
          force: { repulsion: 130, edgeLength: 60, gravity: 0.08 },
          label: { show: true, fontSize: 10, color: '#5b6478', formatter: (p) => p.data.name },
          itemStyle: { borderColor: '#fff', borderWidth: 1 },
          lineStyle: { color: '#c3cad9', width: 1, curveness: 0.1 },
          emphasis: { focus: 'adjacency', lineStyle: { width: 2.5, color: '#4f5df0' } },
          data: d.nodes.map(n => ({
            id: String(n.id), name: n.name, fullName: d.nodes.find(x => x.id === n.id) && n.name,
            value: n.id, category: n.category, categoryName: n.category, wrong_count: n.wrong_count,
            itemStyle: {
              color: n.wrong_count > 0 ? '#dc2626' : (CAT_COLORS[n.category] || '#64748b'),
            },
            symbolSize: 14 + Math.min(n.wrong_count, 5) * 5 + Math.min(degree[n.id] || 0, 6) * 1.5,
          })),
          links: d.links.map(l => ({ source: String(l.source), target: String(l.target) })),
        }],
      }, true);
      chartInst.off('click');
      chartInst.on('click', async (p) => {
        if (p.dataType !== 'node') return;
        try {
          const k = await api(`/questions/knowledge/${p.data.value}`);
          const node = d.nodes.find(n => n.id === p.data.value);
          state.detail = {
            id: p.data.value, title: node ? node.name : p.data.name,
            category: node ? node.category : '', wrong_count: node ? node.wrong_count : 0,
            related: k.related, category_name: k.category_name,
          };
        } catch (e) { state.error = e.message; }
      });
    }

    function pick(c) { state.category = c; load(); }
    function closeDetail() { state.detail = null; }
    onMounted(load);
    onActivated(() => { if (!state.loading) load(); });
    onUnmounted(() => { if (chartInst) { chartInst.dispose(); chartInst = null; } });
    return { state, chartEl, pick, closeDetail, renderAnswer, CATEGORY_NAMES };
  },
  template: `
  <div>
    <div class="card" style="padding:14px 18px; margin-bottom:14px; display:flex; gap:10px; flex-wrap:wrap; align-items:center">
      <b style="font-size:14px">知识地图</b>
      <select v-model="state.category" class="input" style="width:auto; min-width:130px" @change="pick(state.category)">
        <option v-for="(name, code) in CATEGORY_NAMES" :key="code" :value="code">{{ name }}</option>
      </select>
      <span class="hint">{{ state.stats.nodes }} 个考点 · {{ state.stats.links }} 条关联 · {{ state.stats.linked }} 题入网</span>
      <span class="hint" style="margin-left:auto">🔴 红点 = 答错过的薄弱点 · 点大小 = 错题次数 + 关联度</span>
    </div>
    <div class="card" style="padding:0; height:600px; position:relative">
      <div v-if="state.loading" style="position:absolute; inset:0; display:flex; align-items:center; justify-content:center">加载中…</div>
      <div v-show="!state.loading" ref="chartEl" style="width:100%; height:100%"></div>
    </div>

    <!-- 节点详情：题目 + 满分答案 + 关联链路 -->
    <div v-if="state.detail" class="modal-mask" @click.self="closeDetail">
      <div class="modal">
        <h3>{{ state.detail.title }}</h3>
        <div class="q-meta" style="margin-bottom:12px">
          <span class="badge">{{ state.detail.category_name }}</span>
          <span v-if="state.detail.wrong_count" class="badge bad">答错 {{ state.detail.wrong_count }} 次</span>
        </div>
        <div v-if="state.detail.related.length" style="margin-bottom:14px">
          <h4 style="font-size:13px; color:#5b6478; margin-bottom:8px">🔗 知识链路（{{ state.detail.related.length }} 个关联考点）</h4>
          <div class="rel-list">
            <div v-for="r in state.detail.related" :key="r.id" class="rel-item">
              <span class="badge">{{ r.category_name }}</span>
              <span class="t">{{ r.title }}</span>
            </div>
          </div>
        </div>
        <div class="answer-full" v-html="renderAnswer(state.detail.related.find(r => r.id === state.detail.id)?.model_answer || '')"></div>
        <div class="answer-actions">
          <button class="btn" @click="closeDetail">关闭</button>
        </div>
      </div>
    </div>
  </div>
  `,
};

/* ---------- 复盘（历史场次） ---------- */
const SessionsView = {
  name: 'SessionsView',
  setup() {
    const state = reactive({ list: [], detail: null, loading: true });
    async function load() {
      // 已有数据时静默刷新（KeepAlive 激活），仅首次显示加载态
      state.loading = state.list.length === 0 && !state.detail;
      state.list = await api('/interviews?limit=50');
      state.loading = false;
    }
    async function openDetail(id) {
      state.detail = await api(`/interviews/${id}`);
      window.scrollTo({ top: 0 });
    }
    function back() { state.detail = null; }
    function exportMd() { window.open('/api/interviews/' + state.detail.id + '/export'); }
    onMounted(load);
    onActivated(() => { if (state.list.length || state.detail) load(); });
    return { state, openDetail, back, exportMd, fmtTime, scoreClass, renderAnswer, CATEGORY_NAMES, DIFF_LABEL };
  },
  template: `
  <div>
    <template v-if="!state.detail">
      <h3 style="margin-bottom:14px">历史面试场次</h3>
      <div v-if="state.loading" class="card">加载中…</div>
      <div v-else-if="!state.list.length" class="card empty">还没有面试记录，去开始第一场吧</div>
      <div v-else class="list-row" v-for="s in state.list" :key="s.id" @click="openDetail(s.id)">
        <span class="pos">{{ s.position }}</span>
        <span v-if="s.mode === 'REVIEW'" class="badge gray">错题练习</span>
        <span class="badge" :class="s.status === 'finished' ? 'ok' : s.status === 'abandoned' ? 'gray' : 'warn'">
          {{ s.status === 'finished' ? '已完成' : s.status === 'abandoned' ? '已放弃' : '进行中' }}</span>
        <span>{{ s.question_count }} 题</span>
        <span v-if="s.total_score != null" class="score-big" :class="scoreClass(s.total_score)">{{ s.total_score }}</span>
        <span class="time">{{ fmtTime(s.started_at) }}</span>
      </div>
    </template>
    <template v-else>
      <button class="btn small ghost" @click="back">← 返回列表</button>
      <button class="btn small" style="margin-left:8px" @click="exportMd">⬇ 导出笔记 (Markdown)</button>
      <div class="card" style="margin-top:12px">
        <div class="score-row">
          <div>
            <h3 style="font-size:18px">{{ state.detail.position }}
              <span v-if="state.detail.mode === 'REVIEW'" class="badge gray" style="font-size:12px">错题练习</span></h3>
            <span class="hint">{{ state.detail.question_count }} 题 · {{ fmtTime(state.detail.started_at) }}
              · {{ state.detail.status === 'finished' ? '已完成' : state.detail.status === 'abandoned' ? '已放弃' : '进行中' }}</span>
          </div>
          <div v-if="state.detail.total_score != null" class="score-big" :class="scoreClass(state.detail.total_score)" style="margin-left:auto;font-size:28px">{{ state.detail.total_score }}<small style="font-size:13px"> 分</small></div>
        </div>
        <div v-if="state.detail.summary" class="summary-box">{{ state.detail.summary }}</div>
        <div v-if="state.detail.weak_categories && state.detail.weak_categories.length" style="margin-bottom:10px">
          <span class="hint">薄弱类别：</span>
          <span v-for="w in state.detail.weak_categories" :key="w" class="badge bad" style="margin-right:6px">{{ CATEGORY_NAMES[w] || w }}</span>
        </div>
        <div v-for="a in state.detail.answers" :key="a.seq" class="detail-item">
          <div class="detail-head">
            <span class="badge">{{ a.seq }}</span>
            <span class="badge gray">{{ CATEGORY_NAMES[a.category] || a.category }}</span>
            <span class="t">{{ a.question_title }}</span>
            <span v-if="a.score != null" class="badge" :class="scoreClass(a.score)">{{ a.score }} 分</span>
          </div>
          <div class="detail-body">
            <div v-if="a.ai_comment" class="ai-comment">{{ a.ai_comment }}</div>
            <div class="compare">
              <div><h4>你的回答</h4><div class="box you" style="max-height:none">{{ a.answered ? (a.user_answer || '（未作答）') : '未作答' }}</div></div>
              <div><h4>满分答案</h4><div class="box model" style="max-height:none" v-html="renderAnswer(a.answered ? a.model_answer : '（提交后可见）')"></div></div>
            </div>
          </div>
        </div>
      </div>
    </template>
  </div>
  `,
};

/* ---------- 错题本 / 复习 ---------- */
const ReviewView = {
  name: 'ReviewView',
  setup() {
    const state = reactive({
      loading: true, items: [], queueSize: 0,
      phase: 'list',           // list | practicing
      idx: 0, answer: '', revealed: false,
      mastered: 0, practiced: 0, recorded: 0, rsid: null,
      submitting: false, error: '',
    });
    async function load() {
      state.loading = state.items.length === 0; // 静默刷新
      const d = await api('/review/due');
      state.items = d.items;
      state.queueSize = d.queue_size;
      state.loading = false;
    }
    async function start() {
      if (!state.items.length) return;
      state.phase = 'practicing'; state.idx = 0; state.answer = ''; state.revealed = false;
      state.mastered = 0; state.practiced = 0; state.recorded = 0; state.error = '';
      try {
        // 登记为 REVIEW 场次：练习作答进复盘，LLM 开启时自动评分
        const rs = await api('/review/session', { method: 'POST', body: { ids: state.items.map(i => i.id) } });
        state.rsid = rs.session_id;
      } catch (e) { state.rsid = null; }
    }
    function reveal() { state.revealed = true; }
    async function judge(correct) {
      state.submitting = true;
      try {
        const it = state.items[state.idx];
        // 1. 队列更新（自我判定驱动遗忘曲线）
        const r = await api(`/review/${it.id}/answer`, { method: 'POST', body: { correct, user_answer: state.answer } });
        // 2. 练习记录落库（REVIEW 场次，LLM 开启时后台评分）
        if (state.rsid) {
          try {
            await api(`/interviews/${state.rsid}/answers`, { method: 'POST', body: { question_id: it.id, user_answer: state.answer } });
            state.recorded++;
          } catch (e) { /* 记录失败不打断复习 */ }
        }
        state.practiced++;
        if (r.mastered) state.mastered++;
        state.idx++; state.answer = ''; state.revealed = false;
        if (state.idx >= state.items.length) {
          if (state.rsid) {
            try { await api(`/interviews/${state.rsid}/finish`, { method: 'POST', body: {} }); } catch (e) { /* 忽略 */ }
            state.rsid = null;
          }
          state.phase = 'list';
          await load();
        }
      } catch (e) { state.error = e.message; }
      state.submitting = false;
    }
    onMounted(load);
    onActivated(() => { if (state.phase === 'list') load(); });  // 练习中不打扰
    const cur = computed(() => state.items[state.idx] || null);
    return { state, cur, load, start, reveal, judge, renderAnswer, CATEGORY_NAMES, DIFF_LABEL };
  },
  template: `
  <div>
    <div v-if="state.loading" class="card">加载中…</div>

    <template v-else-if="state.phase === 'list'">
      <div class="card" style="margin-bottom:16px">
        <h3>错题本 · 遗忘曲线复习</h3>
        <p class="hint" style="margin-bottom:6px">答错（&lt;60 分）的题自动进入复习队列，间隔 1 → 3 → 7 → 14 天重复出现，连续答对 4 次即掌握移出。练习作答会保存到复盘（可开启 LLM 自动评分）。</p>
        <div class="stat-grid" style="max-width:420px">
          <div class="stat"><b class="warn">{{ state.items.length }}</b><span>现在到期待复习</span></div>
          <div class="stat"><b>{{ state.queueSize }}</b><span>队列总数</span></div>
        </div>
        <div style="margin-top:16px" v-if="state.items.length">
          <button class="btn primary big" @click="start">开始复习（{{ state.items.length }} 题）→</button>
        </div>
      </div>
      <div v-if="!state.items.length" class="card empty">
        {{ state.queueSize ? '今天的错题都复习完了，明天再来 💪' : '错题队列为空 —— 答错的题会自动出现在这里' }}
      </div>
      <div v-else class="review-list">
        <div class="item" v-for="it in state.items" :key="it.id">
          <span class="badge">{{ it.category_name }}</span>
          <span class="t">{{ it.title }}</span>
          <span class="stage-dots" :title="'复习进度第 ' + (it.stage + 1) + ' 阶'">
            <i v-for="n in 4" :key="n" :class="{on: n <= it.stage + 1}"></i>
          </span>
        </div>
      </div>
    </template>

    <template v-else>
      <div class="progress-wrap">
        <span class="badge">复习 {{ state.idx + 1 }} / {{ state.items.length }}</span>
        <div class="progress-track"><div class="progress-fill" :style="{width: state.idx / state.items.length * 100 + '%'}"></div></div>
        <span class="hint">已掌握 {{ state.mastered }}</span>
      </div>
      <div class="card q-card" v-if="cur">
        <div class="q-meta">
          <span class="badge">{{ cur.category_name }}</span>
          <span class="badge gray">难度·{{ DIFF_LABEL[cur.difficulty] }}</span>
        </div>
        <div class="q-title">{{ cur.title }}</div>
      </div>
      <div class="card" v-if="cur">
        <template v-if="!state.revealed">
          <h3>回忆作答（可选）</h3>
          <textarea v-model="state.answer" class="input" rows="6" placeholder="先凭记忆写下要点，再对照满分答案自查——这一步才是复习的价值"></textarea>
          <div class="answer-actions">
            <button class="btn primary" @click="reveal">对照满分答案 →</button>
          </div>
        </template>
        <template v-else>
          <div class="compare">
            <div><h4>你的回忆</h4><div class="box you">{{ state.answer || '（没写，纯靠脑内复盘）' }}</div></div>
            <div><h4>⭐ 满分答案</h4><div class="box model" style="max-height:none" v-html="renderAnswer(cur.model_answer || '（该题暂无满分答案）')"></div></div>
          </div>
          <div class="self-judge">
            <span class="hint" style="align-self:center">这题现在掌握了吗？</span>
            <button class="btn primary" :disabled="state.submitting" @click="judge(true)">✓ 答对了（间隔拉长）</button>
            <button class="btn danger" :disabled="state.submitting" @click="judge(false)">✗ 还不行（明天再来）</button>
          </div>
        </template>
      </div>
      <p v-if="state.error" class="error">{{ state.error }}</p>
    </template>
  </div>
  `,
};

/* ---------- 题库管理 ---------- */
const BankView = {
  name: 'BankView',
  setup() {
    const state = reactive({
      items: [], total: 0, page: 1, size: 20, loading: true,
      filters: { category: '', difficulty: '', source: '', q: '' },
      showForm: false, editingId: null, saving: false, error: '',
      form: { title: '', category: 'MYSQL', difficulty: 2, tags: '', position_tags: '', model_answer: '' },
    });
    async function load() {
      state.loading = state.items.length === 0; // 静默刷新
      const f = state.filters;
      const qs = new URLSearchParams();
      if (f.category) qs.set('category', f.category);
      if (f.difficulty) qs.set('difficulty', f.difficulty);
      if (f.source) qs.set('source', f.source);
      if (f.q) qs.set('q', f.q);
      qs.set('page', state.page); qs.set('size', state.size);
      const d = await api(`/questions?${qs}`);
      state.items = d.items; state.total = d.total;
      state.loading = false;
    }
    function resetPage() { state.page = 1; load(); }
    function openAdd() {
      state.editingId = null;
      state.form = { title: '', category: 'MYSQL', difficulty: 2, tags: '', position_tags: '', model_answer: '' };
      state.showForm = true;
    }
    function openEdit(q) {
      state.editingId = q.id;
      state.form = {
        title: q.title, category: q.category, difficulty: q.difficulty,
        tags: (q.tags || []).join('、'), position_tags: (q.position_tags || []).join('、'),
        model_answer: q.model_answer,
      };
      state.showForm = true;
    }
    async function save() {
      state.saving = true; state.error = '';
      const body = {
        title: state.form.title,
        category: state.form.category,
        difficulty: Number(state.form.difficulty),
        tags: state.form.tags.split(/[、,，\s]+/).map(s => s.trim()).filter(Boolean),
        position_tags: state.form.position_tags.split(/[、,，\s]+/).map(s => s.trim()).filter(Boolean),
        model_answer: state.form.model_answer,
      };
      try {
        if (state.editingId) await api(`/questions/${state.editingId}`, { method: 'PUT', body });
        else await api('/questions', { method: 'POST', body });
        state.showForm = false;
        await load();
      } catch (e) { state.error = e.message; }
      state.saving = false;
    }
    async function del(q) {
      if (!confirm(`删除题目：${q.title.slice(0, 40)}…？`)) return;
      try { await api(`/questions/${q.id}`, { method: 'DELETE' }); await load(); }
      catch (e) { alert(e.message); }
    }
    const pages = computed(() => Math.max(1, Math.ceil(state.total / state.size)));
    onMounted(load);
    onActivated(load);
    return { state, load, resetPage, openAdd, openEdit, save, del, pages, CATEGORY_NAMES, DIFF_LABEL };
  },
  template: `
  <div>
    <div class="filter-bar card" style="padding:14px 18px">
      <select v-model="state.filters.category" class="input" @change="resetPage">
        <option value="">全部类别</option>
        <option v-for="(name, code) in CATEGORY_NAMES" :key="code" :value="code">{{ name }}</option>
      </select>
      <select v-model="state.filters.difficulty" class="input" @change="resetPage">
        <option value="">全部难度</option>
        <option value="1">易</option><option value="2">中</option><option value="3">难</option>
      </select>
      <select v-model="state.filters.source" class="input" @change="resetPage">
        <option value="">全部来源</option>
        <option value="BUILTIN">内置</option><option value="MANUAL">手动录入</option><option value="AI">AI 生成</option>
      </select>
      <input v-model.trim="state.filters.q" class="input grow" placeholder="搜索题目/答案关键词，回车搜索" @keyup.enter="resetPage">
      <button class="btn primary" @click="openAdd">＋ 录入真题</button>
    </div>

    <div class="card table-card">
      <table class="q-table">
        <thead><tr><th style="width:50px">ID</th><th>题目</th><th style="width:110px">类别</th><th style="width:70px">难度</th><th style="width:90px">来源</th><th style="width:130px">操作</th></tr></thead>
        <tbody>
          <tr v-if="state.loading"><td colspan="6" class="empty">加载中…</td></tr>
          <tr v-else-if="!state.items.length"><td colspan="6" class="empty">没有符合条件的题目</td></tr>
          <tr v-for="q in state.items" :key="q.id">
            <td>{{ q.id }}</td>
            <td class="title-cell" :title="q.title">{{ q.title }}</td>
            <td><span class="badge">{{ CATEGORY_NAMES[q.category] || q.category }}</span></td>
            <td>{{ DIFF_LABEL[q.difficulty] }}</td>
            <td><span class="badge" :class="{gray: q.source !== 'AI', ok: q.source === 'AI'}">{{ q.source === 'BUILTIN' ? '内置' : q.source === 'AI' ? 'AI' : '手动' }}</span></td>
            <td>
              <button class="btn small" @click="openEdit(q)">编辑</button>
              <button class="btn small ghost danger" @click="del(q)">删除</button>
            </td>
          </tr>
        </tbody>
      </table>
      <div class="table-foot">
        <span>共 {{ state.total }} 题</span>
        <div style="display:flex;gap:8px;align-items:center">
          <button class="btn small" :disabled="state.page <= 1" @click="state.page--; load()">上一页</button>
          <span>{{ state.page }} / {{ pages }}</span>
          <button class="btn small" :disabled="state.page >= pages" @click="state.page++; load()">下一页</button>
        </div>
      </div>
    </div>

    <!-- 录入/编辑弹窗 -->
    <div v-if="state.showForm" class="modal-mask" @click.self="state.showForm = false">
      <div class="modal">
        <h3>{{ state.editingId ? '编辑题目' : '录入遇到的面试真题' }}</h3>
        <div class="form-row">
          <label>题目 *</label>
          <textarea v-model="state.form.title" class="input" rows="2" placeholder="面试官的原题，越接近原话越好"></textarea>
        </div>
        <div class="grid2">
          <div class="form-row">
            <label>类别</label>
            <select v-model="state.form.category" class="input">
              <option v-for="(name, code) in CATEGORY_NAMES" :key="code" :value="code">{{ name }}</option>
            </select>
          </div>
          <div class="form-row">
            <label>难度</label>
            <select v-model="state.form.difficulty" class="input">
              <option value="1">易</option><option value="2">中</option><option value="3">难</option>
            </select>
          </div>
        </div>
        <div class="form-row">
          <label>知识点标签 <span class="hint">顿号或空格分隔</span></label>
          <input v-model="state.form.tags" class="input" placeholder="索引、事务、B+树">
        </div>
        <div class="form-row">
          <label>满分答案 <span class="hint">当时的回答 + 事后复盘的标准答案，要点式记录</span></label>
          <textarea v-model="state.form.model_answer" class="input" rows="8" placeholder="1. 要点一&#10;2. 要点二&#10;- 细节补充"></textarea>
        </div>
        <p v-if="state.error" class="error">{{ state.error }}</p>
        <div class="answer-actions">
          <button class="btn primary" :disabled="!state.form.title || state.saving" @click="save">{{ state.saving ? '保存中…' : '保存' }}</button>
          <button class="btn ghost" @click="state.showForm = false">取消</button>
        </div>
      </div>
    </div>
  </div>
  `,
};

/* ---------- 设置 ---------- */
const SettingsView = {
  name: 'SettingsView',
  emits: ['saved'],
  setup(_, { emit }) {
    const state = reactive({
      base_url: '', api_key: '', model: '',
      enabled: false, masked: '', loading: true,
      saving: false, testing: false, test: null, saved: false,
    });
    async function load() {
      const s = await api('/settings/llm');
      state.base_url = s.base_url; state.model = s.model; state.enabled = s.enabled; state.masked = s.api_key_masked;
      state.loading = false;
    }
    async function save() {
      state.saving = true;
      try {
        await api('/settings/llm', { method: 'PUT', body: { base_url: state.base_url, api_key: state.api_key, model: state.model } });
        state.saved = true; setTimeout(() => state.saved = false, 2000);
        await load();
        emit('saved');  // 通知根组件立即刷新健康徽章，无需手动刷新页面
      } catch (e) { alert(e.message); }
      state.saving = false;
    }
    async function test() {
      state.testing = true; state.test = null;
      state.test = await api('/settings/llm/test', { method: 'POST' });
      state.testing = false;
    }
    onMounted(load);
    return { state, save, test };
  },
  template: `
  <div class="card" style="max-width:640px">
    <h3>LLM 配置（OpenAI 兼容接口）</h3>
    <div class="status-line">
      当前状态：
      <span class="badge" :class="state.enabled ? 'ok' : 'warn'">{{ state.enabled ? '已启用 · AI 出题/评分生效中' : '离线题库模式' }}</span>
      <span v-if="state.masked" class="hint">密钥 {{ state.masked }}</span>
    </div>
    <p class="hint" style="margin-bottom:16px">配置后系统会用 LLM 按岗位生成新题、现场生成满分答案、给你的回答打分点评；不配置也能用（纯内置题库 + 自查模式）。支持 DeepSeek / Kimi / 通义 / OpenAI 等任何 OpenAI 兼容服务。</p>
    <div v-if="!state.loading">
      <div class="form-row">
        <label>Base URL</label>
        <input v-model.trim="state.base_url" class="input" placeholder="https://api.deepseek.com/v1">
      </div>
      <div class="form-row">
        <label>API Key</label>
        <input v-model.trim="state.api_key" class="input" type="password" :placeholder="state.masked ? '已保存（留空则沿用 ' + state.masked + '）' : 'sk-...'">
      </div>
      <div class="form-row">
        <label>模型名</label>
        <input v-model.trim="state.model" class="input" placeholder="deepseek-chat / moonshot-v1-8k / qwen-plus / gpt-4o-mini">
      </div>
      <div class="answer-actions">
        <button class="btn primary" :disabled="state.saving" @click="save">{{ state.saved ? '✓ 已保存' : state.saving ? '保存中…' : '保存配置' }}</button>
        <button class="btn" :disabled="state.testing" @click="test">{{ state.testing ? '测试中…' : '测试连接' }}</button>
      </div>
      <div v-if="state.test" class="ai-comment" :style="{borderColor: state.test.ok ? '#bbf7d0' : '#fecaca', background: state.test.ok ? '#f0fdf4' : '#fef2f2'}">
        {{ state.test.ok ? '✅ ' : '❌ ' }}{{ state.test.message }}
      </div>
      <h3 style="margin-top:28px">说明</h3>
      <p class="hint" style="line-height:1.9">
        · 配置保存在 Redis，优先级高于 .env 文件<br>
        · 出题策略：优先从题库抽题（错题优先重现），题量不足时由 AI 补充新题入库<br>
        · 离线模式下面试只做「你的回答 vs 满分答案」对比，评分需自查<br>
        · 所有数据（题库/面试记录）在 MySQL，会话与错题队列在 Redis，均落外置盘
      </p>
    </div>
  </div>
  `,
};

/* ---------- 根组件 ---------- */
const App = {
  components: { InterviewView, SessionsView, ReviewView, BankView, SettingsView, MapView },
  setup() {
    const view = ref('home');
    const sessionId = ref(null);
    const tabs = [
      { key: 'home', label: '开始面试' },
      { key: 'map', label: '知识地图' },
      { key: 'sessions', label: '复盘' },
      { key: 'review', label: '错题本' },
      { key: 'bank', label: '题库' },
      { key: 'settings', label: '设置' },
    ];
    const health = reactive({ mysql: '', redis: '', llm: '' });
    const resumeSession = ref(null);

    // 首页表单
    const position = ref('');
    const count = ref(10);
    const categories = ref([]);
    const picked = ref([]);
    const starting = ref(false);
    const error = ref('');
    const llmEnabled = ref(false);
    const stats = reactive({});
    const chart = ref(null);
    let chartInst = null;

    function go(v) { view.value = v; }

    /* ---- Hash 路由：F5 恢复当前页面 + 浏览器前进后退 ---- */
    const VIEW_HASH = { home: '#/', sessions: '#/sessions', review: '#/review', bank: '#/bank', settings: '#/settings' };
    function syncHash() {
      const target = view.value === 'interview' && sessionId.value
        ? `#/interview/${sessionId.value}`
        : (VIEW_HASH[view.value] || '#/');
      if (location.hash !== target) location.hash = target;
    }
    function applyHash() {
      const h = location.hash || '#/';
      const m = h.match(/^#\/interview\/(\d+)$/);
      if (m) {
        sessionId.value = Number(m[1]);
        view.value = 'interview';
        return;
      }
      view.value = { '#/': 'home', '#/sessions': 'sessions', '#/review': 'review', '#/bank': 'bank', '#/settings': 'settings' }[h] || 'home';
      if (view.value !== 'interview') sessionId.value = null;
    }
    window.addEventListener('hashchange', applyHash);
    // 视图/session 变化同步到地址栏
    watch([view, sessionId], syncHash);
    const VIEW_TITLES = { home: '开始面试', interview: '面试中', sessions: '复盘', review: '错题本', bank: '题库', settings: '设置' };
    watch(view, (v) => {
      document.title = (VIEW_TITLES[v] ? VIEW_TITLES[v] + ' · ' : '') + '面试刷题系统';
      if (v === 'home') { loadStats(); loadHealth(); loadMeta(); checkResume(); }
    });
    function toggleCat(code) {
      const i = picked.value.indexOf(code);
      if (i >= 0) picked.value.splice(i, 1); else picked.value.push(code);
    }

    async function loadHealth() {
      try {
        const h = await api('/health');
        health.mysql = h.mysql === 'ok' ? 'ok' : 'down';
        health.redis = h.redis === 'ok' ? 'ok' : 'down';
        health.llm = h.llm === 'on' ? 'ok' : 'off';
        llmEnabled.value = h.llm === 'on';
      } catch (e) {
        health.mysql = health.redis = 'down';
      }
    }
    async function loadMeta() {
      try {
        const m = await api('/questions/meta');
        categories.value = m.categories;
      } catch (e) { /* 容器未就绪时忽略 */ }
    }
    async function loadStats() {
      try {
        const s = await api('/stats');
        Object.assign(stats, s);
        renderChart();
      } catch (e) { /* ignore */ }
    }
    function renderChart() {
      nextTick(() => {
        // v-if 切换会重建元素，不缓存实例，每次按当前元素取
        const el = document.querySelector('.chart');
        if (!el || !stats.categories || !stats.categories.length) return;
        const inst = echarts.getInstanceByDom(el) || echarts.init(el);
        inst.setOption({
          grid: { left: 8, right: 16, top: 10, bottom: 0, containLabel: true },
          xAxis: { type: 'value', max: 100, axisLabel: { color: '#9aa3b8' }, splitLine: { lineStyle: { color: '#eef0f6' } } },
          yAxis: {
            type: 'category',
            data: stats.categories.map(c => c.name).reverse(),
            axisLabel: { color: '#5b6478' },
            axisLine: { show: false }, axisTick: { show: false },
          },
          series: [{
            type: 'bar',
            data: stats.categories.map(c => c.avg_score).reverse(),
            barWidth: 14,
            itemStyle: { borderRadius: 8, color: '#4f5df0' },
            label: { show: true, position: 'right', color: '#5b6478' },
          }],
          tooltip: { trigger: 'axis' },
        });
      });
    }    async function checkResume() {
      try {
        const list = await api('/interviews?limit=5');
        resumeSession.value = list.find(s => s.status === 'in_progress' && s.mode !== 'REVIEW') || null;
      } catch (e) { /* ignore */ }
    }

    async function startInterview() {
      starting.value = true; error.value = '';
      try {
        const r = await api('/interviews', {
          method: 'POST',
          body: { position: position.value, count: count.value, categories: picked.value.length ? picked.value : null },
        });
        sessionId.value = r.session_id;
        view.value = 'interview';
        resumeSession.value = null;
      } catch (e) { error.value = e.message; }
      starting.value = false;
    }

    /* 🔥 高频八股速刷：一键按类别开刷（与岗位面试共享全部机制） */
    const QUICK_PRESETS = {
      mix: { position: '高频八股专项', count: 12, categories: ['NETWORK', 'MYSQL', 'REDIS', 'JVM', 'OS', 'CONCURRENT'] },
      MYSQL: { position: 'MySQL 专项', count: 10, categories: ['MYSQL'] },
      REDIS: { position: 'Redis 专项', count: 10, categories: ['REDIS'] },
      NETWORK: { position: '网络专项', count: 10, categories: ['NETWORK'] },
      JVM: { position: 'JVM 专项', count: 10, categories: ['JVM'] },
      PYTHON: { position: 'Python 专项', count: 8, categories: ['PYTHON'] },
      OS: { position: '操作系统专项', count: 10, categories: ['OS'] },
      CONCURRENT: { position: '并发专项', count: 10, categories: ['CONCURRENT'] },
    };
    async function quickDrill(key) {
      const preset = QUICK_PRESETS[key];
      if (!preset) return;
      starting.value = true; error.value = '';
      try {
        const r = await api('/interviews', {
          method: 'POST',
          body: { position: preset.position, count: preset.count, categories: preset.categories },
        });
        sessionId.value = r.session_id;
        view.value = 'interview';
        resumeSession.value = null;
      } catch (e) { error.value = e.message; }
      starting.value = false;
    }
    function resumeInterview() { sessionId.value = resumeSession.value.id; resumeSession.value = null; view.value = 'interview'; }
    async function abandonResume() {
      if (!confirm('放弃当前进行中的面试？')) return;
      await api(`/interviews/${resumeSession.value.id}/abandon`, { method: 'POST' });
      resumeSession.value = null;
    }
    function onHome() { view.value = 'home'; sessionId.value = null; resumeSession.value = null; }
    function onInterviewFinished() { loadStats(); checkResume(); loadHealth(); }

    onMounted(() => {
      applyHash();          // 按 URL hash 恢复页面（如刷新前在面试页）
      loadHealth(); loadMeta(); loadStats(); checkResume();
      setInterval(loadHealth, 30000);  // 健康徽章自动跟随服务状态
    });

    return {
      view, tabs, health, go, sessionId,
      position, count, categories, picked, toggleCat, starting, error, llmEnabled,
      startInterview, quickDrill, stats, chart, loadHealth,
      resumeSession, resumeInterview, abandonResume, onHome, onInterviewFinished,
    };
  },
};

/* 根模板直接使用 index.html 中 #app 的 DOM 结构（vue.global 自带编译器） */
createApp(App).mount('#app');

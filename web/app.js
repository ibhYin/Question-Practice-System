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
  RESUME: '简历深挖',
};
/* 八股卡背诵状态元数据（八股文库 / 行动面板 / 相关八股条共用） */
const CARD_STATUS_META = {
  new: { label: '未学', cls: 'gray' },
  learning: { label: '待巩固', cls: 'warn' },
  mastered: { label: '已背熟', cls: 'ok' },
};
const DIFF_LABEL = { 1: '易', 2: '中', 3: '难' };
const DIFF_COLOR = { 1: 'ok', 2: 'warn', 3: 'bad' };

function fmtTime(iso) {
  if (!iso) return '-';
  const d = new Date(iso);
  const p = (n) => String(n).padStart(2, '0');
  return `${d.getMonth() + 1}-${p(d.getDate())} ${p(d.getHours())}:${p(d.getMinutes())}`;
}
/* 满分答案/文档轻量渲染 v2：结构化 Markdown（标题/列表/表格/代码块/加粗）+ Mermaid 图表 */
function escHtml(text) {
  return text.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
}
function inlineMd(text) {
  return escHtml(text)
    .replace(/\*\*(.+?)\*\*/g, '<b>$1</b>')
    .replace(/`([^`\n]+?)`/g, '<code>$1</code>');
}
function renderAnswer(text) {
  if (!text) return '';
  // 1. 拆出围栏代码块（```mermaid ... ``` 特殊处理，其余为代码块）
  const parts = String(text).split(/```/);
  let html = '';
  for (let i = 0; i < parts.length; i++) {
    const part = parts[i];
    if (i % 2 === 1) {
      // 围栏块：首行是语言名
      const nl = part.indexOf('\n');
      const lang = (nl === -1 ? part : part.slice(0, nl)).trim().toLowerCase();
      const body = nl === -1 ? '' : part.slice(nl + 1).replace(/\n$/, '');
      if (lang === 'mermaid') {
        html += `<div class="mermaid">${escHtml(body)}</div>`;
      } else {
        html += `<pre class="md-pre">${escHtml(body)}</pre>`;
      }
      continue;
    }
    // 2. 非代码段：逐行结构化
    const lines = part.split('\n');
    let out = '', listBuf = null, tableBuf = null, paraBuf = [];
    const flushPara = () => {
      if (paraBuf.length) { out += `<p>${inlineMd(paraBuf.join(' '))}</p>`; paraBuf = []; }
    };
    const flushList = () => { if (listBuf) { out += `<${listBuf.tag}>` + listBuf.items.map(x => `<li>${inlineMd(x)}</li>`).join('') + `</${listBuf.tag}>`; listBuf = null; } };
    const flushTable = () => {
      if (!tableBuf) return;
      const rows = tableBuf;
      if (rows.length >= 2) {
        const head = rows[0];
        const body = rows.slice(2);  // 跳过 |---|---| 分隔行
        out += '<table class="md-table"><thead><tr>' + head.map(c => `<th>${inlineMd(c)}</th>`).join('') + '</tr></thead><tbody>'
          + body.map(r => '<tr>' + head.map((_, i) => `<td>${inlineMd(r[i] || '')}</td>`).join('') + '</tr>').join('') + '</tbody></table>';
      } else if (rows.length === 1) {
        out += rows[0].map(c => inlineMd(c)).join(' ');
      }
      tableBuf = null;
    };
    for (const raw of lines) {
      const line = raw.trimEnd();
      const t = line.trim();
      // 表格行
      if (/^\|.*\|/.test(t)) {
        flushPara(); flushList();
        const cells = t.replace(/^\||\|$/g, '').split('|').map(c => c.trim());
        const isSep = cells.every(c => /^:?-{2,}:?$/.test(c));
        if (tableBuf && isSep) continue;  // 分隔行
        tableBuf = tableBuf || [];
        tableBuf.push(cells);
        continue;
      }
      flushTable();
      // 标题
      const h = t.match(/^(#{1,4})\s+(.*)/);
      if (h) { flushPara(); flushList(); out += `<h4 class="md-h${h[1].length}">${inlineMd(h[2])}</h4>`; continue; }
      // 无序列表
      const ul = t.match(/^[-*]\s+(.*)/);
      if (ul) { flushPara(); if (!listBuf || listBuf.tag !== 'ul') { flushList(); listBuf = { tag: 'ul', items: [] }; } listBuf.items.push(ul[1]); continue; }
      // 有序列表
      const ol = t.match(/^\d+[.、)]\s+(.*)/);
      if (ol) { flushPara(); if (!listBuf || listBuf.tag !== 'ol') { flushList(); listBuf = { tag: 'ol', items: [] }; } listBuf.items.push(ol[1]); continue; }
      // 空行
      if (!t) { flushPara(); flushList(); continue; }
      // 引用
      const quote = t.match(/^>\s?(.*)/);
      if (quote) { flushPara(); flushList(); out += `<blockquote class="md-quote">${inlineMd(quote[1])}</blockquote>`; continue; }
      // 普通文本（连续行为一段）
      paraBuf.push(t);
    }
    flushPara(); flushList(); flushTable();
    html += out;
  }
  return html;
}
/* v-html 更新后激活页面内的 mermaid 图（未加载/失败时降级为代码块样式） */
function enhanceDiagrams() {
  if (typeof mermaid === 'undefined') return;
  const nodes = document.querySelectorAll('.main .mermaid');
  if (!nodes.length) return;
  try {
    mermaid.initialize({ startOnLoad: false, theme: 'neutral', securityLevel: 'strict' });
    mermaid.run({ nodes: [...nodes] }).catch(() => {
      nodes.forEach(n => n.classList.add('mermaid-error'));
    });
  } catch (e) { /* 降级：保持源码展示 */ }
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
      relatedCards: [],      // 本题关联八股卡（知识点速记）
      cardDetail: null,      // 点开的八股卡
      packState: {},         // cardId -> {loading, content} 知识包懒生成
      sessionQs: [],         // 本场题目导航列表
      answeredCount: 0,
      draftSaved: false,     // 草稿保存微提示
      chats: {},             // qid -> [{role, content}] AI 追问历史（服务端持久化）
      chatInput: '',
      chatSending: false,
      chatOpen: true,        // 追问面板展开状态
      chatLoaded: {},        // qid -> true（已从服务端加载过）
      finishing: false,      // 总评生成中（等待评分收口与总结）
      pendingScores: 0,      // 总评页提示：仍在后台评分的题数
      framework: null,       // 本题知识框架 {qid, framework, cached}
      fwLoading: false,
      fwOpen: true,          // 知识框架展开状态
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
      try {
        localStorage.setItem(draftKey(), state.answer);
        state.draftSaved = true;
        setTimeout(() => { state.draftSaved = false; }, 1500);
      } catch (e) { /* 忽略 */ }
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

    /* 知识链路 + 相关八股：结果页加载本题的延伸材料 */
    async function loadKnowledge(qid) {
      state.knowledge = [];
      state.relatedCards = [];
      try {
        const k = await api(`/questions/knowledge/${qid}`);
        state.knowledge = k.related;
      } catch (e) { /* 关联加载失败不干扰答题 */ }
      try {
        const c = await api(`/questions/${qid}/cards`);
        state.relatedCards = c.cards;
      } catch (e) { /* 忽略 */ }
    }

    /* 题号导航：拉取本场题目列表 + 切换题目 */
    async function loadSessionQs() {
      try {
        const d = await api(`/interviews/${props.sessionId}/questions`);
        state.sessionQs = d.items;
        state.answeredCount = d.answered_count;
      } catch (e) { /* 忽略 */ }
    }
    // 可切换的范围：已答题 + 顺位下一题（越题防护规则的前端镜像）
    const unlockedIds = computed(() => {
      const n = state.answeredCount || 0;
      return new Set(state.sessionQs.filter(i => i.seq <= n + 1).map(i => i.id));
    });
    // 结果视图的题目 meta（标题/分类/难度/标签），提交与回看共用
    const resultQ = computed(() => (state.result ? state.sessionQs.find(i => i.id === state.result.question_id) || null : null));
    async function gotoQuestion(qid) {
      if (!unlockedIds.value.has(qid) || state.submitting) return;
      saveDraft();               // 切走前保存当前草稿（按题隔离，互不影响）
      if (state.pollTimer) { clearInterval(state.pollTimer); state.pollTimer = null; }
      stopTimer();
      const item = state.sessionQs.find(i => i.id === qid);
      if (!item) return;
      if (item.answered) {
        // 已答题 → 结果视图（从导航数据重建，含分数与对比）
        const d = await api(`/interviews/${props.sessionId}`);
        const mine = d.answers.find(a => a.question_id === qid);
        if (!mine) return;
        state.result = {
          question_id: qid, seq: mine.seq,
          score: mine.score, ai_comment: mine.ai_comment,
          user_answer: mine.user_answer, model_answer: mine.model_answer,
          scoring: false,
          next_question: null, finished: false, revisiting: true,
          title: item.title, related: state.knowledge, relatedCards: state.relatedCards,
        };
        state.question = null;
        state.phase = 'result';
        loadKnowledge(qid);
        loadChat(qid);
      } else {
        // 可答未答题 → 答题视图（恢复草稿 + 上次作答提示）
        const p = await api(`/interviews/${props.sessionId}/progress`);
        if (p.question && p.question.id === qid) {
          state.question = p.question;
          state.answer = ''; state.result = null; state.addedReview = false;
          state.phase = 'answering';
          restoreDraft();
          startTimer();
        }
      }
      nextTick(enhanceDiagrams);
    }

    /* AI 追问（结果视图内，持久化到服务端的多轮对话） */
    function chatList() {
      const key = state.result ? state.result.question_id : 0;
      if (!state.chats[key]) state.chats[key] = [];
      return state.chats[key];
    }
    async function loadChat(qid) {
      if (state.chatLoaded[qid]) return;
      try {
        const d = await api(`/interviews/${props.sessionId}/answers/${qid}/chat`);
        state.chats[qid] = d.messages;
        state.chatLoaded[qid] = true;
      } catch (e) { /* 忽略 */ }
    }
    async function sendChat() {
      const q = state.chatInput.trim();
      if (!q || state.chatSending || !state.result) return;
      if (!state.llmEnabled) { state.error = 'AI 追问需要先在「设置」中配置 LLM'; return; }
      state.chatSending = true; state.error = '';
      const qid = state.result.question_id;
      const history = chatList();
      history.push({ role: 'user', content: q });
      state.chatInput = '';
      try {
        const r = await api(`/interviews/${props.sessionId}/answers/${qid}/chat`, {
          method: 'POST',
          body: { content: q },
        });
        history.push({ role: 'assistant', content: r.reply });
      } catch (e) {
        history.push({ role: 'assistant', content: `⚠️ ${e.message}` });
      }
      state.chatSending = false;
      nextTick(enhanceDiagrams);
    }

    /* 本题知识框架（懒生成，缓存于题库） */
    async function loadFramework() {
      if (!state.result) return;
      const qid = state.result.question_id;
      state.fwLoading = true;
      try {
        const r = await api(`/questions/${qid}/framework`, { method: 'POST', body: {} });
        state.framework = { qid, framework: r.framework, cached: r.cached };
      } catch (e) { state.error = e.message; }
      state.fwLoading = false;
    }
    function frameworkVisible() {
      return state.framework && state.result && state.framework.qid === state.result.question_id;
    }
    function openRelated(k) {
      state.relatedDetail = k;   // k 含 title/category_name/model_answer
    }
    function openCard(c) {
      state.cardDetail = { ...c };
    }
    async function markCard(cardId, status) {
      try {
        await api(`/study/cards/${cardId}/status`, { method: 'POST', body: { status } });
        if (state.cardDetail && state.cardDetail.id === cardId) state.cardDetail.status = status;
        state.relatedCards = state.relatedCards.map(c => c.id === cardId ? { ...c, status } : c);
        loadOverviewForCards();
      } catch (e) { state.error = e.message; }
    }
    async function loadPackForCard(card) {
      state.packState = { ...state.packState, [card.id]: { loading: true, content: null } };
      try {
        const p = await api('/analysis/knowledge-pack', { method: 'POST', body: { tag: card.title } });
        state.packState = { ...state.packState, [card.id]: { loading: false, content: p.content } };
      } catch (e) {
        state.packState = { ...state.packState, [card.id]: { loading: false, content: null, error: e.message } };
      }
    }
    function loadOverviewForCards() { /* 占位：标记变化会由八股文库页激活时刷新 */ }

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
        loadChat(r.question_id);      // 追问历史（服务端持久化）
        loadSessionQs();              // 刷新题号导航（答题状态变化）
        nextTick(enhanceDiagrams);
      } catch (e) { state.error = e.message; }
      state.submitting = false;
    }

    async function nextQuestion() {
      // 重访历史题的结果视图：返回当前待答题
      if (state.result && state.result.revisiting) {
        const cur = state.sessionQs.find(i => i.seq === state.answeredCount + 1);
        if (cur) return gotoQuestion(cur.id);
      }
      if (state.result.finished) return finish();
      state.question = state.result.next_question;
      state.answer = '';
      state.result = null;
      state.addedReview = false;
      state.phase = 'answering';
      restoreDraft();
      startTimer();
    }

    /* 按理解重新作答：保留上一轮记录（后端新增一行），回到答题视图对照重写 */
    function reanswer() {
      if (!state.result || !resultQ.value) return;
      stopTimer();
      if (state.pollTimer) { clearInterval(state.pollTimer); state.pollTimer = null; }
      // 上一轮作答作为「上次作答」提示展示（分数/回答/点评），辅助对照改进
      const r = state.result;
      const pa = (r.score != null || (r.user_answer || '').trim()) ? {
        score: r.score,
        user_answer: r.user_answer,
        ai_comment: r.ai_comment,
      } : null;
      const meta = resultQ.value;
      state.question = {
        id: r.question_id, seq: r.seq,
        title: meta.title, category: meta.category,
        difficulty: meta.difficulty, tags: meta.tags || [],
        prev_attempt: pa,
      };
      state.answer = '';
      state.result = null;
      state.addedReview = false;
      state.phase = 'answering';
      startTimer();
    }

    async function addToReview() {
      try {
        await api(`/review/${state.result.question_id}/add`, { method: 'POST' });
        state.addedReview = true;
      } catch (e) { state.error = e.message; }
    }

    async function finish() {
      state.finishing = true; state.error = '';
      try {
        const fr = await api(`/interviews/${props.sessionId}/finish`, { method: 'POST' });
        state.pendingScores = fr.pending_scores || 0;
      } catch (e) { /* 忽略，接着拉详情 */ }
      const detail = await api(`/interviews/${props.sessionId}`);
      state.summary = detail;
      state.phase = 'summary';
      state.finishing = false;
      emit('finished');
    }

    async function abandon() {
      if (!confirm('确定放弃本场面试？已答题目仍会保存在复盘中。')) return;
      await api(`/interviews/${props.sessionId}/abandon`, { method: 'POST' });
      emit('abandoned');
    }

    onMounted(() => { loadProgress(); loadSessionQs(); });
    onUnmounted(() => { stopTimer(); if (state.pollTimer) clearInterval(state.pollTimer); });

    return { state, submit, nextQuestion, reanswer, finish, abandon, addToReview, saveDraft, fmtElapsed, renderAnswer, loadKnowledge, loadChat, openRelated, openCard, markCard, loadPackForCard, gotoQuestion, unlockedIds, resultQ, sendChat, chatList, loadFramework, frameworkVisible, CARD_STATUS_META, CATEGORY_NAMES, DIFF_LABEL, DIFF_COLOR, scoreClass };
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
      <!-- 题号导航：点击切换题目（锁定题置灰） -->
      <div class="q-nav">
        <button v-for="item in state.sessionQs" :key="item.id"
                class="q-nav-btn"
                :class="{
                  on: state.question && state.question.id === item.id,
                  done: item.answered,
                  locked: !unlockedIds.has(item.id),
                }"
                :disabled="!unlockedIds.has(item.id) || state.submitting"
                :title="item.title"
                @click="gotoQuestion(item.id)">{{ item.seq }}</button>
      </div>
      <div class="card q-card">
        <div class="q-meta">
          <span class="badge">{{ CATEGORY_NAMES[state.question.category] || state.question.category }}</span>
          <span class="badge" :class="DIFF_COLOR[state.question.difficulty]">难度·{{ DIFF_LABEL[state.question.difficulty] }}</span>
          <span v-for="t in state.question.tags" :key="t" class="badge gray">{{ t }}</span>
        </div>
        <div class="q-title">{{ state.question.title }}</div>
        <div v-if="state.question.prev_attempt" class="prev-attempt">
          <div class="pa-head">⚠️ 上次作答 <b>{{ state.question.prev_attempt.score != null ? state.question.prev_attempt.score + ' 分' : '未评分' }}</b></div>
          <div class="pa-body">{{ state.question.prev_attempt.user_answer }}</div>
          <div v-if="state.question.prev_attempt.ai_comment" class="hint">点评：{{ state.question.prev_attempt.ai_comment }}</div>
        </div>
      </div>
      <div class="card">
        <h3>你的回答 <span class="hint">草稿自动保存 <span v-if="state.draftSaved" class="badge ok" style="margin-left:4px">✓ 已保存</span> · Ctrl+Enter 提交</span></h3>
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
      <!-- 题干卡：提交后保留题目可见（与答题页同款） -->
      <div class="card q-card" v-if="resultQ">
        <div class="q-meta">
          <span class="badge">{{ CATEGORY_NAMES[resultQ.category] || resultQ.category }}</span>
          <span class="badge" :class="DIFF_COLOR[resultQ.difficulty]">难度·{{ DIFF_LABEL[resultQ.difficulty] }}</span>
          <span v-for="t in (resultQ.tags || [])" :key="t" class="badge gray">{{ t }}</span>
        </div>
        <div class="q-title">{{ resultQ.title }}</div>
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
        <div v-if="state.relatedCards && state.relatedCards.length" class="know-strip">
          <span class="hint" style="flex-shrink:0; align-self:center">📚 相关八股</span>
          <span v-for="c in state.relatedCards" :key="c.id" class="chip small" @click="openCard(c)">
            {{ CARD_STATUS_META[c.status].label }} · {{ c.title }}</span>
        </div>
        <div class="answer-actions">
          <button v-if="state.result.revisiting" class="btn primary" @click="nextQuestion">← 回到当前题目</button>
          <template v-else>
            <button v-if="state.result.finished && !state.finishing" class="btn primary" @click="nextQuestion">查看本场总评 →</button>
            <button v-else-if="state.result.finished && state.finishing" class="btn primary" disabled>正在生成总评…（收口评分与总结，约需 30 秒）</button>
            <button v-else class="btn primary" @click="nextQuestion">下一题 →</button>
            <button v-if="state.result.score == null && !state.addedReview" class="btn" @click="addToReview">＋ 这题没掌握，加入复习</button>
            <span v-if="state.addedReview" class="badge ok" style="align-self:center">已加入错题本，明天复习</span>
          </template>
          <button v-if="!state.result.scoring && !state.finishing" class="btn ghost"
                  @click="reanswer" title="保留本次记录，新增一次作答尝试；总分按每题最新一次评分计算">✍️ 按理解重新作答</button>
        </div>

        <!-- 🗺 本题知识框架（懒生成，缓存于题库） -->
        <div class="fw-panel">
          <div class="fw-head" @click="state.fwOpen = !state.fwOpen">
            🗺 本题知识框架
            <span class="hint" style="margin-left:8px">前置知识 · 答题骨架 · 易错与追问方向 · 延伸关联</span>
            <span style="margin-left:auto">{{ state.fwOpen ? '▾' : '▸' }}</span>
          </div>
          <div v-show="state.fwOpen" class="fw-body">
            <div v-if="frameworkVisible()">
              <div class="doc-body" v-html="renderAnswer(state.framework.framework)"></div>
            </div>
            <div v-else style="padding:8px 0">
              <button class="btn" :disabled="state.fwLoading" @click="loadFramework">
                {{ state.fwLoading ? '知识框架生成中…（约 1-2 分钟）' : '🗺 生成本题知识框架' }}</button>
              <span v-if="state.framework && state.framework.qid === (state.result && state.result.question_id) && state.framework.error" class="error" style="margin-left:10px">{{ state.framework.error }}</span>
            </div>
          </div>
        </div>

        <!-- 💬 AI 追问：提交/跳过后直接向 AI 提问（记录持久化，刷新不丢） -->
        <div class="chat-panel">
          <div class="chat-head" @click="state.chatOpen = !state.chatOpen">
            💬 追问 AI（针对本题的疑问，如"为什么这里用间隙锁？"）
            <span class="hint" style="margin-left:8px">记录已保存，随时回看</span>
            <span style="margin-left:auto">{{ state.chatOpen ? '▾' : '▸' }}</span>
          </div>
          <div v-show="state.chatOpen" class="chat-body">
            <div v-if="!state.llmEnabled" class="hint" style="padding:8px 0">AI 追问需要先在「设置」中配置 LLM</div>
            <template v-else>
              <div v-for="(m, i) in chatList()" :key="i" class="chat-msg" :class="m.role">
                <div v-if="m.role === 'assistant'" class="box model chat-bubble" v-html="renderAnswer(m.content)"></div>
                <div v-else class="box you chat-bubble">{{ m.content }}</div>
              </div>
              <div v-if="state.chatSending" class="hint" style="padding:4px 0">AI 思考中…</div>
              <div class="chat-input-row">
                <input v-model="state.chatInput" class="input" style="flex:1"
                       placeholder="针对本题追问，如：这个知识点还会怎么考？"
                       @keyup.enter="sendChat" :disabled="state.chatSending">
                <button class="btn primary" :disabled="state.chatSending || !state.chatInput.trim()" @click="sendChat">发送</button>
              </div>
            </template>
          </div>
        </div>
      </div>
    </template>

    <!-- 本场总结 -->
    <template v-else-if="state.phase === 'summary' && state.summary">
      <div class="card">
        <div class="score-row">
          <div>
            <h3 style="font-size:18px">面试结束 · {{ state.summary.position }}</h3>
            <div v-if="state.pendingScores > 0" class="prev-attempt" style="margin-top:8px">
              ⏳ {{ state.pendingScores }} 题评分仍在后台进行——稍后到「复盘」里刷新即可看到分数，不影响本页总评。
            </div>
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

    <!-- 相关八股卡弹窗：正文 + 关键点 + 背诵标记 + 知识包 -->
    <div v-if="state.cardDetail" class="modal-mask" @click.self="state.cardDetail = null">
      <div class="modal">
        <h3>{{ state.cardDetail.title }}</h3>
        <div class="q-meta" style="margin-bottom:12px">
          <span class="badge">{{ state.cardDetail.category_name }}</span>
          <span class="badge" :class="CARD_STATUS_META[state.cardDetail.status].cls">{{ CARD_STATUS_META[state.cardDetail.status].label }}</span>
        </div>
        <div class="box you" style="max-height:none; margin-bottom:12px">{{ state.cardDetail.content }}</div>
        <div v-if="state.cardDetail.points && state.cardDetail.points.length" class="know-strip" style="border:none; padding:0; margin-bottom:14px">
          <span class="hint" style="flex-shrink:0; align-self:center">⚡ 关键点</span>
          <span v-for="(p, i) in state.cardDetail.points" :key="i" class="badge gray">{{ p }}</span>
        </div>
        <div class="know-strip" style="border:none; padding:0; margin-bottom:14px">
          <button class="btn small danger" :disabled="state.cardDetail.status === 'new'" @click="markCard(state.cardDetail.id, 'new')">未掌握</button>
          <button class="btn small" :disabled="state.cardDetail.status === 'learning'" @click="markCard(state.cardDetail.id, 'learning')">待巩固</button>
          <button class="btn small primary" :disabled="state.cardDetail.status === 'mastered'" @click="markCard(state.cardDetail.id, 'mastered')">✓ 已背熟</button>
          <button class="btn small ghost" :disabled="(state.packState[state.cardDetail.id] && (state.packState[state.cardDetail.id].loading || state.packState[state.cardDetail.id].content))" @click="loadPackForCard(state.cardDetail)">
            {{ state.packState[state.cardDetail.id] ? (state.packState[state.cardDetail.id].loading ? '知识包生成中…（1-2分钟）' : (state.packState[state.cardDetail.id].content ? '✓ 知识包已展开' : '重试生成知识包')) : '📖 生成系统知识包（更全面）' }}</button>
        </div>
        <div v-if="state.packState[state.cardDetail.id] && state.packState[state.cardDetail.id].content" class="pack-box">
          <h4 style="font-size:13px; color:#5b6478; margin-bottom:8px">📖 系统知识包（完整原理 · 变体问法 · 识别信号）</h4>
          <div class="doc-body" style="max-height:320px; overflow:auto" v-html="renderAnswer(state.packState[state.cardDetail.id].content)"></div>
        </div>
        <div class="answer-actions">
          <button class="btn" @click="state.cardDetail = null">关闭</button>
        </div>
      </div>
    </div>
  </div>
  `,
};

/* ---------- 知识地图 ---------- */
const MapView = {
  name: 'MapView',
  emits: ['start-session'],
  setup(_, { emit }) {
    const state = reactive({
      loading: true, error: '', category: 'MYSQL',
      mode: 'tag',            // tag 知识点视角 | question 题目视角
      stats: { nodes: 0, links: 0, linked: 0 },
      detail: null,           // 题目模式：点节点弹题详情
      panel: null,            // 知识点模式：点节点弹行动面板
      diagnosing: false, packLoading: false, variantStarting: false,
    });
    let chartInst = null;
    const chartEl = ref(null);

    const CAT_COLORS = {
      MYSQL: '#4f5df0', REDIS: '#dc2626', JAVA: '#b45309', JVM: '#7c3aed', CONCURRENT: '#0891b2',
      SPRING: '#16a34a', NETWORK: '#2563eb', SCENARIO: '#9333ea', AI_APP: '#db2777', AGENT: '#ea580c',
      FULLSTACK: '#0d9488', OS: '#475569', DISTRIBUTED: '#a16207', ALGO: '#be185d', PYTHON: '#ca8a04',
    };
    const STATUS_COLOR = { weak: '#dc2626', encountered: '#2563eb', untouched: '#94a3b8' };

    async function load() {
      state.loading = true; state.error = '';
      state.detail = null; state.panel = null;
      try {
        const d = state.mode === 'tag'
          ? await api(`/analysis/knowledge-graph?category=${state.category}`)
          : await api(`/questions/knowledge/map?category=${state.category}`);
        const flat = d.links.map(l => ({ source: l.source, target: l.target }));
        state.stats = {
          nodes: d.nodes.length, links: d.links.length,
          linked: new Set(flat.flatMap(l => [l.source, l.target])).size,
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
      const isTag = state.mode === 'tag';
      const nodes = d.nodes.map(n => {
        let color, size, tip;
        if (isTag) {
          color = STATUS_COLOR[n.status] || '#94a3b8';
          size = 16 + (n.attempts || 0) * 4 + Math.min(n.question_count || 0, 8) * 1.5;
          const scoreTxt = n.avg_score != null ? `均分 ${n.avg_score}` : '未作答';
          tip = `${n.name}<br/>状态：${{ weak: '🔴 薄弱', encountered: '🔵 答过', untouched: '⚪ 未触达' }[n.status]}<br/>${scoreTxt} · 出现于 ${n.question_count} 题`;
        } else {
          const wrong = n.wrong_count || 0;
          color = wrong > 0 ? '#dc2626' : (CAT_COLORS[n.category] || '#64748b');
          size = 14 + Math.min(wrong, 5) * 5 + Math.min(degree[n.id] || 0, 6) * 1.5;
          tip = `${n.category}<br/>${n.name}<br/>答错 ${wrong} 次`;
        }
        return { id: String(n.id), name: n.name, fullName: n.name, value: n.id, category: n.category, categoryName: n.category, wrong_count: n.wrong_count || 0, status: n.status, attempts: n.attempts, avg_score: n.avg_score, itemStyle: { color }, symbolSize: size, tooltipText: tip };
      });
      chartInst.setOption({
        tooltip: { formatter: (p) => p.dataType === 'node' ? (p.data.tooltipText || '') : '' },
        series: [{
          type: 'graph', layout: 'force', roam: true, draggable: true,
          force: { repulsion: isTag ? 110 : 130, edgeLength: 55, gravity: 0.1 },
          label: { show: true, fontSize: isTag ? 11 : 10, color: '#5b6478' },
          itemStyle: { borderColor: '#fff', borderWidth: 1 },
          lineStyle: { color: '#c3cad9', width: 1, curveness: 0.1, opacity: 0.6 },
          emphasis: { focus: 'adjacency', lineStyle: { width: 2.5, color: '#4f5df0' } },
          data: nodes,
          links: d.links.map(l => ({ source: String(l.source), target: String(l.target) })),
        }],
      }, true);
      chartInst.off('click');
      chartInst.on('click', async (p) => {
        if (p.dataType !== 'node') return;
        if (state.mode === 'tag') {
          state.panel = { tag: p.data.fullName, loading: true };
          try {
            const detail = await api(`/analysis/tags/${encodeURIComponent(p.data.fullName)}/detail`);
            state.panel = { ...detail, loading: false };
          } catch (e) { state.panel = { tag: p.data.fullName, loading: false, error: e.message }; }
        } else {
          try {
            const k = await api(`/questions/knowledge/${p.data.value}`);
            const node = d.nodes.find(n => n.id === p.data.value);
            state.detail = {
              id: p.data.value, title: node ? node.name : p.data.name,
              category: node ? node.category : '', wrong_count: node ? node.wrong_count : 0,
              related: k.related, category_name: k.category_name,
            };
          } catch (e) { state.error = e.message; }
        }
      });
    }

    /* 知识点行动面板的动作 */
    async function runDiagnose() {
      if (!state.panel) return;
      state.diagnosing = true;
      try {
        const d = await api('/analysis/diagnose', { method: 'POST', body: { tag: state.panel.tag } });
        state.panel = { ...state.panel, diagnosis: d };
      } catch (e) { state.error = e.message; }
      state.diagnosing = false;
    }
    async function loadPack() {
      if (!state.panel) return;
      state.packLoading = true;
      try {
        const p = await api('/analysis/knowledge-pack', { method: 'POST', body: { tag: state.panel.tag } });
        state.panel = { ...state.panel, knowledge_pack: { content: p.content }, variant_questions: p.variant_questions || [] };
        nextTick(enhanceDiagrams);
      } catch (e) { state.error = e.message; }
      state.packLoading = false;
    }
    async function startVariants() {
      if (!state.panel) return;
      state.variantStarting = true;
      try {
        const r = await api('/analysis/variant-session', { method: 'POST', body: { tag: state.panel.tag, count: 4 } });
        state.panel = null;
        emit('start-session', r.session_id);
      } catch (e) { state.error = e.message; }
      state.variantStarting = false;
    }
    async function markCard(cardId, status) {
      try {
        await api(`/study/cards/${cardId}/status`, { method: 'POST', body: { status } });
        if (state.panel) {
          state.panel = { ...state.panel, cards: state.panel.cards.map(c => c.id === cardId ? { ...c, status } : c) };
        }
      } catch (e) { state.error = e.message; }
    }
    function closeDetail() { state.detail = null; }
    function closePanel() { state.panel = null; }
    function setMode(m) { state.mode = m; load(); }
    function pick(c) { state.category = c; load(); }
    onMounted(load);
    onActivated(load);
    onUnmounted(() => { if (chartInst) { chartInst.dispose(); chartInst = null; } });
    return { state, chartEl, pick, closeDetail, closePanel, setMode, runDiagnose, loadPack, startVariants, markCard, renderAnswer, CARD_STATUS_META, CATEGORY_NAMES };
  },
  template: `
  <div>
    <div class="card" style="padding:14px 18px; margin-bottom:14px; display:flex; gap:10px; flex-wrap:wrap; align-items:center">
      <b style="font-size:14px">知识地图</b>
      <div class="chips" style="gap:6px">
        <button class="chip" :class="{on: state.mode === 'tag'}" @click="setMode('tag')">🧠 知识点视角</button>
        <button class="chip" :class="{on: state.mode === 'question'}" @click="setMode('question')">📋 题目视角</button>
      </div>
      <select v-model="state.category" class="input" style="width:auto; min-width:130px" @change="pick(state.category)">
        <option v-for="(name, code) in CATEGORY_NAMES" :key="code" :value="code">{{ name }}</option>
      </select>
      <span class="hint">{{ state.stats.nodes }} 个{{ state.mode === 'tag' ? '知识点' : '考点' }} · {{ state.stats.links }} 条关联</span>
      <span v-if="state.mode === 'tag'" class="hint" style="margin-left:auto">🔴 薄弱 · 🔵 答过 · ⚪ 未触达 · 点节点进入行动面板</span>
      <span v-else class="hint" style="margin-left:auto">🔴 红点 = 答错过的题</span>
    </div>
    <div class="card" style="padding:0; height:600px; position:relative">
      <div v-if="state.loading" style="position:absolute; inset:0; display:flex; align-items:center; justify-content:center">加载中…</div>
      <div v-show="!state.loading" ref="chartEl" style="width:100%; height:100%"></div>
    </div>

    <!-- 题目模式：题详情弹窗 -->
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
        <div class="answer-full" v-html="renderAnswer('')"></div>
        <div class="answer-actions"><button class="btn" @click="closeDetail">关闭</button></div>
      </div>
    </div>

    <!-- 知识点模式：行动面板 -->
    <div v-if="state.panel" class="modal-mask" @click.self="closePanel">
      <div class="modal">
        <template v-if="state.panel.loading">
          <h3>{{ state.panel.tag }}</h3><p class="hint">加载中…</p>
        </template>
        <template v-else>
          <h3>🧠 {{ state.panel.tag }}</h3>
          <div class="q-meta" style="margin-bottom:14px">
            <span class="badge" :class="{bad: state.panel.weak, ok: !state.panel.weak && state.panel.attempts, gray: !state.panel.attempts}">
              {{ state.panel.weak ? '🔴 薄弱知识点' : state.panel.attempts ? '🔵 已接触' : '⚪ 未触达' }}</span>
            <span v-if="state.panel.avg_score != null" class="badge gray">均分 {{ state.panel.avg_score }}</span>
            <span class="badge gray">作答 {{ state.panel.attempts }} 次</span>
          </div>

          <!-- 行动区 -->
          <div class="know-strip" style="border:none; padding:0; margin-bottom:14px">
            <button class="btn primary" :disabled="state.variantStarting" @click="startVariants">
              {{ state.variantStarting ? '生成变体题中…' : '🔀 变体训练（换个问法也认识）' }}</button>
            <button class="btn" :disabled="state.packLoading || state.panel.knowledge_pack" @click="loadPack">
              {{ state.packLoading ? '知识包生成中…（约 1-2 分钟）' : state.panel.knowledge_pack ? '✓ 知识包已生成' : '📖 生成系统知识包' }}</button>
            <button class="btn" :disabled="state.diagnosing" @click="runDiagnose">
              {{ state.diagnosing ? '诊断中…' : '🔍 深度诊断我的欠缺' }}</button>
          </div>

          <!-- 深度诊断 -->
          <div v-if="state.panel.diagnosis" class="ai-comment" style="margin-bottom:14px">
            <b>{{ state.panel.diagnosis.gap_summary }}</b>
            <div v-if="state.panel.diagnosis.missed_points && state.panel.diagnosis.missed_points.length" style="margin-top:8px">
              <span class="hint">遗漏要点：</span>
              <span v-for="m in state.panel.diagnosis.missed_points" :key="m" class="badge bad" style="margin:2px">{{ m }}</span>
            </div>
            <div v-if="state.panel.diagnosis.misconception" style="margin-top:6px">⚠️ 误区：{{ state.panel.diagnosis.misconception }}</div>
            <div style="margin-top:6px">📌 {{ state.panel.diagnosis.review_advice }}</div>
          </div>

          <!-- 知识包（系统完整知识） -->
          <div v-if="state.panel.knowledge_pack" class="pack-box" style="margin-bottom:14px">
            <h4 style="font-size:13px; color:#5b6478; margin-bottom:8px">📖 系统知识包（完整原理 · 变体问法 · 识别信号）</h4>
            <div class="doc-body" style="max-height:340px; overflow:auto" v-html="renderAnswer(state.panel.knowledge_pack.content)"></div>
          </div>

          <!-- 弱点证据 -->
          <div v-if="state.panel.evidence && state.panel.evidence.length" style="margin-bottom:14px">
            <h4 style="font-size:13px; color:#5b6478; margin-bottom:8px">证据 · 我的历次作答</h4>
            <div v-for="(e, i) in state.panel.evidence" :key="i" class="rel-item" style="flex-wrap:wrap">
              <span class="badge" :class="e.score >= 60 ? 'warn' : 'bad'">{{ e.score }} 分</span>
              <span class="t">{{ e.title }}</span>
              <span class="hint" style="width:100%">{{ e.comment }}</span>
            </div>
          </div>

          <!-- 相关八股卡 -->
          <div v-if="state.panel.cards && state.panel.cards.length" style="margin-bottom:14px">
            <h4 style="font-size:13px; color:#5b6478; margin-bottom:8px">⚡ 速记卡（点击标记背诵状态）</h4>
            <div v-for="c in state.panel.cards" :key="c.id" class="rel-item" style="flex-wrap:wrap; align-items:flex-start">
              <div style="width:100%; display:flex; gap:8px; align-items:center">
                <span class="badge" :class="CARD_STATUS_META[c.status].cls">{{ CARD_STATUS_META[c.status].label }}</span>
                <b style="font-size:13px">{{ c.title }}</b>
              </div>
              <div class="hint" style="width:100%">{{ c.content }}</div>
              <div style="width:100%; display:flex; gap:6px">
                <button class="btn small danger" :disabled="c.status === 'new'" @click="markCard(c.id, 'new')">未掌握</button>
                <button class="btn small" :disabled="c.status === 'learning'" @click="markCard(c.id, 'learning')">待巩固</button>
                <button class="btn small primary" :disabled="c.status === 'mastered'" @click="markCard(c.id, 'mastered')">已背熟</button>
              </div>
            </div>
          </div>

          <!-- 关联面试题 -->
          <div v-if="state.panel.questions && state.panel.questions.length">
            <h4 style="font-size:13px; color:#5b6478; margin-bottom:8px">📋 该知识点考过的面试题</h4>
            <div class="rel-list">
              <div v-for="q in state.panel.questions" :key="q.id" class="rel-item">
                <span class="t">{{ q.title }}</span>
                <span v-if="q.my_attempts.length" class="badge" :class="q.my_attempts[q.my_attempts.length-1].score >= 60 ? 'warn' : 'bad'">
                  最近 {{ q.my_attempts[q.my_attempts.length-1].score }} 分</span>
              </div>
            </div>
          </div>

          <div class="answer-actions"><button class="btn" @click="closePanel">关闭</button></div>
        </template>
      </div>
    </div>
  </div>
  `,
};

const StudyView = {
  name: 'StudyView',
  setup() {
    const state = reactive({
      mode: 'cards',            // cards | docs
      category: 'MYSQL',
      overview: [],             // 各类进度汇总
      docs: [], doc: null,      // 文档视图
      cards: [], idx: 0,        // 卡片视图（当前翻到的卡）
      flipped: false,
      loading: true, error: '',
    });

    const catOverview = computed(() => state.overview.find(o => o.category === state.category) || null);

    async function loadOverview() {
      try { state.overview = await api('/study/overview'); } catch (e) { /* ignore */ }
    }

    async function loadCategory() {
      state.loading = true; state.error = '';
      try {
        const [cards, docs] = await Promise.all([
          api(`/study/cards?category=${state.category}`),
          api(`/study/docs?category=${state.category}`),
        ]);
        // 卡片排序：未学 → 待巩固 → 已背熟（把没背熟的顶到前面）
        const order = { new: 0, learning: 1, mastered: 2 };
        state.cards = cards.sort((a, b) => order[a.status] - order[b.status]);
        state.docs = docs;
        state.doc = docs.length ? docs[0] : null;
        if (state.doc) state.doc = await api(`/study/docs/${state.doc.id}`);
        state.idx = 0; state.flipped = false;
        loadOverview();
        nextTick(enhanceDiagrams);
      } catch (e) { state.error = e.message; }
      state.loading = false;
    }

    function pick(c) { state.category = c; loadCategory(); }
    function setMode(m) { state.mode = m; }
    function flip() { state.flipped = !state.flipped; }
    function nextCard() { state.flipped = false; state.idx = Math.min(state.idx + 1, state.cards.length - 1); }
    function prevCard() { state.flipped = false; state.idx = Math.max(state.idx - 1, 0); }

    async function mark(status) {
      const card = state.cards[state.idx];
      if (!card) return;
      try {
        await api(`/study/cards/${card.id}/status`, { method: 'POST', body: { status } });
        card.status = status;
        loadOverview();
        if (status === 'mastered') nextCard();  // 背熟自动跳下一张
      } catch (e) { state.error = e.message; }
    }

    async function openDoc(d) { state.doc = await api(`/study/docs/${d.id}`); nextTick(enhanceDiagrams); }

    const card = computed(() => state.cards[state.idx] || null);
    onMounted(loadCategory);
    onActivated(() => { if (state.cards.length || state.docs.length) { loadCategory(); } else { loadCategory(); } });

    return { state, card, catOverview, pick, setMode, flip, nextCard, prevCard, mark, openDoc, loadOverview, renderAnswer, CARD_STATUS_META, CATEGORY_NAMES };
  },
  template: `
  <div>
    <!-- 顶部：类别选择 + 形态切换 + 进度 -->
    <div class="card study-top">
      <select v-model="state.category" class="input" style="width:auto; min-width:140px" @change="pick(state.category)">
        <option v-for="(name, code) in CATEGORY_NAMES" :key="code" :value="code">{{ name }}</option>
      </select>
      <div class="chips" style="gap:6px">
        <button class="chip" :class="{on: state.mode === 'cards'}" @click="setMode('cards')">🃏 背诵卡片</button>
        <button class="chip" :class="{on: state.mode === 'docs'}" @click="setMode('docs')">📖 体系文档</button>
      </div>
      <div v-if="catOverview" class="hint" style="margin-left:auto">
        {{ catOverview.cards }} 卡 · 已背熟 {{ catOverview.mastered }}（{{ catOverview.progress }}%）· 待巩固 {{ catOverview.learning }}
      </div>
    </div>

    <div v-if="state.loading" class="card">加载中…</div>
    <div v-else-if="state.error" class="card error">{{ state.error }}</div>
    <div v-else-if="state.mode === 'docs'">
      <!-- 文档视图：左目录 + 右正文 -->
      <div class="study-layout">
        <div class="card study-toc">
          <h3>体系文档</h3>
          <div v-if="!state.docs.length" class="empty">该类别暂无文档</div>
          <div v-for="d in state.docs" :key="d.id" class="toc-item" :class="{on: state.doc && state.doc.id === d.id}" @click="openDoc(d)">
            📖 {{ d.title }}
          </div>
        </div>
        <div class="card study-content" v-if="state.doc">
          <h3>{{ state.doc.title }}</h3>
          <div class="doc-body" v-html="renderAnswer(state.doc.content)"></div>
        </div>
        <div class="card study-content empty" v-else>该类别暂无文档</div>
      </div>
    </div>
    <div v-else>
      <!-- 卡片视图：翻卡背诵 -->
      <div v-if="!state.cards.length" class="card empty">该类别暂无卡片</div>
      <template v-else>
        <div class="progress-wrap">
          <span class="badge">{{ state.idx + 1 }} / {{ state.cards.length }}</span>
          <div class="progress-track"><div class="progress-fill" :style="{width: (state.idx + 1) / state.cards.length * 100 + '%'}"></div></div>
          <span class="badge" :class="CARD_STATUS_META[card.status].cls">{{ CARD_STATUS_META[card.status].label }}</span>
        </div>
        <div class="card flip-card" @click="flip">
          <div v-if="!state.flipped">
            <div class="flip-front">{{ card.title }}</div>
            <div class="hint" style="text-align:center; margin-top:14px">先回忆要点，点击卡片翻开对照</div>
          </div>
          <div v-else>
            <div class="flip-back">{{ card.content }}</div>
            <div v-if="card.points && card.points.length" class="know-strip" @click.stop>
              <span class="hint" style="flex-shrink:0; align-self:center">⚡ 关键点</span>
              <span v-for="(p, i) in card.points" :key="i" class="badge gray">{{ p }}</span>
            </div>
          </div>
        </div>
        <div class="answer-actions" style="justify-content:center">
          <button class="btn ghost" :disabled="state.idx === 0" @click="prevCard">← 上一张</button>
          <button class="btn danger" :disabled="card.status === 'new'" @click="mark('new')">未掌握</button>
          <button class="btn" :disabled="card.status === 'learning'" @click="mark('learning')">待巩固</button>
          <button class="btn primary" :disabled="card.status === 'mastered'" @click="mark('mastered')">✓ 已背熟</button>
          <button class="btn ghost" :disabled="state.idx >= state.cards.length - 1" @click="nextCard">下一张 →</button>
        </div>
      </template>
    </div>
  </div>
  `,
};

/* ---------- 复盘（历史场次） ---------- */
const SessionsView = {
  name: 'SessionsView',
  setup() {
    const state = reactive({ list: [], detail: null, loading: true, cardMap: {}, cardDetail: null });
    async function load() {
      // 已有数据时静默刷新（KeepAlive 激活），仅首次显示加载态
      state.loading = state.list.length === 0 && !state.detail;
      state.list = await api('/interviews?limit=50');
      state.loading = false;
    }
    async function openDetail(id) {
      state.detail = await api(`/interviews/${id}`);
      window.scrollTo({ top: 0 });
      // 并行拉取各题关联八股卡（复盘里直接给出"背哪几张卡"）
      state.cardMap = {};
      const answered = state.detail.answers.filter(a => a.answered);
      await Promise.all(answered.map(async a => {
        try {
          const r = await api(`/questions/${a.question_id}/cards`);
          if (r.cards.length) state.cardMap[a.question_id] = r.cards;
        } catch (e) { /* 忽略 */ }
      }));
      nextTick(enhanceDiagrams);
    }
    function back() { state.detail = null; }
    function exportMd() { window.open('/api/interviews/' + state.detail.id + '/export'); }
    async function markCard(cardId, status) {
      try {
        await api(`/study/cards/${cardId}/status`, { method: 'POST', body: { status } });
        if (state.cardDetail && state.cardDetail.id === cardId) state.cardDetail.status = status;
        state.cardMap = { ...state.cardMap, ...Object.fromEntries(Object.entries(state.cardMap).map(([qid, cs]) => [qid, cs.map(c => c.id === cardId ? { ...c, status } : c)])) };
      } catch (e) { /* 忽略 */ }
    }
    onMounted(load);
    onActivated(() => { if (state.list.length || state.detail) load(); });
    return { state, openDetail, back, exportMd, markCard, fmtTime, scoreClass, renderAnswer, CARD_STATUS_META, CATEGORY_NAMES, DIFF_LABEL };
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
            <div v-if="state.cardMap[a.question_id] && state.cardMap[a.question_id].length" class="know-strip">
              <span class="hint" style="flex-shrink:0; align-self:center">📚 相关八股</span>
              <span v-for="c in state.cardMap[a.question_id]" :key="c.id" class="chip small" @click="state.cardDetail = { ...c }">
                {{ CARD_STATUS_META[c.status].label }} · {{ c.title }}</span>
            </div>
            <div class="compare">
              <div><h4>你的回答</h4><div class="box you" style="max-height:none">{{ a.answered ? (a.user_answer || '（未作答）') : '未作答' }}</div></div>
              <div><h4>满分答案</h4><div class="box model" style="max-height:none" v-html="renderAnswer(a.answered ? a.model_answer : '（提交后可见）')"></div></div>
            </div>
          </div>
        </div>
      </div>
    </template>

    <!-- 复盘内的八股卡弹窗 -->
    <div v-if="state.cardDetail" class="modal-mask" @click.self="state.cardDetail = null">
      <div class="modal">
        <h3>{{ state.cardDetail.title }}</h3>
        <div class="q-meta" style="margin-bottom:12px">
          <span class="badge">{{ state.cardDetail.category_name }}</span>
          <span class="badge" :class="CARD_STATUS_META[state.cardDetail.status].cls">{{ CARD_STATUS_META[state.cardDetail.status].label }}</span>
        </div>
        <div class="box you" style="max-height:none; margin-bottom:12px">{{ state.cardDetail.content }}</div>
        <div v-if="state.cardDetail.points && state.cardDetail.points.length" class="know-strip" style="border:none; padding:0; margin-bottom:14px">
          <span class="hint" style="flex-shrink:0; align-self:center">⚡ 关键点</span>
          <span v-for="(p, i) in state.cardDetail.points" :key="i" class="badge gray">{{ p }}</span>
        </div>
        <div class="know-strip" style="border:none; padding:0">
          <button class="btn small danger" :disabled="state.cardDetail.status === 'new'" @click="markCard(state.cardDetail.id, 'new')">未掌握</button>
          <button class="btn small" :disabled="state.cardDetail.status === 'learning'" @click="markCard(state.cardDetail.id, 'learning')">待巩固</button>
          <button class="btn small primary" :disabled="state.cardDetail.status === 'mastered'" @click="markCard(state.cardDetail.id, 'mastered')">✓ 已背熟</button>
        </div>
        <div class="answer-actions">
          <button class="btn" @click="state.cardDetail = null">关闭</button>
        </div>
      </div>
    </div>
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

/* ---------- 简历面试：上传简历 → 生成深挖题 → 开考 ---------- */
const ResumeView = {
  name: 'ResumeView',
  emits: ['start-session'],
  setup(props, { emit }) {
    const state = Vue.reactive({
      loading: true,
      versions: [],
      questionCount: 0,
      uploading: false,
      pasteOpen: false,
      pasteText: '',
      genCount: 8,
      generating: false,
      genResult: null,   // {added, skipped, question_count}
      error: '',
      starting: false,
    });

    async function load() {
      state.loading = true;
      try {
        const d = await api('/resume');
        state.versions = d.versions;
        state.questionCount = d.question_count;
      } catch (e) { state.error = e.message; }
      state.loading = false;
    }
    onActivated(load);
    load();

    async function uploadFile(ev) {
      const f = ev.target.files && ev.target.files[0];
      ev.target.value = '';
      if (!f) return;
      state.uploading = true; state.error = '';
      try {
        const fd = new FormData();
        fd.append('file', f);
        const resp = await fetch('/api/resume/upload', { method: 'POST', body: fd });
        const d = await resp.json();
        if (!resp.ok) throw new Error(d.detail || '上传失败');
        await load();
      } catch (e) { state.error = e.message; }
      state.uploading = false;
    }

    async function pasteSave() {
      if (state.pasteText.trim().length < 100) { state.error = '请粘贴完整简历（至少 100 字符）'; return; }
      state.uploading = true; state.error = '';
      try {
        await api('/resume/paste', { method: 'POST', body: { content: state.pasteText } });
        state.pasteText = ''; state.pasteOpen = false;
        await load();
      } catch (e) { state.error = e.message; }
      state.uploading = false;
    }

    async function activate(id) {
      try { await api(`/resume/${id}/activate`, { method: 'POST', body: {} }); await load(); }
      catch (e) { state.error = e.message; }
    }
    async function removeVersion(id) {
      try { await api(`/resume/${id}`, { method: 'DELETE' }); await load(); }
      catch (e) { state.error = e.message; }
    }

    async function generate() {
      state.generating = true; state.error = ''; state.genResult = null;
      try {
        const d = await api('/resume/generate-questions', {
          method: 'POST',
          body: { count: state.genCount },
        });
        state.genResult = d;
        state.questionCount = d.question_count;
      } catch (e) { state.error = e.message; }
      state.generating = false;
    }

    async function startInterview() {
      if (!state.questionCount) { state.error = '题池为空，请先生成简历题'; return; }
      state.starting = true; state.error = '';
      try {
        const r = await api('/interviews', {
          method: 'POST',
          body: { position: '简历项目深挖', count: Math.min(state.genCount, state.questionCount), categories: ['RESUME'] },
        });
        emit('start-session', r.session_id);
      } catch (e) { state.error = e.message; }
      state.starting = false;
    }

    return { state, uploadFile, pasteSave, activate, removeVersion, generate, startInterview, fmtTime, CATEGORY_NAMES };
  },
  template: `
  <div>
    <div v-if="state.loading" class="card">加载中…</div>
    <template v-else>
      <div class="card">
        <h3>📄 简历面试</h3>
        <p class="hint" style="line-height:1.8">
          上传你的简历，AI 会围绕<b>简历上写的项目、量化数据和技能</b>生成深挖追问题
          （为什么这么选型 / 指标怎么测出来的 / 踩过什么坑），答完与建议回答对比 + AI 评分。
          简历文本会发送给你配置的 LLM 服务商。
        </p>
        <div class="answer-actions">
          <label class="btn primary" style="cursor:pointer">
            {{ state.uploading ? '处理中…' : '⬆️ 上传简历（PDF / TXT / MD）' }}
            <input type="file" accept=".pdf,.txt,.md" style="display:none" @change="uploadFile" :disabled="state.uploading">
          </label>
          <button class="btn ghost" @click="state.pasteOpen = !state.pasteOpen">{{ state.pasteOpen ? '收起粘贴框' : '📋 或直接粘贴文本' }}</button>
        </div>
        <div v-if="state.pasteOpen" style="margin-top:12px">
          <textarea v-model="state.pasteText" class="input" rows="6" placeholder="把简历全文粘贴到这里…"></textarea>
          <div class="answer-actions"><button class="btn primary" :disabled="state.uploading" @click="pasteSave">保存为新版本</button></div>
        </div>
        <p v-if="state.error" class="error">{{ state.error }}</p>
      </div>

      <div class="card">
        <h3>🗂 简历版本 <span class="hint">出题时使用 ✅ 激活版本；已生成的题目保留在题库（类别：简历深挖）</span></h3>
        <div v-if="!state.versions.length" class="empty">还没有上传过简历</div>
        <ul v-else class="hot-list">
          <li v-for="v in state.versions" :key="v.id">
            <span class="cat">{{ v.is_active ? '✅ 使用中' : '历史' }}</span>
            {{ v.filename }} <em>{{ v.char_count }} 字 · {{ fmtTime(v.created_at) }}</em>
            <span style="margin-left:auto; display:flex; gap:6px">
              <button v-if="!v.is_active" class="btn small ghost" @click="activate(v.id)">设为使用中</button>
              <button class="btn small ghost danger" @click="removeVersion(v.id)">删除</button>
            </span>
          </li>
        </ul>
      </div>

      <div class="card">
        <h3>🎯 生成简历深挖题 <span class="hint">题池现有 {{ state.questionCount }} 道</span></h3>
        <div class="answer-actions">
          <span v-for="n in [5, 8, 10, 15]" :key="n" class="chip" :class="{ on: state.genCount === n }" @click="state.genCount = n">{{ n }} 题</span>
          <button class="btn primary" :disabled="state.generating || !state.versions.some(v => v.is_active)" @click="generate">
            {{ state.generating ? 'AI 正在读简历出题…（约 1-2 分钟）' : '🧠 生成深挖题' }}
          </button>
        </div>
        <p v-if="state.genResult" class="hint">
          ✅ 本次生成 {{ state.genResult.added }} 道{{ state.genResult.skipped ? '（去重跳过 ' + state.genResult.skipped + ' 道）' : '' }}，题池共 {{ state.genResult.question_count }} 道。可在「题库」页筛选「简历深挖」审题或修改。
        </p>
        <div class="answer-actions" style="margin-top:8px">
          <button class="btn primary" :disabled="state.starting || !state.questionCount" @click="startInterview">
            {{ state.starting ? '开考中…' : (state.questionCount ? '🎤 开始简历面试（' + Math.min(state.genCount, state.questionCount) + ' 题）' : '题池为空，请先生成') }}
          </button>
        </div>
      </div>
    </template>
  </div>
  `,
};

/* ---------- 根组件 ---------- */
const App = {
  components: { InterviewView, SessionsView, ReviewView, BankView, SettingsView, MapView, StudyView, ResumeView },
  setup() {
    const view = ref('home');
    const sessionId = ref(null);
    const tabs = [
      { key: 'home', label: '开始面试' },
      { key: 'resume', label: '简历面试' },
      { key: 'study', label: '八股文库' },
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
    const recentPositions = ref([]);   // 历史岗位（localStorage 记忆，点击回填）
    const stats = reactive({});
    const chart = ref(null);
    let chartInst = null;

    /* 岗位历史 + 上次设置的记忆（localStorage） */
    function loadRecentPositions() {
      try { recentPositions.value = JSON.parse(localStorage.getItem('recent_positions') || '[]'); }
      catch (e) { recentPositions.value = []; }
    }
    function rememberPosition(pos) {
      let list = recentPositions.value.filter(p => p !== pos);
      list.unshift(pos);
      recentPositions.value = list.slice(0, 8);
      try { localStorage.setItem('recent_positions', JSON.stringify(recentPositions.value)); } catch (e) { /* 忽略 */ }
    }
    function removeRecentPosition(pos) {
      recentPositions.value = recentPositions.value.filter(p => p !== pos);
      try { localStorage.setItem('recent_positions', JSON.stringify(recentPositions.value)); } catch (e) { /* 忽略 */ }
    }
    function saveLastSettings() {
      try {
        localStorage.setItem('last_settings', JSON.stringify({ count: count.value, categories: picked.value }));
      } catch (e) { /* 忽略 */ }
    }
    function restoreLastSettings() {
      try {
        const s = JSON.parse(localStorage.getItem('last_settings') || 'null');
        if (!s) return;
        if ([5, 10, 15].includes(s.count)) count.value = s.count;
        if (Array.isArray(s.categories)) picked.value = s.categories.filter(c => (categories.value || []).some(x => x.code === c) || ['MYSQL','REDIS','JAVA','JVM','CONCURRENT','SPRING','NETWORK','SCENARIO','AI_APP','AGENT','FULLSTACK','OS','DISTRIBUTED','ALGO','PYTHON','RESUME'].includes(c));
      } catch (e) { /* 忽略 */ }
    }

    function go(v) { view.value = v; }

    /* ---- Hash 路由：F5 恢复当前页面 + 浏览器前进后退 ---- */
    const VIEW_HASH = { home: '#/', resume: '#/resume', sessions: '#/sessions', review: '#/review', bank: '#/bank', settings: '#/settings', map: '#/map', study: '#/study' };
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
      view.value = { '#/': 'home', '#/resume': 'resume', '#/sessions': 'sessions', '#/review': 'review', '#/bank': 'bank', '#/settings': 'settings', '#/map': 'map', '#/study': 'study' }[h] || 'home';
      if (view.value !== 'interview') sessionId.value = null;
    }
    window.addEventListener('hashchange', applyHash);
    // 视图/session 变化同步到地址栏
    watch([view, sessionId], syncHash);
    const VIEW_TITLES = { home: '开始面试', interview: '面试中', resume: '简历面试', study: '八股文库', map: '知识地图', sessions: '复盘', review: '错题本', bank: '题库', settings: '设置' };
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
        rememberPosition(position.value);   // 记住岗位（下次一键回填）
        saveLastSettings();                 // 记住题数与考察范围
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
    function onVariantStart(sid) { sessionId.value = sid; view.value = 'interview'; }
    function onResumeStart(sid) { sessionId.value = sid; view.value = 'interview'; }

    onMounted(() => {
      applyHash();          // 按 URL hash 恢复页面（如刷新前在面试页）
      loadRecentPositions(); // 历史岗位回填列表
      loadHealth(); loadMeta(); loadStats(); checkResume();
      // 类别元数据到达后恢复上次的考察范围选择
      nextTick(() => { restoreLastSettings(); picked.value = picked.value.filter(c => !categories.value.length || categories.value.some(x => x.code === c)); });
      setInterval(loadHealth, 30000);  // 健康徽章自动跟随服务状态
    });

    return {
      view, tabs, health, go, sessionId,
      position, count, categories, picked, toggleCat, starting, error, llmEnabled,
      recentPositions, removeRecentPosition,
      startInterview, quickDrill, stats, chart, loadHealth,
      resumeSession, resumeInterview, abandonResume, onHome, onInterviewFinished, onVariantStart, onResumeStart,
    };
  },
};

/* 根模板直接使用 index.html 中 #app 的 DOM 结构（vue.global 自带编译器） */
createApp(App).mount('#app');

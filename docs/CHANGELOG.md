# CHANGELOG — 同传课堂 (live-subtitle)

变更日志，按时间倒序。用于跨机器交接（Windows planner / Mac implementer）与版本回顾。

---

## 2026-09-02 — v3.7 补充：定稿模型 medium → large-v3-turbo

### 🎯 用户问题
「有没有又快又好的模型或方法」→ 实测蒸馏/涡轮模型在 M5 CPU 的真实表现。

### 🔬 实测（M5 CPU int8，session_96 同段音频）
| 模型 | 草稿 3s窗 | 定稿 5s窗 | 质量 |
|---|---|---|---|
| small | 1.65s | 2.2s | 基准 |
| medium | 5.2s | 6.8s | 部分错 |
| **large-v3-turbo** | **4.45s** | **4.99s** | **large-v3 级（完整句）** |

关键结论：turbo/distil 在 **M5 CPU 短窗场景只快 ~15%**（非宣称 8x）——瓶颈是
whisper 架构「每次调用编码整 30s mel」的固定开销（encoder 未减层、参数≈medium），
decoder 减 8 层对短文本解码影响小。**模型内卷无解，速度飞跃只能靠 GPU 编码**
（whisper.cpp Metal / MLX，远期）或流式增量（远期）。
但 turbo 质量 = large-v3 级、速度 ≈ medium → 定稿精修是**纯赚**：准确率更高，
后台异步不在乎那点速度差。

### 🔧 变更
- `.env`：`ASR_MODEL = large-v3-turbo`（定稿精修；模型已缓存，启动即用）。
- 双轨保持：草稿 `ASR_PARTIAL_MODEL=small`（实时跟读）+ 定稿 turbo（准确入库）。
- **需重启应用生效。**

---

## 2026-09-02 — v3.7：双轨识别（字幕 small 跟读 + 定稿 medium 精修）

### 🎯 用户决策
「字幕用 small，框内的用 medium，识别正确更加重要。」——全 medium 在实时链路
单线程会积压卡死（medium 单次 5.2s > 触发间隔），故采用双模型并行。

### 🔧 改动
1. `app/config.py`：新增 `ASR_PARTIAL_MODEL`（草稿模型，默认 small）；`ASR_MODEL`
   语义改为**定稿精修模型**（.env = medium）。
2. `app/recorder.py` 双轨管道：
   - 新增 `m_q`（定稿精修队列）；`asr_worker` 只服务 partial（small 快速跟读），
     final 音频转发 `m_q`；
   - 新增 `final_asr_worker`（独立线程 + `tr_final` 实例，medium beam5 精修，
     不与其他识别共用 `_mlock`——不同实例线程安全），精修后入 `f_q` 走翻译入库；
   - `Recorder(store, tr, tsl, tr_final=None)`——None 时单模型兼容旧路径
     （small beam5 + 复用预翻）；
   - 哨兵链：asr_worker 退出 → p_q/m_q None → final_asr_worker 收 m_q None 后
     发 f_q None → final_worker 退出；代际机制覆盖 final_asr_worker。
3. `app/ui/main_window.py`：`_warmup_model` 加载双模型（草稿 + 定稿，同模型则
   单轨 tr_final=None）；`_ensure_recorder` 传 tr_final。
4. `.env`：`ASR_MODEL=medium`（定稿精修）；`.env` 值后禁止行内注释
   （load_dotenv 不剥注释，会混进模型名——踩坑两次，已统一清理）。

### ✅ 验收
- 新增 `scripts/smoke_dual_track.py` 全过：final 入库文本 = 精修模型结果且翻译
  基于精修文本；双轨收尾哨兵链正常；单模型（tr_final=None）兼容旧路径。
- 全量 10 套件回归全绿。
- 预期：悬浮字幕 small 跟读（~3s 延迟不卡）；框内/卡片/导出/笔记 = medium
  准确版（句子定稿后 ~7s 入库）。内存 ~2.1GB（small 0.5 + medium 1.6）。
- **需重启应用生效。**

---

## 2026-09-02 — v3.6 补充：ASR 回退 small（medium 实时链路实测不可用）

### 🎯 用户反馈
「本地识别应该很快就出来吧？体感老师说到出现有 4 秒。」

### 🔬 实测（单次推理耗时，session_96 语音片段）
| 模型 | beam1 3s窗 | beam5 5s窗 |
|---|---|---|
| **small** | **1.65s** | 2.2s |
| **medium** | **5.2s** | 6.8s |

根因：whisper 短音频也按 30s pad 计算，单次调用有巨大固定开销——**不能用整段批量
RTF（medium 0.07）判断实时可行性**。之前按批量 RTF 换 medium 是失误（用户 4s 延迟
正是 medium 造成）。延迟构成 = 触发 1.2s + 识别 1.65s + 防抖 + final 插队排队 ≈ 3~4s。

### 🔧 变更
1. `.env`：`ASR_MODEL` 回退 **small**（medium 单次 5.2s 实时不可用；medium 仅适合
   课后整段批量精修，批量 RTF 0.07 快且准——待做「双轨精修」功能）。
2. 上屏防抖 0.3s → 0.15s（`app/recorder.py`）。
3. 坑：`.env` 值后不能加行内注释（load_dotenv 不去注释，会把注释混进模型名）。

### ✅ 验收
关键回归全绿（streamer 7 / finalize 6 / 续录 / 代际隔离）。
- 预期：字幕延迟回到 ~2.5~3s（small 时代水平）；要降到 1s 内需流式 ASR 或
  partial 并行实例（远期方向）。
- **需重启应用生效。**

---

## 2026-09-02 — v3.6：周期定稿防腰斩（修复「漏掉最后几个词」）

### 🎯 用户反馈
「有时候会感觉漏掉最后几个词没进发言」+ 询问 medium 内存占用。

### 🔬 定位
session_99 实测：196 段中 **88 段（45%）无终止标点结尾**——5s 周期定稿在
句子中间截断，句子后半（最后几个词）丢失；课堂连续语音下 ASR 标点稀疏，
标点补全机制经常不触发，大量句子靠周期定稿 → 腰斩。

### 🔧 改动（`app/recorder.py`）
- 新增 `_sentence_incomplete(text, rms, talk_gap, since)`：句子未完（最近转写
  无终止标点）且仍在说话（能量高 或 最近 2s 内有非空文本——外放/远场低音量
  兜底）且未超 `_PENDING_MAX=10s` → 跳过本次周期定稿，等句子说完（静音/标点）
  再整句入库；超上限强制定稿兜底（防长句无限跳过）。
- feed_loop 周期定稿处接入该判定。

### ✅ 验收
- 新增 `tests/test_finalize_policy.py` 6 项全过（句中+高能量跳过、句中+低音量
  talk 兜底跳过、带标点定稿、说完停顿定稿、超上限强制定稿、空文本不跳过）。
- 全量 9 套件回归全绿。
- 预期：句子完整入库率显著提升（45% 截断 → 仅剩 >10s 超长连续句的强制截断）。
- **需重启应用生效。**

---

## 2026-09-02 — ASR 升级：small → medium（实测验证后切换）

### 🎯 背景
用户反馈「字幕有些不对，导致中文也不对」，要求用之前的录音实测判断。

### 🔬 实测（脚本 scripts/diag_asr_quality.py，样本=EnglishPod 对话 session_96/98）
同一句 "hired an intern"（标准发音）：
| 来源 | 结果 |
|---|---|
| 实时链路（当时 small 5s 窗） | "hide it in here"（全错）|
| 离线 small（beam5+VAD） | "hired Inter"（部分错）|
| 离线 **medium** | "hired an intern"（正确）|

结论：**不是老师发音问题**（medium 一次就对）；中文错是英文识别错的传导（翻译源文本错）。
三层原因：① small 模型对连读/弱读消歧弱（WER 36~46% 主因）；② 实时滑动窗切分损失跨窗上下文；
③ 无课程术语热词兜底。

### 🔧 变更
- `.env`：`ASR_MODEL=small → medium`（medium 模型 1.4G 已在本地缓存，无需下载）。
- 实测 M5：加载 0.9s、60s 音频 RTF 0.07（实时富余；16GB 内存 OK）。
- 注意：`config.load_dotenv` 用 `os.environ.setdefault`（只认第一个值）——.env 里若已有旧值
  需改原行而非追加新行，否则不生效（本次踩坑）。

### ⚠️ 说明
- medium 明显提升但非 100%：对 "an intern" 这类弱读偶有波动（流式窗口切分固有），
  后续可用课程术语表（whisper 热词/prompt 注入）进一步兜底。
- **需重启应用生效**。

---

## 2026-09-02 — v3.5：字幕流畅度优化（事件驱动 + 短窗双轨 + 去重修复）

### 🎯 背景
用户反馈「英文字幕不算快」；双 subagent 评估（性能派 vs 课堂派）结论冲突，
用户拍板「保守稳」：A 事件驱动 + B 短窗 3.0s + 去重修复 + 触发 1.2s
（2.5s 窗在教室混响/远场下 WER 55~70%，3.0s 是课堂安全下限）。

### 🔧 改动
1. **短窗双轨**（`app/streamer.py`）：新增 `partial_asr_win`（默认回退 asr_win
   兼容旧行为）；`feed()` 的 partial 分支喂 3s 窗（realtime），`finalize()` 仍
   5s 窗精校——「快草稿 + 慢精校」，草稿识别 0.6s→0.36s/次。
2. **触发与上屏节奏**（`app/recorder.py`）：`_apply_mode` realtime 模式
   partial_win 1.5→1.2s、partial_asr_win=3.0s（precise 模式参数不动）；
   partial_worker 上屏节流 1.5s→0.3s（事件驱动：有变化就刷 + 300ms 防抖，
   同文本去重保留）。
3. **去重修复**（`app/recorder.py`）：`_same_sentence` 前缀判据在短窗下失效
   （短窗 partial 只重发句尾片段、前缀重合低 → 同句被判新句 → 重复定稿），
   重写为 **时间窗重叠 + 长度 + 文本覆盖** 三判据：窗口不重叠→放行；
   长度明显增长（残句补全）→放行；同音频且长度不增→文本覆盖率高判同跳过。
   feed_loop 标点定稿处计算窗口重叠率传入。
4. **复用阈值**：`_REUSE_OVERLAP` 0.7→0.5（3s/5s 窗最大重叠 0.6，恢复
   「定稿复用预翻」机制，final 不必恒跑 beam5）。

### ✅ 验收
- 新增 `tests/test_streamer_smoke.py` 7 项全过：短窗双轨（partial=3s/final=5s、
  触发间隔 1.2s）、_same_sentence 五场景（同句重发判同、短窗尾部片段判同、
  残句补全放行、窗口不重叠放行、不同句放行）、默认回退兼容。
- 全量 8 套件回归全绿（3 处 FakeEngine 加 partial_asr_win 兼容参数）。
- 预期体感：字幕从「1.5~2s 跳一次」→「~1.2s 滚一次」，端到端滞后 1.2~1.8s。
- 待实测：教室实跑看草稿观感；错字闪现偏多则下一步补低置信度灰显
  （avg_logprob 标定）。**需重启应用生效。**

---

## 2026-09-02 — P0 修复：停止→续录代际隔离 + 录制中锁翻译引擎

### 🎯 来源
代码审查 subagent 报告的两个 P0（数据安全风险）。

### 🔧 P0#1 停止→续录竞态（`app/recorder.py`）
收尾 `_finish` join 超时后残留 worker（daemon）仍活着；用户立即「继续录制/
新建」时旧 worker 会消费新会话任务，闭包 sid 是旧的 → 句子写进错误课节或
重复入库。修复：
1. **代际机制**：`_start_workers` 创建新 `_epoch_ev` 并 set 旧的；三个 worker
   主循环 `get(timeout=0.5)` 轮询 epoch，旧代际 worker 半秒内自行退出。
2. **f_q 任务带 sid**：asr_worker 放 `f_q` 时用动态 `self.session_id`（非闭包）；
   final_worker 校验 sid 不匹配 → 放回队尾让正确代际处理，放回 3 次无归属则
   丢弃（防无限放回死循环），绝不写入本课节。
3. `_workers` 线程引用清理（过滤已退出）。

### 🔧 P0#2 录制中切换翻译引擎（`app/ui/main_window.py`）
`on_settings` 切引擎置 `self.recorder = None` → `on_stop` 直接 return →
录音无法结束（只能强杀进程，复刻 session 93 数据丢失坑）。修复：录制中
（`_recording_active`）打开设置时「翻译引擎」下拉框禁用 + 红色提示
「录制中已锁定」；on_settings 兜底：即便 provider 变化也不重建 recorder。

### ✅ 验收
- 新增 `scripts/smoke_epoch_guard.py` 全过：跨会话任务被拦截（不写错课节、
  无死循环）、代际切换后新旧会话互不串台、残留旧代际任务被丢弃。
- `tests/test_mainwindow_smoke.py` 新增 lock_provider 断言（录制中 provider
  禁用）3/3 全过。
- 全量回归 7 套件全绿（smoke_context_translate 因 f_q 格式变更同步更新）。
- **需重启应用生效。**

---

## 2026-09-02 — v3.4：悬浮字幕只显英文（撤掉中文行）+ 右侧英文/中文双积累框

### 🎯 用户反馈
「怎么感觉英文字幕变慢了，中文字幕还是取消吧，就还是在框内积累的翻译。
要不搞个英文也在框内积累的，俩个框可以看中文和英文。」

### 🔧 改动
1. **悬浮字幕回到只显英文**（`app/overlay.py`）：彻底删除中文行（zh label /
   淡入动画 / show_zh 开关），只保留英文单行 + v3.3 固定高度 66px 稳定布局。
   **英文字幕变慢的原因**：v3.3 的中文行 QGraphicsOpacityEffect 淡入动画对
   透明浮动窗口（WA_TranslucentBackground + 浮动层）有合成开销，移除后恢复流畅。
2. **主窗口右侧改双积累框**（`app/ui/main_window.py`）：新增「英文原文」
   `en_box`（等宽字体 Menlo，逐句累积 + 自动滚底），与「中文译文」`zh_box`
   上下并列（QSplitter Vertical）——中英逐句对照看。`_append_en` 排除
   `[ASR错误]`；`_clear_transcript`（切会话/新建）清空双框。
3. **设置清理**：删除 `show_zh_subtitle` 开关（settings.py / 设置对话框 /
   `_show_overlay` / `on_settings` 全部移除）。

### ✅ 验收
- `tests/test_overlay_smoke.py` 重写 8 项全过（只显英文、固定 66px、短句化
  保留末尾、单行省略、空英文占位）。
- `scripts/smoke_v3_dual_pane.py` 更新全过（overlay 只显英文 66px、右侧
  en_box 累积滚底、切会话清空双框）。
- 回归：续录、上下文翻译、主窗口、accumulate 全过。
- **需重启应用生效。**

---

## 2026-09-02 — v3.3：悬浮字幕双行稳定布局 + 中文译文行淡入

### 🎯 用户拍板
舒适度方案第一项（见 v3.2 讨论）：「悬浮窗加译文行 + 稳定布局」。

### 🔧 改动（`app/overlay.py` + `app/settings.py` + `app/ui/main_window.py`）
1. **恢复中文译文行**：`update_text`（final）后 zh 行显示译文并 **320ms 淡入**
   （QGraphicsOpacityEffect + QPropertyAnimation 挂在 zh 外包容器，避免与
   文字阴影 effect 冲突）；`update_partial` 阶段中文行保持上一句 final 译文不动
   （不随英文打字机高频闪烁），新句定稿时随译文一起淡入更新。
2. **固定高度稳定布局**：英文/中文行都改单行（关闭换行、超宽 elide 省略），
   窗口总高固定——双行 104px / 单行 66px，只由「是否显示中文行」决定，
   **不再随文本换行数跳变**（此前 `_relayout` 按换行高度重算是跳动主因）。
3. **短句化上限适配单行**：英文 72→56 字符、中文 48（1200px 窗口 28px 粗体
   单行约容 60 字符）；`_tail_clause` 词边界截断修正为**保留末尾窗口**
   （显示正在说的部分，旧实现截开头，长句跟读看不到新词）。
4. **设置开关**：`show_zh_subtitle`（默认开）——关闭时中文行隐藏、窗口收窄为
   单行；打开恢复双行并复原最近译文。设置对话框加「悬浮字幕」分组复选框，
   即时生效（无需重启）。

### ✅ 验收
- `tests/test_overlay_smoke.py` 重写并扩到 8 项全过：打字机累积、final 替换、
  partial 不动中文行、固定高度稳定（短/长句高度不变）、单行 elide、中文行开关、
  空英文占位、暂停/恢复。
- `scripts/smoke_v3_dual_pane.py` 5/5b 更新为 v3.3 语义全过（双行 104 固定、
  长句 97→56 字符保留末尾 "that keeps growing…"、开关 66/104 切换）。
- 回归：续录、上下文翻译、主窗口冒烟、accumulate 11 项全过。
- **需重启应用生效。**

---

## 2026-09-02 — v3.2：背景式上下文翻译（前 N 句英中作背景）

### 🎯 背景
用户反馈逐句翻译偶有指代混乱（this/that/it 孤立翻译）；经对比讨论，拍板
「背景式」方案：**当前句单独翻译，前 2 句英中对照注入 prompt 供指代/话题理解**，
维持逐句 1:1 对齐（不做批量翻译，避免打断实时链路）。

### 🔧 改动
1. `app/config.py`：`TRANSLATE_CONTEXT=2`（前 N 句背景，0=关闭，可 .env 覆盖）。
2. `app/storage.py`：`recent_context(sid, before_seq, n)` —— 取定稿句之前的最近
   N 句（seq 升序），自动跳过 `[ASR错误]` / `[翻译失败]` / 空行，避免脏背景。
3. `app/translate.py`：
   - 新增 `CONTEXT_SYSTEM_PROMPT`（明确「只翻译当前句，不重复背景」）+ 纯函数
     `build_context_user(text, context)` 拼背景行。
   - LLM 引擎（DeepSeek / DashScope / Ollama）`translate(text, context=None)`：
     context 非空走背景 prompt 且不再叠加 `last_zh`（背景已含上句）；无 context
     保持旧行为（上一句译文 + SYSTEM_PROMPT），完全向后兼容。
   - 统计类引擎（百度 / 腾讯 / 阿里）加 `context=None` 兼容签名并忽略（无法注入 prompt）。
4. `app/recorder.py` `final_worker`：定稿翻译前 `store.recent_context(sid, s, n=config.TRANSLATE_CONTEXT)`，
   背景注入 `tsl.translate(en, context=ctx or None)`。

### ✅ 验收
- 新增 `scripts/smoke_context_translate.py` 全过：recent_context 前 N 句升序 + 跳过失败行
  + n=0 关闭；build_context_user 结构（背景行 + 当前句行）；DeepSeek context 分支用背景提示词、
  无 context 保持旧行为；final_worker 真实链路验证新句翻译携带前 2 句英中背景、逐句对齐入库。
- 回归：续录冒烟、v3 双区冒烟全过（FakeTsl 同步加 context 参数）。

### ⚠️ 说明
- 背景只影响 LLM 类翻译引擎；百度/腾讯/阿里仍是逐句独立翻译。
- 每句多带 ~2 句背景，token 成本略增（可忽略）；延迟不变（仍是单次 LLM 调用）。
- 需重启应用生效。

---

## 2026-09-02（凌晨）— v3.1：悬浮字幕只显英文 + 短句化显示

### 🎯 用户反馈
1. 「有时候会跳出带中文的字幕」——v3 只砍了 partial 的中文，**final 定稿 `update_text(en, zh)` 仍把中英双语打到悬浮字幕**。
2. 「英文字幕不是一句话一句话展示，有时候会是一个大长句」——partial 句子累积（打字机）会让显示文本越长越大。

### 🔧 改动（`app/overlay.py`）
1. **字幕只显英文**：`update_text`（final）不再上中文，`zh` 行恒隐藏——中文译文只累积在主窗口右侧「中文译文」区（用户拍板：翻译慢慢显示没关系）。
2. **短句化 `_tail_clause(text, max_chars=72)`**：只显示最后一个句子/从句（含正在说的片段）——先按 `.!?` 断句取尾句，仍超长按 `,;` 收窄到末从句，再超按词边界截断（保留末尾内容）。`update_partial` 显示 `_tail_clause(new_en) + " …"`；`update_text` 显示 `_tail_clause(en)`。
3. **空英文回退**：`update_text("", "等待老师讲课…")` 启动占位等状态提示仍显示中文（状态非译文）。

### ✅ 验收
- `scripts/smoke_v3_dual_pane.py` 新增 5b 断言全过：final 中文行隐藏且显示尾句（"This is the second sentence."）、97 字符长句 partial 短句化到 73 字符且保留末尾、空英文保留中文占位；既有 7 项回归全过。
- 续录冒烟回归全过。

### ⚠️ 说明
- 完整英文句仍在主窗口转写区卡片（partial 虚线卡 / 定稿卡）；字幕只做实时跟读提示。
- 需重启应用生效。

---

## 2026-09-01（夜）— 续录：已结束的课节可重新打开，追加录制到同一节

### 🎯 用户问题
「如果我按结束但是我之后还想在那节课继续录制就无法搞了」——结束后（误按/下课又补录）只能新建「第 N+1 节」，无法合并到同一课节。

### 🔧 改动
1. **数据层**（`app/storage.py`）：
   - 新表 `session_audio(session_id, ord, file, start_epoch)`：登记每段续录 wav 及起始墙钟（主录音不登记，起点用 sessions.started_at）；
   - `resume_session(sid)`：status done → recording、清 ended_at；`add_session_audio` / `list_session_audio`；`max_seq(sid)` 供续录序号接着编。
2. **Recorder**（`app/recorder.py`）：`start()` 重构出 `_reset_state()` + `_launch()` 公共尾段；新增 `continue_session(sid)`——复用 session_id、seq 从 max 续编、音频写新文件 `session_{sid}_contN.wav`（不动原文件）、成功后登记 session_audio；麦克风启动失败则恢复课节为 done（不残留 recording）。
3. **UI**（`app/ui/main_window.py`）：
   - 中栏新增「▶ 继续录制」按钮（选中已结束课节且空闲时可用）；右键课节菜单加同项；
   - `on_continue()`：确认弹窗 → `recorder.continue_session(sid)` → 课节回到「● 录制中」；
   - 回听升级为多 wav 路由：`_build_audio_map`（单换算器）→ `_build_audio_routes`（[(wav, 起始墙钟)] 按时间排序）；`_play_range` 按 t0 落到对应 wav，跨边界钳到该 wav 末尾；全文对话框双击回听改用 `_audio_routes`；
   - 结束确认文案补充「结束后想补录可点 ▶ 继续录制」。

### ✅ 验收
- `py_compile` 全过；新增 `scripts/smoke_continue_session.py` 无头冒烟全过：resume/max_seq、续录状态机（done→recording→done、可反复续录、cont1/cont2 登记、seq 续编）、btn_continue 可用性、三 wav 路由排序。
- v3 双区冒烟（`smoke_v3_dual_pane.py`）回归全过，未破坏既有功能。

### ⚠️ 说明
- 续录 wav 独立存储（session_{sid}_contN.wav），不做音频拼接——不动原文件、实现安全；回听按墙钟自动路由到对应 wav。
- 导出/计入笔记按 session_id 汇总，续录内容自动并入同一课节。

---

## 2026-09-01（凌晨）— v3 双区架构：英文实时识别流 + 右侧中文译文累积区

### 🎯 用户问题
「我不追求快速的翻译出来，我只需要快速的看到识别的英文字幕，然后中文在另外一个框里面显示，这个框就放所有的已经翻译好的中文」——英文识别与中文译文彻底解耦。

### 🔧 改动
1. **砍掉 partial 预翻**（`app/recorder.py`）：`partial_worker` 不再调 `translate_partial`（DeepSeek 流式取首段），改为 `ui_q.put((en, ""))` 只上屏英文；中文由 `final_worker` 句子定稿后翻译一次。**省一半 API 调用**，partial 不再产生半句烂译文。
2. **主窗口右侧中文译文累积区**（`app/ui/main_window.py`）：
   - split 由 3 栏改 4 栏（课程序/课节/转写/中文译文），`setSizes([150, 220, 560, 320])`；
   - `zh_box` = 只读 `QPlainTextEdit`，定稿句翻译后 `_append_zh` 顺序累积（空行分隔 + 自动滚底）；
   - 排除「（未识别」「[翻译失败]」等无效译文；切换会话/新建时 `_clear_transcript` 同步清空；
   - `_SegmentCard` / `_FullRow`：partial 无中文时隐藏中文行（不留空行），`_FullRow.set_lang` 增加 `_has_zh` 联动。
3. **悬浮字幕适配**（`app/overlay.py`）：`update_partial` 在 zh 恒空时隐藏中文行、不显示孤立省略号；`update_text`/`show_paused` 同步管理中文行可见性；`_relayout` 只按可见行计高。
4. `QPlainTextEdit` 补进 `main_window.py` 的 PySide6.QtWidgets import。

### ✅ 验收
- `py_compile` 全过；新增 `scripts/smoke_v3_dual_pane.py` 无头冒烟全过（4 栏布局 / zh_box 累积滚底 / partial 英文-only / FullRow 空 zh 隐藏 + set_lang 联动 / overlay zh 隐藏与暂停恢复）。

### ⚠️ 说明
- `app/translate.py` 的 `translate_partial` / `_sse_first_chunk` 已无调用方，留作备用不删。
- 效果：英文识别上屏更快（无翻译等待）、中文在右侧按句子顺序永久累积可回看；悬浮字幕 partial 阶段只显英文。

---

## 2026-09-01（深夜）— 质量验证：实时链路翻译 vs 录音整体翻译 对比（session 94）

### 🎯 用户问题
「目前的最终翻译质量对得上最后用录音的整体翻译吗」——验证实时链路逐句翻译 vs 拿录音整体离线转写+翻译能否对上。

### 📊 方法
- 离线侧：`offline_transcribe.py` 对 session_94.wav 做 small+VAD+beam3 精准转写（与实时 precise 同参）→ 540 段 / 3193 词 / 覆盖 0–39:40。
- 实时侧：DB session 94 的 165 段（原文+译文），墙钟→wav 内秒换算。
- 三层对比：① 时间覆盖与暂停识别 ② 词级 WER（60s 桶，Levenshtein）③ 离线全文分 13 块 DeepSeek 整体翻译（同参：SYSTEM_PROMPT / temperature 0.3）vs 实时逐句译文并排对照。
- 新脚本：`scripts/compare_session94.py`（支持 `--no-translate` 只跑本地分析）。

### 🔍 关键发现
1. **暂停识别**：DB 段墙钟出现 2 次 >60s 跳跃（09:30–11:26、11:36–20:24，累计 10:43）。暂停期间 wav 连续录但实时不喂 ASR → 离线转写覆盖暂停段（476 词）而实时无 → 属**预期行为，非丢句**。
2. **恢复后时间戳偏移 ~20s**（实测内容锚点中位数 -19.8s）：暂停恢复重锚定后实时段时间戳整体偏晚。**不校正时恢复后 WER 虚高到 89.2%**；校正后 46.5%，与暂停前 43.8% 同水平 → 实时 ASR 质量前后稳定。
3. **WER**：暂停前 43.8% / 恢复后(校正) 46.5%，合计 45.9%——与 session 93 的 36.0%、92 的 40.1% 同一量级；差异主要来自同音/近音错（small 模型，如 suing/hiring/swimming/shining）。
4. **翻译层**：实时逐句译文 4382 汉字 vs 离线整体译文 4549 汉字（96%）；抽样 4 块并排对照——语义主体一致，离线整体翻译更连贯，实时受 ASR 同音错拖累。

### ✅ 结论
**实时链路最终翻译与「录音整体翻译」主体对得上**。质量差异主要来自 ASR 同音错而非翻译链路本身；翻译链路（逐句 vs 整体）差异体现在连贯性，语义不失真。

### 📦 交付
`data/exports/session_94_offline.json`、`data/exports/session_94_实时vs离线翻译对比报告.md`、`scripts/compare_session94.py`。

---

## 2026-09-01（深夜）— 暂停/恢复后转写区「不再写入」根因修复（UI 滚动跟随）

### 🐛 用户现象

课 3（session 94）暂停 48 分钟后继续：**DB 正常入库（165 段 / 覆盖 wav 100.9%），但主窗口转写区不再显示新内容**——「数据不再写入，可能依旧有入库，但是我看不见老师讲的之前内容」。

### 🔍 排查结论

- 恢复后采集/ASR/翻译/入库全链路均在日志持续出现（21:06:46 起 on_partial/on_final 到 21:26 停止），**无任何丢句、无 Traceback**。
- `seg_finalized`/`partial_ready` 信号连接在 `_on_record` 只连一次、持久有效；暂停/恢复（`_do_pause`/`_do_resume`）只 finalize+reset+重锚定，不清转写区、不断信号。
- **根因：主窗口转写区的滚动跟随判断有 off-by-one 缺陷**——`_add_segment_card` 先 `addItem`（滚动条 `maximum` 立即计入新卡高度 60-100px）再判断 `_transcript_at_bottom()`（`maximum - value < 24`）→ 该条件恒为 False → **新卡 addItem 但视口永不滚动**。暂停前用户盯着底部所以「碰巧正常」；暂停后滚动条停在旧位置，恢复后所有新卡都 addItem 在视口外 → UI 看起来「不再写入」。
- 对照：全文对话框（`_TranscriptDialog._stick`）用的是 **sticky 状态**（`_at_bottom` + `valueChanged` 监听），工作正常——主窗口缺的正是这个。

### 🔧 修复（app/ui/main_window.py）

1. **sticky 滚动状态**：`_transcript_sticky`（初始 True）+ `verticalScrollBar().valueChanged` → `_on_transcript_scrolled` 实时记录「用户是否在底部附近」（`maximum - value < 24`）。
2. **三处滚动改用 sticky 判断**：`_add_segment_card` / `_add_marker_card` / `_upsert_partial` 中 `if self._transcript_sticky: scrollToBottom()`——addItem 前记录状态，规避「addItem 后 maximum 已含新卡高」的判断陷阱。
3. **恢复录制强制回底**：`_on_state` 中 `prev == "paused"` → `_transcript_sticky = True` + `scrollToBottom()`（用户按「继续」= 回到实时字幕）。
4. **`_clear_transcript` 重置 sticky=True**：新会话/切课/加载历史默认回底部；`_load_session` 末尾 `scrollToTop()` 会经 valueChanged 翻转为 False，不影响「看历史不打扰」。
5. 删除废弃的 `_transcript_at_bottom()` 方法。

### ✅ 验证

- `py_compile` 通过；无头冒烟测试 sticky 语义：底部跟随 ✓ / 滚走不打扰 ✓ / 滚回恢复 ✓ / 恢复后新卡持续跟随 ✓。
- 数据层面 session 94 无丢失（165 段覆盖 2404s vs wav 2383s = 100.9%），无需补回。

### ⚠️ 生效方式

GUI 进程跑的还是旧代码——**重启应用**后本修复 + 上轮三件套（final 优先 / join 5s / 启动清理）一并生效。

### 📌 用户拍板（session 93）

**不再补回** session 93 丢失的 18 分钟——关闭该待办，补全方案（离线 478 段回填）作废。

---

### 🐛 根因链（用户报「停止了还在显示录音中」）

`asr_q` 是 `PriorityQueue` 三元组，原设计 **partial 优先级 0 > final 1**。precise 模式下 ASR 变慢（~2s/个），partial 每 1.5s 入队一个 → worker 永远在处理 partial → **final 定稿被饿死积压 209 个** → 停止时 `_finish` 需逐个转写（约 7 分钟）→ 用户等不及强杀进程 → `end_session` 未执行 → DB 卡 `recording` + 尾部 18 分钟内容丢失。

### 🔧 修复三件套

1. **final 优先级反转**（`app/recorder.py`）：`_PRIO_FINAL=0` / `_PRIO_PARTIAL=1`。final 是入库内容，partial 只是实时预览——丢弃后 1.5s 内新 partial 即来，最多字幕跳一帧。注释保留完整教训。
2. **`_finish` 并行短超时**：3 个 worker 并行 `join(timeout=5)`，剩余异步补入（daemon + store 锁安全），保存 5 秒内必完成。
3. **启动自动清理残留**（`app/storage.py` `recover_stale_sessions()` + `main.py` 启动调用）：所有残留 `status='recording'` 统一置 `done`，从根上杜绝「录音中」残留。

### 📊 session 93（IS5113 第 2 节）精准模式实测

- 离线 `small + VAD + beam3`（与 precise 同参）转写完整 wav 24:16 → **478 段全覆盖**（RTF 0.081）。
- 实时链路实际只入库 **74 段、覆盖前 6:14，丢失 18:02 = 74%**（饿死 bug 期间未入库）。
- 重叠区词级 **WER = 36.0%**（接近 session 92 的 40.1% 预期，precise 略优于 realtime）。
- 交付：`data/exports/session_93_precise.json`、`data/exports/session_93_精准补全报告.md`；DB 备份 `subtitle.db.bak_fix93`。

### ⚠️ 待办

- session 94（第 3 节）录制时跑的是旧代码，**结束后必须重启应用**让三项修复生效。（2026-09-01 已重启验证？——见上方「暂停/恢复后不再写入」修复）
- ~~是否将离线 478 段补回 session 93~~ **用户已拍板：不补回**（2026-09-01）。

---

## 2026-09-01 — 回听修复 + 字幕显示重构 + 双识别模式 + 课后精度分析

### 🔧 回听功能（三处修复，之前"点了没声音/从头播"）

1. **墙钟→wav 位置换算**（`app/ui/main_window.py`）
   - 问题：`segments.t_start/t_end` 是墙钟 epoch 秒，直接被当成 wav 内毫秒传给 `setPosition`，超出音频长度数亿倍 → 无声音。
   - 修复：新增 `_build_audio_map(sid)`，读 `sessions.started_at` 解析为 epoch，`wall_t − start_epoch` 即 wav 内秒数。
   - 注意：wav 是连续录音、**暂停时麦克风不停录**（只停 ASR 喂入），所以**不需要扣暂停时长**（最初加了暂停扣除，被合成测试数据推翻）。

2. **wav 永不停止录制**（`app/recorder.py` `_finish()`）
   - 问题：正常结束后不调 `src.stop()` → 流一直开、队列无限增长。实测 session 90（6s 会话 → 883s wav）、session 91（14s → 263s 且 mtime 持续增长）。
   - 修复：`_finish` 在 feed_loop join 之后补 `src.stop()`。

3. **大文件首击回听失效**（`app/ui/main_window.py`）
   - 问题：`setSource` 后立即 `setPosition`，media 未加载时无效 → 首次回听从头播。
   - 修复：`_pending_pos` + 连接 `mediaStatusChanged`，等 `LoadedMedia` 再 seek。

### 🎬 字幕显示重构（"太急促和杂乱"）

- 根因：5s ASR 滑动窗口每 1.5s 重听一次，partial 显示的是**整个 5s 窗的整段重听结果** → 前面的词被滑出窗口消失 + ASR 措辞抖动 → 字幕闪跳。
- 修复（`app/overlay.py`）：句子累积打字机 `_accumulate()`
  - partial 只追加新词、已显词不消失、措辞抖动不闪屏；
  - `difflib.SequenceMatcher` 匹配块 + `matched / min(len)` 阈值 0.5 判断「窗口滑头」vs「内容切换」；
  - final 整句替换为精校版，作为下句累积基准；暂停/恢复重置累积状态。

### ⚙️ 双识别模式（用户拍板：两种功能并存，现状保留）

- `realtime`（默认）：5s 窗 + beam1 + 无 VAD —— 现状，延迟低，脑补稍多。
- `precise`：10s 窗 + beam3 + VAD 滤环境音 —— 更稳更准，延迟 +0.5s。
- 实现：`app/recorder.py` 新增 `asr_mode` 参数与 `_apply_mode()` 注入；设置页新增下拉框（`app/settings.py` DEFAULTS + `app/ui/main_window.py` `_SettingsDialog`）；`app/asr.py` `Transcriber` 支持 `vad` 参数。

### 📊 课后精度分析（session 92，IS5113 第 1 节，39min / 422 段）

- 用户反馈「有时候会多词」→ 三向对比（离线标准原文 vs 实时转写 vs 译文）：
  - **根因在 ASR 层**：误听（`class`→`cars`、`punctual`→`puncture`）+ 环境音脑补（`snitcher`/`canvas`）；翻译是忠实放大器，不编造。
  - 量化：实时多出实义词 477 次/354 词（幻觉密度 12.45%）；实时漏听 1874 次/667 词 —— **漏听比多词严重约 4 倍**。
- A/B 滑窗模拟（300-480s 片段，WER 越低越好）：
  - small 5s 无VAD（现状）= **42.9%**
  - small 5s + VAD = 42.0%
  - **precise（10s+VAD）= 40.1%**（RTF 0.28，实时可行）
  - **medium 10s+VAD = 29.5%**（质变 −13.4pp，但 RTF 0.79 M5 CPU 实时不可行 → 留给课后离线重转）
  - 结论：窗口+VAD 在 small 上提升有限（small 精度天花板 ~40%）。
- 交付：`data/exports/session_92_精度对比报告.md`

### 🧪 新增脚本与测试

- `scripts/offline_transcribe.py`：离线全量转写 wav → 句子级 JSON（16kHz wav → `{start, end, text}`）。
- `scripts/compare_session92.py`：三向对比 + 词频差 + 幻觉候选，输出对比报告。
- `scripts/ab_test.py`：A/B 滑窗 WER 模拟（必须模拟 final 定稿链路 + 定稿周期=窗口大小，否则 WER 假象）。
- `tests/test_overlay_accumulate.py`（11/11 PASS）、`tests/test_overlay_smoke.py`（4/4 PASS）、`tests/test_mainwindow_smoke.py`（2/2 PASS）。

### ⚠️ 待办

- 重启应用后建议在设置里切「精准模式」体验。
- medium 离线重转 session 92（29.5% 精度）待用户确认是否要做。

# Regenerate + Continue 功能 - 测试清单

> **功能版本**：v2.1（补充头像回归测试）
> **更新时间**：2026-04-03
> **测试范围**：后端 API + 前端交互 + 数据库 + 边界情况

---

## 一、数据库验证

### 1.1 Schema 检查
- [ ] `chat_messages` 表包含 `versions` 字段（jsonb，默认 `[]`）
- [ ] **注意**：`versions` 字段只保留最终版本，不做累积存储（每次 regenerate/continue 后覆盖为单条记录）

### 1.2 数据完整性
- [ ] 插入新消息时，`versions` 自动初始化为 `[]`
- [ ] regenerate 后：`versions = [{"content": "新内容", "operation": "regenerate", "created_at": "..."}]`
- [ ] continue 后：`versions = [{"content": "原始+追加完整内容", "operation": "continue", "created_at": "..."}]`

---

## 二、后端 API 测试（Postman / curl）

### 2.1 Regenerate 接口 (`POST /api/chat/regenerate`)

#### 基础功能测试
- [ ] **正常流程**：发送有效 message_id → 返回 SSE 流 → 完成后 content 被替换为新内容
- [ ] **上下文一致性**：regenerate 后 AI 基于用户最新消息生成（不是基于旧 AI 回复）
  - 验证方法：发送用户消息 A → 得到回复 X → 点击 regenerate → 新回复 Y 的内容应围绕消息 A，而非围绕 X
- [ ] **时间排序正确性**：
  - 历史消息按 `ORDER BY created_at ASC, id ASC` 排序（非 UUID 字典序）
  - 连续 assistant 消息（来自 continue）被自动裁剪
- [ ] **SSE 格式验证**：
  ```
  event: chunk → {"type":"chunk","text":"片段"}
  event: done  → {"type":"done","reply":"完整内容","message_id":"uuid","operation":"regenerate","character_state":{...}}
  ```

#### 异常处理测试
- [ ] **404 错误**：message_id 不存在 → `{"detail": "消息不存在或无权操作"}`
- [ ] **权限校验**：使用其他用户的 message_id → 404
- [ ] **角色类型校验**：传入 user 角色的 message_id → 404
- [ ] **未登录访问**：无 Token → 401/403
- [ ] **参数校验**：message_id 缺失或无效 → 422

### 2.2 Continue 接口 (`POST /api/chat/continue`)

#### 基础功能测试
- [ ] **正常流程**：发送有效 message_id → SSE 流式追加 → 数据库 content 更新为拼接后完整内容
- [ ] **双字段返回**：
  - `reply`：原始 + 追加的完整拼接（用于 DB 保存）
  - `appended_text`：仅新增部分（用于前端渲染）
- [ ] **SSE 格式验证**：
  ```
  event: chunk → {"type":"chunk","text":"片段"}
  event: done  → {"type":"done","reply":"完整拼接","appended_text":"仅新增部分","message_id":"uuid","operation":"continue","character_state":{...}}
  ```

#### 特殊逻辑测试
- [ ] **Continue 指令注入**：Prompt 中包含"【请继续】"指令
- [ ] **空回复处理**：AI 返回空内容 → 抛出 error SSE 事件
- [ ] **追加后再次 continue**：可多次 continue，每次在上次结果基础上追加

---

## 三、业务逻辑集成测试

### 3.1 VIP 限额系统 ⭐
- [ ] **Free 用户 regenerate**：消耗 token → 计入每日限额
- [ ] **VIP 用户 continue**：使用 VIP 模型配置（AIFRIEND_VIP_*）
- [ ] **SVIP 用户**：使用 SVIP 配置，更高 token 上限
- [ ] **限额耗尽**：连续 regenerate 直到额度用完 → 返回限额提示
- [ ] **游客模式**：调用 regenerate/continue → 应拒绝（需登录）

### 3.2 好感度系统触发 ⭐
- [ ] **Regenerate 触发好感度**：
  - AI 回复中包含 `[STATE_UPDATE]{"event":"compliment","mood":"warm"}[/STATE_UPDATE]`
  - → 解析并更新 character_states 表
- [ ] **Continue 触发好感度**：追加部分的 STATE_UPDATE 也被解析
- [ ] **三防机制验证**：
  - 同一事件短时间重复触发 → CD 冷却生效
  - 单日累计超过上限（15点）→ Daily Cap 生效

### 3.3 记忆摘要系统
- [ ] **触发摘要**：regenerate/continue 后消息数达到阈值（24条）→ 触发后台摘要生成

---

## 四、前端交互测试

### 4.1 UI 渲染
- [ ] **按钮显示**：AI 消息右侧显示 ↻（重新生成）和 ▶（继续生成）两个圆形按钮
- [ ] **按钮样式**：
  - ↻ 按钮 hover → 紫色高亮 (#8a72ff)
  - ▶ 按钮 hover → 绿色高亮 (#34d399)
  - 两个按钮视觉大小协调（↻ font-size:20px, ▶ font-size:10px + line-height/padding 微调）
- [ ] **移动端适配**⭐：
  - 按钮始终半透明显示（非 hover 才出现）
  - 触摸区域 ≥ 32px × 32px

### 4.2 Regenerate 交互流程
- [ ] **点击 ↻ 按钮**：
  1. 按钮进入 `.loading` 状态（文字变透明，CSS spinner 居中旋转显示在按钮内）
  2. ▶ 按钮同时禁用
  3. **不显示 typing 指示器气泡**（直接在原气泡内流式替换内容）
  4. SSE chunk 到达 → 实时替换原气泡 innerHTML
  5. 完成 → 按钮恢复原样（移除 .loading，恢复图标），显示 Toast
- [ ] **Spinner 居中**：旋转动画在按钮正中央（绝对定位四边拉伸 + margin:auto）

### 4.3 Continue 交互流程
- [ ] **点击 ▶ 按钮**：
  1. 显示 typing 指示器（"..."跳动点）
  2. 隐藏原气泡的操作按钮（display:none）
  3. SSE 首个 chunk 到达时 → **在原气泡下方创建全新的 row + bubble**
  4. 每个 chunk 写入新气泡
  5. 完成 → 使用 `payload.appended_text`（仅新增部分）渲染新气泡
  6. 新气泡有自己独立的 ↻ 和 ▶ 按钮
  7. 原气泡的操作按钮保持隐藏
- [ ] **新气泡不含重复内容**：确认新气泡只显示追加的部分，不是完整拼接内容

### 4.4 并发控制
- [ ] **发送中 / regenerate 中 / continue 中** → 其他操作按钮禁用
- [ ] **isSending 标志位**正确锁定全局状态
- [ ] **快速连点**：100ms 内点击 10 次 → 只有第 1 次生效

### 4.5 错误处理
- [ ] **网络错误**：SSE error 事件 → 显示红色 Toast（3s）
- [ ] **未登录**：点击按钮 → 提示"请先登录"
- [ ] **Continue 错误恢复**：出错时删除新建的新气泡，恢复原按钮显示

---

## 五、边界情况和安全性

### 5.1 数据安全
- [ ] **越权防护**：用户 A 不能 regenerate/continue 用户 B 的消息
- [ ] **SQL 注入**：message_id 参数化查询
- [ ] **XSS 防护**：返回内容经过 escapeHtml 处理

### 5.2 并发场景
- [ ] **同一消息连续操作**：regenerate 完成后才可继续 operate
- [ ] **快速连点**：isSending 保护，只有首次生效
- [ ] **网络中断**：SSE 断开 → 数据库不保存半成品

---

## 六、回归测试（防止破坏主链路）

### 6.1 主聊天流程不受影响
- [ ] **普通发送**：POST /api/chat/stream → 正常工作
- [ ] **历史加载**：GET /api/chat/history → 正确返回
- [ ] **开场白**：首次进聊天 → 不显示操作按钮（message_id 为空）
- [ ] **游客模式**：游客聊天 → 不显示操作按钮

### 6.2 管理后台兼容
- [ ] **查看历史**：admin 后台能正常显示 messages 表
- [ ] **versions 字段**：管理员能看到 JSON 内容

### 6.3 头像系统回归测试 ⭐
- [ ] **Regenerate 后头像显示**：AI 回复重新生成后，头像正确显示且位置不变
- [ ] **Continue 后头像显示**：追加生成的新气泡中，AI 头像正确显示在左侧
- [ ] **头像加载时机**：SSE 流式输出过程中头像已提前渲染完成
- [ ] **用户头像一致性**：用户消息和 AI 消息的头像在整个对话过程中保持一致
- [ ] **头像缓存**：regenerate/continue 操作不会导致重复请求头像资源
- [ ] **移动端头像尺寸**：新气泡中的头像在小屏幕下尺寸适配正常
- [ ] **头像与气泡对齐**：Continue 新建气泡的头像与原气泡垂直对齐

---

## 七、已知限制

### 当前设计决策（有意为之）
1. **无版本历史切换**：只保留最终版本，不支持查看/回退历史版本（简化设计）
2. **无 Swiper 手势滑动**：已移除所有版本切换 UI 代码
3. **Regenerate 无 typing 气泡**：使用按钮内 spinner 替代，更简洁
4. **Continue 使用独立新气泡**：不在原气泡内追回，而是下方新建气泡展示追加内容
5. **不支持批量操作**：一次只能对一条消息执行 regenerate/continue

### 后续可选优化
- [ ] 添加版本历史侧边栏（如需版本回退功能）
- [ ] Undo 功能（一键回退到上一版本）
- [ ] 批量 regenerate（一次处理多条消息）

---

**文档维护说明**：本清单应与代码实现同步更新。当 regenerate/continue 的交互逻辑或数据存储策略发生变化时，及时修订本文档。

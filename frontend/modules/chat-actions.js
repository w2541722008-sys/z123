/** chat-actions.js — Regenerate、Continue 与重试逻辑 */
const ChatActions = ((ChatState) => {
  const R = ChatState.render;
  const S = ChatState.stream;

  /* ── 操作按钮绑定 ───────────────────────────────────── */
  function bindMessageActionButtons(actionBtnsEl, rowEl, bubbleEl, messageId) {
    if (!actionBtnsEl) return;
    if (!messageId) { actionBtnsEl.style.display = 'none'; return; }
    actionBtnsEl.style.opacity = '';
    rowEl.dataset.messageId = messageId;
    actionBtnsEl.querySelector('.regenerate-btn').addEventListener('click', (e) => {
      e.stopPropagation();
      regenerateMessage(messageId, rowEl, bubbleEl);
    });
    actionBtnsEl.querySelector('.continue-btn').addEventListener('click', (e) => {
      e.stopPropagation();
      continueMessage(messageId, rowEl, bubbleEl);
    });
  }

  /* ── Regenerate ─────────────────────────────────────── */
  async function regenerateMessage(messageId, rowEl, bubbleEl) {
    if (ChatState.isSending) return;
    if (!Auth.isLoggedIn()) { UI.toast('请登录后使用', 'warn'); return; }
    const buttons = S.beginMessageAction(rowEl, { loading: 'regenerate' });
    let aiText = '';
    try {
      await API.regenerateMessage(
        { message_id: messageId },
        {
          onChunk(chunk) {
            if (!chunk) return;
            aiText += chunk;
            R.renderMessageBubble(bubbleEl, aiText, true);
            ChatState.scrollToBottom();
          },
          onDone(payload) {
            aiText = payload?.reply || aiText;
            R.renderMessageBubble(bubbleEl, aiText, true);
            S.finalizeAssistantMessageUpdate(messageId, aiText, payload);
          },
          onError() {},
        },
        ChatState.streamController.signal
      );
    } catch (err) {
      UI.toast(`重新生成失败：${err.message}`, 'error');
    } finally {
      S.completeMessageAction(buttons, { loading: 'regenerate' });
    }
  }

  /* ── Continue ───────────────────────────────────────── */
  async function continueMessage(messageId, rowEl, bubbleEl) {
    if (ChatState.isSending) return;
    if (!Auth.isLoggedIn()) { UI.toast('请登录后使用', 'warn'); return; }
    const buttons = S.beginMessageAction(rowEl, { loading: 'continue', showTypingBubble: true, hideActions: true });
    let appendedText = '';
    let newBubbleEl = null;
    let newRowEl = null;
    let newActionBtnsEl = null;
    try {
      await API.continueMessage(
        { message_id: messageId },
        {
          onChunk(chunk) {
            if (!chunk) return;
            R.removeTyping();
            appendedText += chunk;
            if (!newBubbleEl) {
              const continuationRow = S.createContinuationMessageRow(rowEl, messageId, () => appendedText);
              newRowEl = continuationRow.row;
              newBubbleEl = continuationRow.bubble;
              newActionBtnsEl = continuationRow.actionBtns;
            }
            R.renderMessageBubble(newBubbleEl, appendedText, true);
            ChatState.scrollToBottom();
          },
          onDone(payload) {
            const { finalAppended, nextMessageId, fullText } = S.resolveContinuationResult(
              bubbleEl.textContent, appendedText, payload, messageId
            );
            if (newBubbleEl) R.renderMessageBubble(newBubbleEl, finalAppended, true);
            S.finalizeAssistantMessageUpdate(messageId, fullText, payload, nextMessageId);
            bindMessageActionButtons(newActionBtnsEl, newRowEl, newBubbleEl, nextMessageId);
            S.setActionButtonsVisible(buttons.actions, false);
          },
          onError(payload) {
            R.removeTyping();
            R.removeRowIfPresent(newRowEl);
            S.setActionButtonsVisible(buttons.actions, true);
          },
        },
        ChatState.streamController.signal
      );
    } catch (err) {
      R.removeTyping();
      R.removeRowIfPresent(newRowEl);
      UI.toast(`继续生成失败：${err.message}`, 'error');
      S.setActionButtonsVisible(buttons.actions, true);
    } finally {
      S.completeMessageAction(buttons, { loading: 'continue' });
    }
  }

  return { bindMessageActionButtons, regenerateMessage, continueMessage };
});

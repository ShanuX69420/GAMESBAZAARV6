'use client';

import { useState, useEffect, useRef, useCallback } from 'react';
import { useAuth } from '@/lib/auth';
import {
  getChatWebSocketTicket,
  getConversation,
  getConversations,
  startConversation,
  sendImageMessage,
  formatLastActive,
} from '@/lib/api';

const WS_BASE = process.env.NEXT_PUBLIC_WS_URL || 'ws://127.0.0.1:8000';
const MESSAGE_PAGE_SIZE = 50;
const MAX_CHAT_MESSAGE_LENGTH = 2000;

export default function ChatBox({ conversationId, sellerId, sellerName, onConversationStart, compact = false }) {
  const { user } = useAuth();
  const [convo, setConvo] = useState(null);
  const [messages, setMessages] = useState([]);
  const [messagePagination, setMessagePagination] = useState(null);
  const [input, setInput] = useState('');
  const [sending, setSending] = useState(false);
  const [loadingOlder, setLoadingOlder] = useState(false);
  const [activeConvoId, setActiveConvoId] = useState(conversationId);
  const [connected, setConnected] = useState(false);
  const [pendingImage, setPendingImage] = useState(null); // { file, preview }
  const [imageUploading, setImageUploading] = useState(false);
  const [chatError, setChatError] = useState('');
  const messagesContainerRef = useRef(null);
  const messagesEndRef = useRef(null);
  const wsRef = useRef(null);
  const reconnectTimer = useRef(null);
  const errorTimerRef = useRef(null);
  const reconnectAttempts = useRef(0);
  const isNearBottom = useRef(true);
  const loadingOlderRef = useRef(false);
  const mountedRef = useRef(true);
  const fileInputRef = useRef(null);

  function handleScroll() {
    const el = messagesContainerRef.current;
    if (!el) return;
    isNearBottom.current = el.scrollHeight - el.scrollTop - el.clientHeight < 80;
    if (el.scrollTop < 80 && messagePagination?.next_before_id !== null &&
        messagePagination?.next_before_id !== undefined && !loadingOlderRef.current) {
      loadOlderMessages();
    }
  }

  function scrollToBottom(instant = false) {
    const el = messagesContainerRef.current;
    if (!el) return;
    if (instant || isNearBottom.current) {
      el.scrollTop = el.scrollHeight;
    }
  }

  function showChatError(message) {
    setChatError(message);
    clearTimeout(errorTimerRef.current);
    errorTimerRef.current = setTimeout(() => {
      if (mountedRef.current) setChatError('');
    }, 4000);
  }

  // Scroll when messages change (after DOM renders)
  useEffect(() => {
    setTimeout(() => scrollToBottom(), 50);
  }, [messages.length]);

  // On mount: look up existing conversation with seller
  useEffect(() => {
    if (activeConvoId || !sellerId || !user) return;
    getConversations()
      .then(convos => {
        const existing = convos.find(c => c.other_user?.id === sellerId);
        if (existing && mountedRef.current) setActiveConvoId(existing.id);
      })
      .catch(() => {});
  }, [sellerId, user, activeConvoId]);

  // Sync conversationId prop
  useEffect(() => {
    if (conversationId) setActiveConvoId(conversationId);
  }, [conversationId]);

  // Load messages via REST
  const loadMessages = useCallback(async () => {
    if (!activeConvoId) return;
    try {
      const data = await getConversation(activeConvoId, { limit: MESSAGE_PAGE_SIZE });
      if (!mountedRef.current) return;
      setConvo(data);
      setMessages(data.messages || []);
      setMessagePagination(data.message_pagination || null);
      requestAnimationFrame(() => scrollToBottom(true));
    } catch { }
  }, [activeConvoId]);

  // Initial load
  useEffect(() => {
    loadMessages();
  }, [loadMessages]);

  async function loadOlderMessages() {
    if (!activeConvoId || messagePagination?.next_before_id === null ||
        messagePagination?.next_before_id === undefined || loadingOlderRef.current) return;
    const el = messagesContainerRef.current;
    const previousHeight = el?.scrollHeight || 0;
    const previousTop = el?.scrollTop || 0;
    loadingOlderRef.current = true;
    setLoadingOlder(true);
    try {
      const data = await getConversation(activeConvoId, {
        limit: MESSAGE_PAGE_SIZE,
        beforeId: messagePagination.next_before_id,
      });
      if (!mountedRef.current) return;
      setMessages(prev => {
        const existing = new Set(prev.map(m => m.id));
        const older = (data.messages || []).filter(m => !existing.has(m.id));
        return [...older, ...prev];
      });
      setMessagePagination(data.message_pagination || null);
      requestAnimationFrame(() => {
        const nextEl = messagesContainerRef.current;
        if (nextEl) {
          nextEl.scrollTop = nextEl.scrollHeight - previousHeight + previousTop;
        }
      });
    } catch { } finally {
      loadingOlderRef.current = false;
      setLoadingOlder(false);
    }
  }

  // WebSocket with auto-reconnect
  useEffect(() => {
    mountedRef.current = true;
    if (!activeConvoId || !user) return;

    function scheduleReconnect() {
      if (!mountedRef.current) return;
      setConnected(false);
      const delay = Math.min(1000 * Math.pow(2, reconnectAttempts.current), 10000);
      reconnectAttempts.current += 1;
      reconnectTimer.current = setTimeout(() => {
        if (mountedRef.current) {
          loadMessages();
          connectWs();
        }
      }, delay);
    }

    async function connectWs() {
      let ticket;
      try {
        const data = await getChatWebSocketTicket(activeConvoId);
        ticket = data.ticket;
      } catch {
        scheduleReconnect();
        return;
      }
      if (!ticket || !mountedRef.current) return;

      if (wsRef.current) {
        wsRef.current.onclose = null;
        wsRef.current.close();
      }

      const ws = new WebSocket(`${WS_BASE}/ws/chat/${activeConvoId}/?ticket=${encodeURIComponent(ticket)}`);
      wsRef.current = ws;

      ws.onopen = () => {
        if (!mountedRef.current) return;
        setConnected(true);
        reconnectAttempts.current = 0;
        setTimeout(() => window.dispatchEvent(new Event('chatUpdate')), 300);
      };

      ws.onmessage = (e) => {
        if (!mountedRef.current) return;
        try {
          const data = JSON.parse(e.data);
          if (data.type === 'new_message') {
            setMessages(prev => {
              if (prev.some(m => m.id === data.message.id)) return prev;
              return [...prev, data.message];
            });
            setMessagePagination(prev => prev ? { ...prev, count: prev.count + 1 } : prev);
            setChatError('');
            window.dispatchEvent(new Event('chatUpdate'));
          } else if (data.type === 'error') {
            showChatError(data.error || 'Message could not be sent.');
          }
        } catch { }
      };

      ws.onclose = () => {
        scheduleReconnect();
      };

      ws.onerror = () => {};
    }

    connectWs();

    return () => {
      mountedRef.current = false;
      clearTimeout(reconnectTimer.current);
      clearTimeout(errorTimerRef.current);
      if (wsRef.current) {
        wsRef.current.onclose = null;
        wsRef.current.close();
        wsRef.current = null;
      }
    };
  }, [activeConvoId, user, loadMessages]);

  // Handle paste for images
  function handlePaste(e) {
    const items = e.clipboardData?.items;
    if (!items) return;
    for (const item of items) {
      if (item.type.startsWith('image/')) {
        e.preventDefault();
        const file = item.getAsFile();
        if (file) openPreview(file);
        break;
      }
    }
  }

  // Handle file input change
  function handleFileSelect(e) {
    const file = e.target.files?.[0];
    if (file && file.type.startsWith('image/')) {
      openPreview(file);
    }
    e.target.value = ''; // Reset
  }

  function openPreview(file) {
    const preview = URL.createObjectURL(file);
    setPendingImage({ file, preview });
  }

  function cancelPreview() {
    if (pendingImage?.preview) URL.revokeObjectURL(pendingImage.preview);
    setPendingImage(null);
  }

  async function sendImage() {
    if (!pendingImage || !activeConvoId) return;
    setImageUploading(true);
    try {
      const data = await sendImageMessage(activeConvoId, pendingImage.file, '');
      // Add to messages immediately (REST-uploaded, not via WebSocket)
      setMessages(prev => {
        if (prev.some(m => m.id === data.id)) return prev;
        return [...prev, { ...data, is_mine: true }];
      });
      setMessagePagination(prev => prev ? { ...prev, count: prev.count + 1 } : prev);
      window.dispatchEvent(new Event('chatUpdate'));
      cancelPreview();
    } catch (err) {
      alert(err.message || 'Failed to send image');
    } finally {
      setImageUploading(false);
    }
  }

  async function handleSend(e) {
    e.preventDefault();
    if (!input.trim()) return;

    const messageText = input.trim();
    if (messageText.length > MAX_CHAT_MESSAGE_LENGTH) {
      showChatError(`Message cannot be longer than ${MAX_CHAT_MESSAGE_LENGTH} characters.`);
      return;
    }
    setSending(true);
    setInput('');

    try {
      if (!activeConvoId && sellerId) {
        const data = await startConversation(sellerId, messageText);
        setActiveConvoId(data.id);
        setConvo(data);
        setMessages(data.messages || []);
        setMessagePagination(data.message_pagination || null);
        if (onConversationStart) onConversationStart(data.id);
        requestAnimationFrame(() => scrollToBottom(true));
      } else if (wsRef.current && wsRef.current.readyState === WebSocket.OPEN) {
        wsRef.current.send(JSON.stringify({
          type: 'chat_message',
          content: messageText,
        }));
      }
    } catch (err) {
      setInput(messageText);
      showChatError(err.message || 'Message could not be sent.');
    } finally {
      setSending(false);
    }
  }

  // Build grouped messages with date separators
  function renderMessages() {
    const elements = [];
    let lastDate = null;
    let lastSender = null;
    let lastTime = null;

    for (let i = 0; i < messages.length; i++) {
      const msg = messages[i];
      const msgDate = new Date(msg.created_at);
      const dateKey = msgDate.toDateString();

      if (dateKey !== lastDate) {
        elements.push(
          <div key={`date-${dateKey}`} className="chat-date-separator">
            <span>{formatDateSeparator(msgDate)}</span>
          </div>
        );
        lastDate = dateKey;
        lastSender = null;
        lastTime = null;
      }

      const timeDiff = lastTime ? (msgDate - lastTime) / 60000 : Infinity;
      const showHeader = msg.sender_name !== lastSender || timeDiff >= 5;

      elements.push(
        <div key={msg.id} className={`chat-msg-row ${showHeader ? 'with-header' : ''}`}>
          {showHeader && (
            <div className="chat-msg-header">
              <span className="chat-msg-sender">{msg.is_mine ? 'You' : msg.sender_name}</span>
              <span className="chat-msg-time">
                {msgDate.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}
              </span>
            </div>
          )}
          {msg.image_url && (
            <div className="chat-msg-image">
              <img src={msg.image_url} alt="Shared image" onClick={() => window.open(msg.image_url, '_blank')} />
            </div>
          )}
          {msg.content && <div className="chat-msg-content">{msg.content}</div>}
        </div>
      );

      lastSender = msg.sender_name;
      lastTime = msgDate;
    }
    return elements;
  }

  if (!user) {
    return (
      <div className={`chatbox ${compact ? 'chatbox-compact' : ''}`}>
        <div className="chatbox-header">
          <span>💬 Chat with {sellerName || 'Seller'}</span>
        </div>
        <div className="chatbox-empty">
          <a href="/login" className="btn btn-primary btn-sm">Login to chat</a>
        </div>
      </div>
    );
  }

  return (
    <div className={`chatbox ${compact ? 'chatbox-compact' : ''}`}>
      {!compact && (
        <div className="chatbox-header">
          <div className="inbox-avatar" style={{ width: 36, height: 36, fontSize: '0.9rem' }}>
            {(convo?.other_user?.username || sellerName || '?')[0].toUpperCase()}
            {convo?.other_user?.is_online && <span className="online-dot"></span>}
          </div>
          <div>
            <div className="chatbox-header-name">
              <a href={`/seller/${convo?.other_user?.username || sellerName}`} style={{ color: 'inherit', textDecoration: 'none' }}>
                {convo?.other_user?.username || sellerName || 'Chat'}
              </a>
            </div>
            {convo?.other_user?.last_active && (
              <div className={`presence-text ${convo.other_user.is_online ? 'is-online' : ''}`}>
                {formatLastActive(convo.other_user.last_active)}
              </div>
            )}
          </div>
        </div>
      )}

      <div
        className="chatbox-messages"
        ref={messagesContainerRef}
        onScroll={handleScroll}
      >
        {loadingOlder && (
          <div className="chat-loading-older">
            Loading older messages...
          </div>
        )}
        {messages.length === 0 ? (
          <div className="chatbox-empty-msg">
            No messages yet. Say hello!
          </div>
        ) : renderMessages()}
        <div ref={messagesEndRef} />
      </div>

      {/* Image Preview Modal */}
      {pendingImage && (
        <div className="image-preview-overlay" onClick={cancelPreview}>
          <div className="image-preview-modal" onClick={e => e.stopPropagation()}>
            <div className="image-preview-header">
              <span>Send Image</span>
              <button className="image-preview-close" onClick={cancelPreview}>✕</button>
            </div>
            <div className="image-preview-body">
              <img src={pendingImage.preview} alt="Preview" />
            </div>
            <div className="image-preview-footer">
              <button className="btn btn-secondary btn-sm" onClick={cancelPreview} disabled={imageUploading}>
                Cancel
              </button>
              <button className="btn btn-primary btn-sm" onClick={sendImage} disabled={imageUploading}>
                {imageUploading ? 'Sending...' : 'Send'}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Input Area */}
      {chatError && <div className="chatbox-error">{chatError}</div>}
      <form className="chatbox-input" onSubmit={handleSend} onPaste={handlePaste}>
        <input type="hidden" />
        <input
          ref={fileInputRef}
          type="file"
          accept="image/*"
          style={{ display: 'none' }}
          onChange={handleFileSelect}
        />
        <input
          type="text"
          value={input}
          onChange={(e) => setInput(e.target.value)}
          placeholder="Message..."
          maxLength={MAX_CHAT_MESSAGE_LENGTH}
          disabled={sending}
        />
        <button
          type="button"
          className="chatbox-attach-btn"
          onClick={() => fileInputRef.current?.click()}
          title="Attach image"
        >
          <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <path d="M21.44 11.05l-9.19 9.19a6 6 0 01-8.49-8.49l9.19-9.19a4 4 0 015.66 5.66l-9.2 9.19a2 2 0 01-2.83-2.83l8.49-8.48" />
          </svg>
        </button>
        <button type="submit" disabled={sending || !input.trim()}>
          <svg width="20" height="20" viewBox="0 0 24 24" fill="currentColor">
            <path d="M2.01 21L23 12 2.01 3 2 10l15 2-15 2z" />
          </svg>
        </button>
      </form>
    </div>
  );
}

function formatDateSeparator(date) {
  const now = new Date();
  const today = new Date(now.getFullYear(), now.getMonth(), now.getDate());
  const msgDay = new Date(date.getFullYear(), date.getMonth(), date.getDate());
  const diff = (today - msgDay) / 86400000;

  if (diff === 0) return 'Today';
  if (diff === 1) return 'Yesterday';
  return date.toLocaleDateString('en-US', { day: 'numeric', month: 'long' });
}

'use client';

import { useState, useEffect, useRef, useCallback } from 'react';
import { useAuth } from '@/lib/auth';
import { getConversation, getConversations, startConversation } from '@/lib/api';

const WS_BASE = process.env.NEXT_PUBLIC_WS_URL || 'ws://127.0.0.1:8000';

export default function ChatBox({ conversationId, sellerId, sellerName, onConversationStart, compact = false }) {
  const { user } = useAuth();
  const [convo, setConvo] = useState(null);
  const [messages, setMessages] = useState([]);
  const [input, setInput] = useState('');
  const [sending, setSending] = useState(false);
  const [activeConvoId, setActiveConvoId] = useState(conversationId);
  const [connected, setConnected] = useState(false);
  const messagesEndRef = useRef(null);
  const messagesContainerRef = useRef(null);
  const wsRef = useRef(null);
  const isNearBottom = useRef(true);

  // Track scroll position
  function handleScroll() {
    const el = messagesContainerRef.current;
    if (!el) return;
    isNearBottom.current = el.scrollHeight - el.scrollTop - el.clientHeight < 80;
  }

  function scrollToBottom(instant = false) {
    const el = messagesContainerRef.current;
    if (!el) return;
    if (instant) {
      el.scrollTop = el.scrollHeight;
    } else if (isNearBottom.current) {
      el.scrollTop = el.scrollHeight;
    }
  }

  // On mount: look up existing conversation with seller
  useEffect(() => {
    if (activeConvoId || !sellerId || !user) return;
    getConversations()
      .then(convos => {
        const existing = convos.find(c => c.other_user?.id === sellerId);
        if (existing) setActiveConvoId(existing.id);
      })
      .catch(() => {});
  }, [sellerId, user, activeConvoId]);

  // Sync conversationId prop
  useEffect(() => {
    if (conversationId) setActiveConvoId(conversationId);
  }, [conversationId]);

  // Load initial messages via REST (once), then WebSocket takes over
  useEffect(() => {
    if (!activeConvoId) return;
    getConversation(activeConvoId)
      .then(data => {
        setConvo(data);
        setMessages(data.messages || []);
        // Instant scroll on first load
        requestAnimationFrame(() => {
          const el = messagesContainerRef.current;
          if (el) el.scrollTop = el.scrollHeight;
        });
      })
      .catch(() => {});
  }, [activeConvoId]);

  // WebSocket connection
  useEffect(() => {
    if (!activeConvoId || !user) return;

    const token = localStorage.getItem('gb_access_token');
    if (!token) return;

    const ws = new WebSocket(`${WS_BASE}/ws/chat/${activeConvoId}/?token=${token}`);
    wsRef.current = ws;

    ws.onopen = () => {
      setConnected(true);
    };

    ws.onmessage = (e) => {
      const data = JSON.parse(e.data);
      if (data.type === 'new_message') {
        setMessages(prev => {
          // Avoid duplicates
          if (prev.some(m => m.id === data.message.id)) return prev;
          return [...prev, data.message];
        });
        // Scroll for new messages
        requestAnimationFrame(() => scrollToBottom());
      }
    };

    ws.onclose = () => {
      setConnected(false);
    };

    ws.onerror = () => {
      setConnected(false);
    };

    return () => {
      ws.close();
      wsRef.current = null;
    };
  }, [activeConvoId, user]);

  async function handleSend(e) {
    e.preventDefault();
    if (!input.trim()) return;

    const messageText = input.trim();
    setSending(true);
    setInput('');

    try {
      // If no conversation yet, start via REST, then WebSocket will connect
      if (!activeConvoId && sellerId) {
        const data = await startConversation(sellerId, messageText);
        setActiveConvoId(data.id);
        setConvo(data);
        setMessages(data.messages || []);
        if (onConversationStart) onConversationStart(data.id);
        requestAnimationFrame(() => {
          const el = messagesContainerRef.current;
          if (el) el.scrollTop = el.scrollHeight;
        });
      } else if (wsRef.current && wsRef.current.readyState === WebSocket.OPEN) {
        // Send via WebSocket — consumer will save & broadcast back
        wsRef.current.send(JSON.stringify({
          type: 'chat_message',
          content: messageText,
        }));
      }
    } catch (err) {
      setInput(messageText);
    } finally {
      setSending(false);
    }
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
          <span>💬 {convo?.other_user?.username || sellerName || 'Chat'}</span>
          {activeConvoId && (
            <span className={`ws-indicator ${connected ? 'online' : 'offline'}`}></span>
          )}
        </div>
      )}

      <div
        className="chatbox-messages"
        ref={messagesContainerRef}
        onScroll={handleScroll}
      >
        {messages.length === 0 ? (
          <div className="chatbox-empty-msg">
            No messages yet. Say hello!
          </div>
        ) : (
          messages.map((msg) => (
            <div
              key={msg.id}
              className={`chat-msg ${msg.is_mine ? 'mine' : 'theirs'}`}
            >
              <div className="chat-msg-bubble">
                {msg.content}
              </div>
              <div className="chat-msg-time">
                {new Date(msg.created_at).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}
              </div>
            </div>
          ))
        )}
        <div ref={messagesEndRef} />
      </div>

      <form className="chatbox-input" onSubmit={handleSend}>
        <input
          type="text"
          value={input}
          onChange={(e) => setInput(e.target.value)}
          placeholder="Type a message..."
          disabled={sending}
        />
        <button type="submit" disabled={sending || !input.trim()}>
          ➤
        </button>
      </form>
    </div>
  );
}

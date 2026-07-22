'use client';

import { useState, useEffect, useRef, useCallback } from 'react';
import { useAuth } from '@/lib/auth';
import { WS_BASE } from '@/lib/config';
import {
  getChatWebSocketTicket,
  getConversation,
  getConversations,
  startConversation,
  sendMessage,
  sendImageMessage,
  formatLastActive,
  isOnlineFromLastActive,
} from '@/lib/api';
import { resetMessageSoundCooldown } from '@/lib/messageAlerts';
import Linkified from '@/components/Linkified';

const MESSAGE_PAGE_SIZE = 50;
const MAX_CHAT_MESSAGE_LENGTH = 2000;
const CHAT_SUBPROTOCOL = 'gb.chat';
const PRESENCE_TICK_MS = 30000;

// Turn the order number and participant usernames inside a system notice
// into links (order page / seller profiles).
function renderSystemText(content, orderInfo) {
  if (!content || !orderInfo) return content;
  const links = {};
  if (orderInfo.order_number) {
    links[`#${orderInfo.order_number}`] = `/order/${encodeURIComponent(orderInfo.order_number)}`;
  }
  for (const username of [orderInfo.buyer_username, orderInfo.seller_username]) {
    if (username) links[username] = `/seller/${encodeURIComponent(username)}`;
  }
  const tokens = Object.keys(links).sort((a, b) => b.length - a.length);
  if (!tokens.length) return content;
  const escaped = tokens.map(t => t.replace(/[.*+?^${}()|[\]\\]/g, '\\$&'));
  const splitter = new RegExp(`(${escaped.join('|')})`, 'g');
  return content.split(splitter).map((part, i) =>
    links[part]
      ? <a key={i} href={links[part]} className="chat-event-link">{part}</a>
      : part
  );
}

// Sender names in message headers link to the user's public profile;
// 'You' and the GamesBazaar platform label stay plain text.
function renderSenderName(label) {
  if (!label || label === 'You' || label === 'GamesBazaar') return label;
  return (
    <a href={`/seller/${encodeURIComponent(label)}`} className="chat-msg-sender-link">
      {label}
    </a>
  );
}

function encodeWebSocketTicket(ticket) {
  return btoa(ticket).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '');
}

export default function ChatBox({
  conversationId,
  sellerId,
  sellerName,
  sellerAvatarUrl,
  sellerLastActive,
  onConversationStart,
  compact = false,
  listingId,
  listingTitle,
  listingPrice,
  onOrderEvent,
}) {
  const { user } = useAuth();
  const [convo, setConvo] = useState(null);
  const [messages, setMessages] = useState([]);
  const [messagePagination, setMessagePagination] = useState(null);
  const [input, setInput] = useState('');
  const [sending, setSending] = useState(false);
  const [loadingMessages, setLoadingMessages] = useState(true);
  const [loadingOlder, setLoadingOlder] = useState(false);
  const [activeConvoId, setActiveConvoId] = useState(conversationId);
  const [connected, setConnected] = useState(false);
  const [pendingImage, setPendingImage] = useState(null); // { file, preview }
  const [imageUploading, setImageUploading] = useState(false);
  const [lightboxUrl, setLightboxUrl] = useState(null);
  const [chatError, setChatError] = useState('');
  const [presenceNow, setPresenceNow] = useState(() => Date.now());
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
  const inputRef = useRef(null);
  const initialImageAutoScrollRef = useRef(false);
  const pendingInitialImageLoadsRef = useRef(0);
  const initialImageScrollTimerRef = useRef(null);
  const [listingContextSent, setListingContextSent] = useState(false);
  const onOrderEventRef = useRef(onOrderEvent);
  onOrderEventRef.current = onOrderEvent;

  // Auto-grow the message box as lines are added (Shift+Enter), reset after send.
  useEffect(() => {
    const el = inputRef.current;
    if (!el) return;
    el.style.height = 'auto';
    el.style.height = `${Math.min(el.scrollHeight, 120)}px`;
  }, [input]);


  function handleScroll() {
    const el = messagesContainerRef.current;
    if (!el) return;
    isNearBottom.current = el.scrollHeight - el.scrollTop - el.clientHeight < 80;
    if (el.scrollTop < 80 && messagePagination?.next_before_id !== null &&
        messagePagination?.next_before_id !== undefined && !loadingOlderRef.current) {
      loadOlderMessages();
    }
  }

  useEffect(() => {
    const interval = setInterval(() => setPresenceNow(Date.now()), PRESENCE_TICK_MS);
    const handleVisibilityChange = () => {
      if (document.visibilityState === 'visible') setPresenceNow(Date.now());
    };
    document.addEventListener('visibilitychange', handleVisibilityChange);
    return () => {
      clearInterval(interval);
      document.removeEventListener('visibilitychange', handleVisibilityChange);
    };
  }, []);

  function scrollToBottom(instant = false) {
    const el = messagesContainerRef.current;
    if (!el) return;
    if (instant || isNearBottom.current) {
      el.scrollTop = el.scrollHeight;
    }
  }

  function stopInitialImageAutoScroll() {
    initialImageAutoScrollRef.current = false;
    pendingInitialImageLoadsRef.current = 0;
    clearTimeout(initialImageScrollTimerRef.current);
  }

  function armInitialImageAutoScroll(nextMessages) {
    clearTimeout(initialImageScrollTimerRef.current);
    const imageCount = (nextMessages || []).filter(msg => msg.image_url).length;
    pendingInitialImageLoadsRef.current = imageCount;
    initialImageAutoScrollRef.current = imageCount > 0;

    requestAnimationFrame(() => scrollToBottom(true));
    setTimeout(() => scrollToBottom(true), 80);
    setTimeout(() => scrollToBottom(true), 350);

    if (imageCount > 0) {
      initialImageScrollTimerRef.current = setTimeout(() => {
        stopInitialImageAutoScroll();
      }, 8000);
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
    if (loadingOlderRef.current) return;
    const firstScroll = setTimeout(() => scrollToBottom(), 50);
    // Secondary scroll to catch images that finish loading after the first scroll
    const secondScroll = setTimeout(() => scrollToBottom(), 300);
    return () => {
      clearTimeout(firstScroll);
      clearTimeout(secondScroll);
    };
  }, [messages.length]);

  // Re-scroll image loads only while opening a conversation or when the user
  // was already parked at the newest message.
  function handleImageLoad() {
    if (initialImageAutoScrollRef.current) {
      scrollToBottom(true);
      pendingInitialImageLoadsRef.current -= 1;
      if (pendingInitialImageLoadsRef.current <= 0) {
        stopInitialImageAutoScroll();
      }
      return;
    }
    if (loadingOlderRef.current || !isNearBottom.current) return;
    scrollToBottom();
  }

  // On mount: look up existing conversation with seller
  useEffect(() => {
    if (activeConvoId || !sellerId || !user) return;
    let cancelled = false;
    setLoadingMessages(true);

    getConversations({ otherUserId: sellerId, limit: 1 })
      .then(data => {
        if (cancelled || !mountedRef.current) return;
        const convos = data.conversations || data;
        const existing = convos.find(c => c.other_user?.id === sellerId);
        if (existing) {
          setActiveConvoId(existing.id);
        } else {
          setLoadingMessages(false);
        }
      })
      .catch(() => {
        if (!cancelled && mountedRef.current) setLoadingMessages(false);
      });

    return () => {
      cancelled = true;
    };
  }, [sellerId, user, activeConvoId]);

  // Sync conversationId prop
  useEffect(() => {
    if (conversationId) {
      setActiveConvoId(conversationId);
      setMessages([]);
      setLoadingMessages(true);
    }
  }, [conversationId]);

  // Load messages via REST. `silent` refreshes in place (no skeleton, no
  // forced scroll) — used to catch up after a reconnect.
  const loadMessages = useCallback(async ({ silent = false } = {}) => {
    if (!activeConvoId) return;
    if (!silent) setLoadingMessages(true);
    try {
      const data = await getConversation(activeConvoId, { limit: MESSAGE_PAGE_SIZE });
      if (!mountedRef.current) return;
      const nextMessages = data.messages || [];
      setConvo(data);
      setMessages(nextMessages);
      setMessagePagination(data.message_pagination || null);
      if (!silent) armInitialImageAutoScroll(nextMessages);
    } catch { } finally {
      if (mountedRef.current && !silent) setLoadingMessages(false);
    }
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
    // Per-run liveness flag: unlike mountedRef (which the next effect run
    // sets back to true), this stays false once this run is torn down, so
    // stale async connects and orphaned retry timers can't resurrect.
    let disposed = false;

    function scheduleReconnect() {
      if (disposed) return;
      setConnected(false);
      // Replace any pending retry so reconnect loops can't multiply
      clearTimeout(reconnectTimer.current);
      const delay = Math.min(1000 * Math.pow(2, reconnectAttempts.current), 10000);
      reconnectAttempts.current += 1;
      reconnectTimer.current = setTimeout(() => {
        if (!disposed) connectWs();
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
      if (!ticket || disposed) return;

      if (wsRef.current) {
        wsRef.current.onclose = null;
        wsRef.current.close();
      }

      const ticketProtocol = `gb.ticket.${encodeWebSocketTicket(ticket)}`;
      const ws = new WebSocket(`${WS_BASE}/ws/chat/${activeConvoId}/`, [
        CHAT_SUBPROTOCOL,
        ticketProtocol,
      ]);
      wsRef.current = ws;

      ws.onopen = () => {
        if (disposed) return;
        clearTimeout(reconnectTimer.current);
        setConnected(true);
        // Connecting marks the conversation read server-side; treat it as
        // caught up so its next incoming message dings again.
        resetMessageSoundCooldown(activeConvoId);
        if (reconnectAttempts.current > 0) {
          // Catch up quietly on messages and order events missed while
          // offline — no skeleton, no scroll jump.
          loadMessages({ silent: true });
          if (onOrderEventRef.current) onOrderEventRef.current(null);
        }
        reconnectAttempts.current = 0;
        setTimeout(() => window.dispatchEvent(new Event('chatUpdate')), 300);
      };

      ws.onmessage = (e) => {
        if (disposed) return;
        try {
          const data = JSON.parse(e.data);
          if (data.type === 'new_message') {
            if (
              data.message.is_mine &&
              data.message.listing_reference?.id === Number(listingId)
            ) {
              setListingContextSent(true);
            }
            setMessages(prev => {
              if (prev.some(m => m.id === data.message.id)) return prev;
              return [...prev, data.message];
            });
            setMessagePagination(prev => prev ? { ...prev, count: prev.count + 1 } : prev);
            setChatError('');
            // Messages landing in an open chat are auto-read by the server,
            // so keep the sound cooldown reset while the user watches.
            if (!data.message.is_mine) resetMessageSoundCooldown(activeConvoId);
            window.dispatchEvent(new Event('chatUpdate'));
            if (
              onOrderEventRef.current &&
              (data.message.message_type === 'system' || data.message.message_type === 'delivery')
            ) {
              onOrderEventRef.current(data.message);
            }
          } else if (data.type === 'presence') {
            // Server pushes the other participant's fresh last_active —
            // replaces the old 30s polling.
            setConvo(prev => {
              if (!prev?.other_user || prev.other_user.id !== data.user_id) return prev;
              return { ...prev, other_user: { ...prev.other_user, last_active: data.last_active } };
            });
            setPresenceNow(Date.now());
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
      disposed = true;
      mountedRef.current = false;
      clearTimeout(reconnectTimer.current);
      clearTimeout(errorTimerRef.current);
      clearTimeout(initialImageScrollTimerRef.current);
      if (wsRef.current) {
        wsRef.current.onclose = null;
        wsRef.current.close();
        wsRef.current = null;
      }
    };
  }, [activeConvoId, user, loadMessages, listingId]);

  // Close the image lightbox with Escape
  useEffect(() => {
    if (!lightboxUrl) return;
    function handleKeyDown(e) {
      if (e.key === 'Escape') setLightboxUrl(null);
    }
    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [lightboxUrl]);

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
      requestAnimationFrame(() => scrollToBottom(true));
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

    const rawText = input.trim();
    const messageListingId = listingId && !listingContextSent ? listingId : null;
    if (rawText.length > MAX_CHAT_MESSAGE_LENGTH) {
      showChatError(`Message cannot be longer than ${MAX_CHAT_MESSAGE_LENGTH} characters.`);
      return;
    }
    setSending(true);
    setInput('');

    try {
      if (!activeConvoId && sellerId) {
        const data = await startConversation(sellerId, rawText, messageListingId);
        setActiveConvoId(data.id);
        setConvo(data);
        const nextMessages = data.messages || [];
        setMessages(nextMessages);
        setMessagePagination(data.message_pagination || null);
        if (onConversationStart) onConversationStart(data.id);
        armInitialImageAutoScroll(nextMessages);
        if (messageListingId) setListingContextSent(true);
      } else if (wsRef.current && wsRef.current.readyState === WebSocket.OPEN) {
        wsRef.current.send(JSON.stringify({
          type: 'chat_message',
          content: rawText,
          ...(messageListingId ? { listing_id: messageListingId } : {}),
        }));
      } else if (activeConvoId) {
        const data = await sendMessage(activeConvoId, rawText, messageListingId);
        setMessages(prev => {
          if (prev.some(m => m.id === data.id)) return prev;
          return [...prev, { ...data, is_mine: true }];
        });
        setMessagePagination(prev => prev ? { ...prev, count: prev.count + 1 } : prev);
        window.dispatchEvent(new Event('chatUpdate'));
        if (messageListingId && data.listing_reference) setListingContextSent(true);
      } else {
        setInput(rawText);
        showChatError('Chat is still connecting. Please try again.');
      }
    } catch (err) {
      setInput(rawText);
      showChatError(err.message || 'Message could not be sent.');
    } finally {
      setSending(false);
    }
  }

  function renderSpecialMessage(msg, msgDate) {
    const time = msgDate.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });

    if (msg.message_type === 'system') {
      if (msg.system_event === 'guard_code') {
        // Codes read as a plain message from the seller, even though the
        // stored sender is the buyer (kept that way for unread badging).
        const guardSeller = msg.order_info?.seller_username;
        return (
          <div key={msg.id} className="chat-msg-row with-header">
            <div className="chat-msg-header">
              <span className="chat-msg-sender">
                {renderSenderName(guardSeller === user?.username ? 'You' : (guardSeller || 'GamesBazaar'))}
              </span>
              <span className="chat-msg-time">{time}</span>
            </div>
            <div className="chat-msg-content"><Linkified text={msg.content} /></div>
          </div>
        );
      }
      return (
        <div key={msg.id} className="chat-msg-row with-header chat-event-row">
          <div className="chat-msg-header">
            <span className="chat-msg-sender chat-event-brand">
              GamesBazaar <span className="chat-badge chat-badge-system">order update</span>
            </span>
            <span className="chat-msg-time">{time}</span>
          </div>
          <div className={`chat-event-card chat-event-${msg.system_event || 'generic'}`}>
            <div className="chat-event-text">{renderSystemText(msg.content, msg.order_info)}</div>
          </div>
        </div>
      );
    }

    const senderLabel = msg.is_mine ? 'You' : (msg.sender_name || 'GamesBazaar');

    if (msg.message_type === 'delivery') {
      return (
        <div key={msg.id} className="chat-msg-row with-header">
          <div className="chat-msg-header">
            <span className="chat-msg-sender">
              {renderSenderName(senderLabel)} <span className="chat-badge chat-badge-delivery">delivery</span>
            </span>
            <span className="chat-msg-time">{time}</span>
          </div>
          <div className="chat-msg-content"><Linkified text={msg.content} /></div>
        </div>
      );
    }

    // message_type === 'instructions'
    return (
      <div key={msg.id} className="chat-msg-row with-header">
        <div className="chat-msg-header">
          <span className="chat-msg-sender">
            {renderSenderName(senderLabel)} <span className="chat-badge chat-badge-instructions">instructions</span>
          </span>
          <span className="chat-msg-time">{time}</span>
        </div>
        <div className="chat-msg-content"><Linkified text={msg.content} /></div>
      </div>
    );
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

      if (msg.message_type && msg.message_type !== 'text') {
        elements.push(renderSpecialMessage(msg, msgDate));
        // Force the next regular message to re-render its own header
        lastSender = null;
        lastTime = msgDate;
        continue;
      }

      const timeDiff = lastTime ? (msgDate - lastTime) / 60000 : Infinity;
      const showHeader = msg.sender_name !== lastSender || timeDiff >= 5;

      elements.push(
        <div key={msg.id} className={`chat-msg-row ${showHeader ? 'with-header' : ''}`}>
          {showHeader && (
            <div className="chat-msg-header">
              <span className="chat-msg-sender">{renderSenderName(msg.is_mine ? 'You' : msg.sender_name)}</span>
              <span className="chat-msg-time">
                {msgDate.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}
              </span>
            </div>
          )}
          {msg.image_url && (
            <div className="chat-msg-image">
              <img
                src={msg.image_url}
                alt="Shared image"
                loading="lazy"
                onLoad={handleImageLoad}
                onError={handleImageLoad}
                onClick={() => setLightboxUrl(msg.image_url)}
              />
            </div>
          )}
          {msg.listing_reference && (
            <div className="chat-msg-listing-ref">
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                <path d="M20.59 13.41l-7.17 7.17a2 2 0 01-2.83 0L2 12V2h10l8.59 8.59a2 2 0 010 2.82z"/>
                <line x1="7" y1="7" x2="7.01" y2="7"/>
              </svg>
              <span className="chat-msg-listing-ref-title">{msg.listing_reference.title}</span>
              <span className="chat-msg-listing-ref-price">PKR {msg.listing_reference.price}</span>
            </div>
          )}
          {msg.content && <div className="chat-msg-content"><Linkified text={msg.content} /></div>}
        </div>
      );

      lastSender = msg.sender_name;
      lastTime = msgDate;
    }
    return elements;
  }

  const chatHeaderName = convo?.other_user?.username || sellerName || 'Seller';
  const chatHeaderAvatarUrl = convo?.other_user?.avatar_url || sellerAvatarUrl;
  const chatHeaderLastActive = convo?.other_user?.last_active || sellerLastActive;
  const chatHeaderIsOnline = isOnlineFromLastActive(chatHeaderLastActive, presenceNow);

  if (!user) {
    return (
      <div className={`chatbox ${compact ? 'chatbox-compact' : ''}`}>
        <div className="chatbox-header">
          <span>Chat with {sellerName || 'Seller'}</span>
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
            <img src={chatHeaderAvatarUrl || '/avatar-default.svg'} alt={chatHeaderName} style={{ width: '100%', height: '100%', objectFit: 'cover', borderRadius: '50%' }} />
            {chatHeaderIsOnline && <span className="online-dot"></span>}
          </div>
          <div>
            <div className="chatbox-header-name">
              <a href={`/seller/${chatHeaderName}`} style={{ color: 'inherit', textDecoration: 'none' }}>
                {chatHeaderName}
              </a>
            </div>
            {chatHeaderLastActive && (
              <div className={`presence-text ${chatHeaderIsOnline ? 'is-online' : ''}`}>
                {formatLastActive(chatHeaderLastActive)}
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
        {loadingMessages ? (
          <div className="chat-skeleton-loader">
            <div className="chat-skeleton-row">
              <div className="chat-skeleton-avatar"></div>
              <div className="chat-skeleton-lines">
                <div className="chat-skeleton-line" style={{ width: '40%' }}></div>
                <div className="chat-skeleton-line" style={{ width: '70%' }}></div>
              </div>
            </div>
            <div className="chat-skeleton-row right">
              <div className="chat-skeleton-lines">
                <div className="chat-skeleton-line" style={{ width: '30%', marginLeft: 'auto' }}></div>
                <div className="chat-skeleton-line" style={{ width: '55%', marginLeft: 'auto' }}></div>
              </div>
            </div>
            <div className="chat-skeleton-row">
              <div className="chat-skeleton-avatar"></div>
              <div className="chat-skeleton-lines">
                <div className="chat-skeleton-line" style={{ width: '50%' }}></div>
                <div className="chat-skeleton-line" style={{ width: '80%' }}></div>
                <div className="chat-skeleton-line" style={{ width: '35%' }}></div>
              </div>
            </div>
            <div className="chat-skeleton-row right">
              <div className="chat-skeleton-lines">
                <div className="chat-skeleton-line" style={{ width: '45%', marginLeft: 'auto' }}></div>
              </div>
            </div>
            <p className="chat-skeleton-label">Loading messages…</p>
          </div>
        ) : messages.length === 0 ? (
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
              <button className="image-preview-close" onClick={cancelPreview} aria-label="Close">✕</button>
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

      {/* Image Lightbox — view a sent/received image full size */}
      {lightboxUrl && (
        <div className="chat-image-lightbox" onClick={() => setLightboxUrl(null)}>
          <button className="chat-image-lightbox-close" onClick={() => setLightboxUrl(null)} aria-label="Close">✕</button>
          <img src={lightboxUrl} alt="Shared image" onClick={e => e.stopPropagation()} />
        </div>
      )}

      {/* Input Area */}
      {chatError && <div className="chatbox-error">{chatError}</div>}

      {/* Listing context banner — shown when messaging from a listing page */}
      {listingId && listingTitle && !listingContextSent && (
        <div className="chat-listing-context">
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <path d="M20.59 13.41l-7.17 7.17a2 2 0 01-2.83 0L2 12V2h10l8.59 8.59a2 2 0 010 2.82z"/>
            <line x1="7" y1="7" x2="7.01" y2="7"/>
          </svg>
          <span className="chat-listing-context-text">
            Messaging about: <strong>{listingTitle}</strong>
            {listingPrice && <span className="chat-listing-context-price"> — PKR {listingPrice}</span>}
          </span>
        </div>
      )}

      <form className="chatbox-input" onSubmit={handleSend} onPaste={handlePaste}>
        <input type="hidden" />
        <input
          ref={fileInputRef}
          type="file"
          accept="image/*"
          style={{ display: 'none' }}
          onChange={handleFileSelect}
        />
        <textarea
          ref={inputRef}
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === 'Enter' && !e.shiftKey) {
              e.preventDefault();
              handleSend(e);
            }
          }}
          placeholder="Message..."
          maxLength={MAX_CHAT_MESSAGE_LENGTH}
          disabled={sending}
          rows={1}
        />
        <button
          type="button"
          className="chatbox-attach-btn"
          onClick={() => fileInputRef.current?.click()}
          title="Attach image"
          aria-label="Attach image"
        >
          <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <path d="M21.44 11.05l-9.19 9.19a6 6 0 01-8.49-8.49l9.19-9.19a4 4 0 015.66 5.66l-9.2 9.19a2 2 0 01-2.83-2.83l8.49-8.48" />
          </svg>
        </button>
        <button type="submit" disabled={sending || !input.trim()} aria-label="Send message">
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

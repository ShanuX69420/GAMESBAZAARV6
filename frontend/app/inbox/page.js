'use client';

import { useState, useEffect, useCallback, useRef } from 'react';
import { useRouter } from 'next/navigation';
import { useAuth } from '@/lib/auth';
import {
  getConversations,
  getInboxWebSocketTicket,
  formatLastActive,
  isOnlineFromLastActive,
} from '@/lib/api';
import { WS_BASE } from '@/lib/config';
import {
  buildTicketSubprotocols,
  sortConversationsByActivity,
  upsertConversation,
  applyPresenceToConversations,
} from '@/lib/inbox';
import ChatBox from '@/components/ChatBox';

const CONVERSATION_PAGE_SIZE = 30;
const PRESENCE_TICK_MS = 30000;

export default function InboxPage() {
  const { user, loading: authLoading } = useAuth();
  const router = useRouter();
  const [conversations, setConversations] = useState([]);
  const [conversationPagination, setConversationPagination] = useState(null);
  const [loading, setLoading] = useState(true);
  const [loadingMore, setLoadingMore] = useState(false);
  const [activeChatId, setActiveChatId] = useState(null);
  const [mobileChatOpen, setMobileChatOpen] = useState(false);
  const [presenceNow, setPresenceNow] = useState(() => Date.now());
  const loadedLimitRef = useRef(CONVERSATION_PAGE_SIZE);
  const activeChatIdRef = useRef(null);
  activeChatIdRef.current = activeChatId;

  useEffect(() => {
    if (!authLoading && !user) router.push('/login');
  }, [user, authLoading, router]);

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

  const fetchConvos = useCallback(() => {
    if (!user) return;
    getConversations({ limit: loadedLimitRef.current })
      .then(data => {
        const nextConversations = data.conversations || data;
        setConversations(sortConversationsByActivity(nextConversations));
        setConversationPagination(data.pagination || null);
      })
      .catch(() => {})
      .finally(() => setLoading(false));
  }, [user]);

  async function loadMoreConversations() {
    if (!conversationPagination?.next_offset || loadingMore) return;
    setLoadingMore(true);
    try {
      const data = await getConversations({
        limit: CONVERSATION_PAGE_SIZE,
        offset: conversationPagination.next_offset,
      });
      const nextConversations = data.conversations || [];
      setConversations(prev => {
        const byId = new Map(prev.map(convo => [convo.id, convo]));
        nextConversations.forEach(convo => byId.set(convo.id, convo));
        const merged = sortConversationsByActivity([...byId.values()]);
        loadedLimitRef.current = Math.max(
          CONVERSATION_PAGE_SIZE,
          data.pagination?.next_offset ?? merged.length
        );
        return merged;
      });
      setConversationPagination(data.pagination || null);
    } catch {
    } finally {
      setLoadingMore(false);
    }
  }

  // Initial load + full refetch when the tab becomes visible again
  // (fallback for anything missed while hidden).
  useEffect(() => {
    if (!user) return;
    fetchConvos();
    const handleVisible = () => {
      if (document.visibilityState === 'visible') fetchConvos();
    };
    document.addEventListener('visibilitychange', handleVisible);
    return () => document.removeEventListener('visibilitychange', handleVisible);
  }, [user, fetchConvos]);

  // Per-user inbox socket: the server pushes "conversation updated" and
  // presence events, replacing the old 10s full-list polling.
  useEffect(() => {
    if (!user) return;
    let disposed = false;
    let ws = null;
    let reconnectTimer = null;
    let reconnectAttempts = 0;

    function scheduleReconnect() {
      if (disposed) return;
      // Replace any pending retry so reconnect loops can't multiply
      clearTimeout(reconnectTimer);
      const delay = Math.min(1000 * Math.pow(2, reconnectAttempts), 10000);
      reconnectAttempts += 1;
      reconnectTimer = setTimeout(() => {
        if (!disposed) connectWs();
      }, delay);
    }

    async function applyConversationUpdate(conversationId, otherUserId) {
      if (!otherUserId) {
        fetchConvos();
        return;
      }
      try {
        const data = await getConversations({ otherUserId, limit: 1 });
        const updated = (data.conversations || []).find(convo => convo.id === conversationId);
        if (disposed) return;
        if (!updated) {
          fetchConvos();
          return;
        }
        // ChatBox auto-marks the open conversation read; don't flash a badge
        if (updated.id === activeChatIdRef.current) updated.unread_count = 0;
        setConversations(prev => upsertConversation(prev, updated));
      } catch { }
    }

    async function connectWs() {
      let ticket;
      try {
        ({ ticket } = await getInboxWebSocketTicket());
      } catch {
        scheduleReconnect();
        return;
      }
      if (!ticket || disposed) return;

      ws = new WebSocket(`${WS_BASE}/ws/inbox/`, buildTicketSubprotocols(ticket));

      ws.onopen = () => {
        if (disposed) return;
        clearTimeout(reconnectTimer);
        // Catch up on anything missed while disconnected
        if (reconnectAttempts > 0) fetchConvos();
        reconnectAttempts = 0;
      };

      ws.onmessage = (e) => {
        if (disposed) return;
        try {
          const data = JSON.parse(e.data);
          if (data.type === 'conversation_updated') {
            applyConversationUpdate(data.conversation_id, data.other_user_id);
          } else if (data.type === 'presence') {
            setConversations(prev =>
              applyPresenceToConversations(prev, data.user_id, data.last_active)
            );
            setPresenceNow(Date.now());
          }
        } catch { }
      };

      ws.onclose = () => scheduleReconnect();
      ws.onerror = () => {};
    }

    connectWs();

    return () => {
      disposed = true;
      clearTimeout(reconnectTimer);
      if (ws) {
        ws.onclose = null;
        ws.close();
      }
    };
  }, [user, fetchConvos]);

  // Derive activeChat from latest conversations data (always fresh)
  const activeChat = conversations.find(c => c.id === activeChatId) || null;

  function selectConversation(convo) {
    setActiveChatId(convo.id);
    setMobileChatOpen(true);
    // ChatBox marks the conversation read once it connects; mirror that here
    // instead of waiting for the next server push.
    if (convo.unread_count > 0) {
      setConversations(prev =>
        prev.map(c => (c.id === convo.id ? { ...c, unread_count: 0 } : c))
      );
    }
  }

  function handleBackToList() {
    setMobileChatOpen(false);
  }

  if (authLoading || !user) {
    return (
      <div className="container">
        <div className="loading"><div className="loading-spinner"></div> Loading...</div>
      </div>
    );
  }

  return (
    <div className="container">
      <div className="page-header" style={{ paddingBottom: '16px' }}>
        <h1 className="page-title">Messages</h1>
      </div>

      {loading ? (
        <div className="loading"><div className="loading-spinner"></div> Loading...</div>
      ) : conversations.length === 0 ? (
        <div className="empty-state">
          <div className="empty-state-icon">💬</div>
          <p>No conversations yet. Start chatting from a listing page!</p>
        </div>
      ) : (
        <div className={`inbox-split ${mobileChatOpen ? 'mobile-chat-open' : ''}`}>
          <div className="inbox-sidebar">
            {conversations.map((convo) => (
              <div
                key={convo.id}
                className={`inbox-item ${activeChatId === convo.id ? 'active' : ''}`}
                onClick={() => selectConversation(convo)}
              >
                <div className="inbox-avatar">
                  {convo.other_user?.avatar_url ? (
                    <img src={convo.other_user.avatar_url} alt={convo.other_user.username} loading="lazy" style={{ width: '100%', height: '100%', objectFit: 'cover', borderRadius: '50%' }} />
                  ) : (
                    convo.other_user?.username?.[0]?.toUpperCase() || '?'
                  )}
                  {isOnlineFromLastActive(convo.other_user?.last_active, presenceNow) && <span className="online-dot"></span>}
                </div>
                <div className="inbox-info">
                  <div className="inbox-name">
                    {convo.other_user?.username || 'Unknown'}
                    {convo.unread_count > 0 && (
                      <span className="inbox-unread-badge">{convo.unread_count}</span>
                    )}
                  </div>
                  <div className="inbox-preview">
                    {convo.last_message ? (
                      <>
                        <span className="inbox-sender">
                          {!convo.last_message.sender_name
                            ? 'GamesBazaar'
                            : convo.last_message.sender_name === user.username
                              ? 'You'
                              : convo.last_message.sender_name}:
                        </span>{' '}
                        {convo.last_message.content}
                      </>
                    ) : 'No messages yet'}
                  </div>
                </div>
                <div className="inbox-time">
                  {convo.last_message
                    ? formatTime(convo.last_message.created_at)
                    : formatTime(convo.updated_at)}
                </div>
              </div>
            ))}
            {conversationPagination?.next_offset !== null &&
              conversationPagination?.next_offset !== undefined && (
                <button
                  type="button"
                  className="btn btn-outline btn-full"
                  style={{ margin: '12px' }}
                  onClick={loadMoreConversations}
                  disabled={loadingMore}
                >
                  {loadingMore ? 'Loading...' : 'Load More'}
                </button>
              )}
          </div>

          <div className="inbox-chatpanel">
            {activeChat ? (
              <>
                <div className="inbox-chat-header">
                  <button className="inbox-back-btn" onClick={handleBackToList} aria-label="Back to conversations">
                    ←
                  </button>
                  <div className="inbox-avatar" style={{ width: 36, height: 36, fontSize: '0.9rem' }}>
                    {activeChat.other_user?.avatar_url ? (
                      <img src={activeChat.other_user.avatar_url} alt={activeChat.other_user.username} loading="lazy" style={{ width: '100%', height: '100%', objectFit: 'cover', borderRadius: '50%' }} />
                    ) : (
                      activeChat.other_user?.username?.[0]?.toUpperCase() || '?'
                    )}
                    {isOnlineFromLastActive(activeChat.other_user?.last_active, presenceNow) && <span className="online-dot"></span>}
                  </div>
                  <div>
                    <div style={{ fontWeight: 600, fontSize: '0.95rem' }}>
                      <a href={`/seller/${activeChat.other_user?.username}`} style={{ color: 'inherit', textDecoration: 'none' }}>
                        {activeChat.other_user?.username}
                      </a>
                    </div>
                    <div className={`presence-text ${isOnlineFromLastActive(activeChat.other_user?.last_active, presenceNow) ? 'is-online' : ''}`}>
                      {formatLastActive(activeChat.other_user?.last_active)}
                    </div>
                  </div>
                </div>
                <ChatBox
                  key={activeChatId}
                  conversationId={activeChatId}
                  compact={true}
                />
              </>
            ) : (
              <div className="inbox-chat-empty">
                <div className="empty-state-icon">💬</div>
                <p>Select a conversation to start chatting</p>
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
}

function formatTime(dateStr) {
  const date = new Date(dateStr);
  const now = new Date();
  const diff = now - date;
  if (diff < 60000) return 'Just now';
  if (diff < 3600000) return `${Math.floor(diff / 60000)}m`;
  if (diff < 86400000) return `${Math.floor(diff / 3600000)}h`;
  return date.toLocaleDateString();
}

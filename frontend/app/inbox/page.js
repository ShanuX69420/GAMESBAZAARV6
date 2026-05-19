'use client';

import { useState, useEffect, useCallback, useRef } from 'react';
import { useRouter } from 'next/navigation';
import { useAuth } from '@/lib/auth';
import { getConversations, formatLastActive } from '@/lib/api';
import ChatBox from '@/components/ChatBox';

const CONVERSATION_PAGE_SIZE = 30;

export default function InboxPage() {
  const { user, loading: authLoading } = useAuth();
  const router = useRouter();
  const [conversations, setConversations] = useState([]);
  const [conversationPagination, setConversationPagination] = useState(null);
  const [loading, setLoading] = useState(true);
  const [loadingMore, setLoadingMore] = useState(false);
  const [activeChatId, setActiveChatId] = useState(null);
  const [mobileChatOpen, setMobileChatOpen] = useState(false);
  const loadedLimitRef = useRef(CONVERSATION_PAGE_SIZE);

  useEffect(() => {
    if (!authLoading && !user) router.push('/login');
  }, [user, authLoading, router]);

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

  useEffect(() => {
    if (!user) return;
    fetchConvos();
    // Poll every 10s for presence updates + fallback for messages
    const interval = setInterval(fetchConvos, 10000);
    const handleChatUpdate = () => fetchConvos();
    window.addEventListener('chatUpdate', handleChatUpdate);
    return () => {
      clearInterval(interval);
      window.removeEventListener('chatUpdate', handleChatUpdate);
    };
  }, [user, fetchConvos]);

  // Derive activeChat from latest conversations data (always fresh)
  const activeChat = conversations.find(c => c.id === activeChatId) || null;

  function selectConversation(convo) {
    setActiveChatId(convo.id);
    setMobileChatOpen(true);
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
                  {convo.other_user?.is_online && <span className="online-dot"></span>}
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
                          {convo.last_message.sender_name === user.username ? 'You' : convo.last_message.sender_name}:
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
                    {activeChat.other_user?.is_online && <span className="online-dot"></span>}
                  </div>
                  <div>
                    <div style={{ fontWeight: 600, fontSize: '0.95rem' }}>
                      <a href={`/seller/${activeChat.other_user?.username}`} style={{ color: 'inherit', textDecoration: 'none' }}>
                        {activeChat.other_user?.username}
                      </a>
                    </div>
                    <div className={`presence-text ${activeChat.other_user?.is_online ? 'is-online' : ''}`}>
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

function sortConversationsByActivity(conversations) {
  return [...conversations].sort((a, b) => {
    const aDate = new Date(a.last_message?.created_at || a.updated_at).getTime();
    const bDate = new Date(b.last_message?.created_at || b.updated_at).getTime();
    return bDate - aDate;
  });
}

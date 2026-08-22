'use client';

import { useState, useEffect, useCallback, useRef } from 'react';
import { useRouter } from 'next/navigation';
import { useAuth } from '@/lib/auth';
import { getConversations } from '@/lib/api';
import { sortConversationsByActivity } from '@/lib/inbox';
import ChatBox from '@/components/ChatBox';

const CONVERSATION_PAGE_SIZE = 30;
const CONVERSATION_POLL_MS = 10000;

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
  const activeChatIdRef = useRef(null);
  activeChatIdRef.current = activeChatId;
  const pushedChatHistoryRef = useRef(false);

  // Mobile fullscreen chat: lock the page scroll behind the overlay.
  useEffect(() => {
    document.body.classList.toggle('gb-mobile-chat-open', mobileChatOpen);
    return () => document.body.classList.remove('gb-mobile-chat-open');
  }, [mobileChatOpen]);

  // iOS never shrinks the layout viewport when the on-screen keyboard opens —
  // it scrolls the visible area instead, which slides the fullscreen chat's
  // pinned input upwards and exposes the conversation list underneath it.
  // Publish the visual viewport's size and offset so the overlay can sit
  // exactly on the visible rectangle. (On Android interactiveWidget:
  // 'resizes-content' already shrinks the layout viewport, so these values
  // simply match it and nothing changes.)
  useEffect(() => {
    const vv = window.visualViewport;
    if (!mobileChatOpen || !vv) return;
    const root = document.documentElement;
    let frame = 0;

    function sync() {
      cancelAnimationFrame(frame);
      frame = requestAnimationFrame(() => {
        root.style.setProperty('--gb-chat-vv-height', `${vv.height}px`);
        root.style.setProperty('--gb-chat-vv-top', `${vv.offsetTop}px`);
      });
    }

    sync();
    vv.addEventListener('resize', sync);
    vv.addEventListener('scroll', sync);
    return () => {
      cancelAnimationFrame(frame);
      vv.removeEventListener('resize', sync);
      vv.removeEventListener('scroll', sync);
      root.style.removeProperty('--gb-chat-vv-height');
      root.style.removeProperty('--gb-chat-vv-top');
    };
  }, [mobileChatOpen]);

  // The phone's back button should close the fullscreen chat, not leave the
  // inbox — opening a chat on mobile pushes a history entry, popping it (back
  // button or our back arrow) closes the chat.
  useEffect(() => {
    function handlePopState() {
      pushedChatHistoryRef.current = false;
      setMobileChatOpen(false);
    }
    window.addEventListener('popstate', handlePopState);
    return () => window.removeEventListener('popstate', handlePopState);
  }, []);

  useEffect(() => {
    if (!authLoading && !user) router.push('/login');
  }, [user, authLoading, router]);

  const fetchConvos = useCallback(() => {
    if (!user) return;
    getConversations({ limit: loadedLimitRef.current })
      .then(data => {
        const nextConversations = (data.conversations || data).map(convo =>
          // ChatBox auto-marks the open conversation read; don't flash a badge.
          convo.id === activeChatIdRef.current ? { ...convo, unread_count: 0 } : convo
        );
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

  // Initial load, then poll the list while the tab is visible (plus a full
  // refetch when the tab becomes visible again to catch anything missed).
  useEffect(() => {
    if (!user) return;
    fetchConvos();
    const interval = setInterval(() => {
      if (document.visibilityState === 'visible') fetchConvos();
    }, CONVERSATION_POLL_MS);
    const handleVisible = () => {
      if (document.visibilityState === 'visible') fetchConvos();
    };
    document.addEventListener('visibilitychange', handleVisible);
    return () => {
      clearInterval(interval);
      document.removeEventListener('visibilitychange', handleVisible);
    };
  }, [user, fetchConvos]);

  // Derive activeChat from latest conversations data (always fresh)
  const activeChat = conversations.find(c => c.id === activeChatId) || null;

  function selectConversation(convo) {
    setActiveChatId(convo.id);
    setMobileChatOpen(true);
    if (window.matchMedia('(max-width: 768px)').matches && !pushedChatHistoryRef.current) {
      window.history.pushState({ gbInboxChat: true }, '');
      pushedChatHistoryRef.current = true;
    }
    // ChatBox marks the conversation read once it connects; mirror that here
    // instead of waiting for the next server push.
    if (convo.unread_count > 0) {
      setConversations(prev =>
        prev.map(c => (c.id === convo.id ? { ...c, unread_count: 0 } : c))
      );
    }
  }

  function handleBackToList() {
    if (pushedChatHistoryRef.current) {
      window.history.back();
    } else {
      setMobileChatOpen(false);
    }
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
          <p>No messages yet. Order updates and deliveries will appear here.</p>
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
                  <img src={convo.other_user?.avatar_url || '/avatar-default.svg'} alt={convo.other_user?.username || ''} loading="lazy" style={{ width: '100%', height: '100%', objectFit: 'cover', borderRadius: '50%' }} />
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
                    <img src={activeChat.other_user?.avatar_url || '/avatar-default.svg'} alt={activeChat.other_user?.username || ''} loading="lazy" style={{ width: '100%', height: '100%', objectFit: 'cover', borderRadius: '50%' }} />
                  </div>
                  <div>
                    <div style={{ fontWeight: 600, fontSize: '0.95rem' }}>
                      {activeChat.other_user?.username}
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

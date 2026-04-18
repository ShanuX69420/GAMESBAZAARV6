'use client';

import { useState, useEffect, useRef } from 'react';
import { useRouter } from 'next/navigation';
import { useAuth } from '@/lib/auth';
import { getConversations } from '@/lib/api';
import ChatBox from '@/components/ChatBox';

export default function InboxPage() {
  const { user, loading: authLoading } = useAuth();
  const router = useRouter();
  const [conversations, setConversations] = useState([]);
  const [loading, setLoading] = useState(true);
  const [activeChat, setActiveChat] = useState(null);
  const [mobileChatOpen, setMobileChatOpen] = useState(false);

  useEffect(() => {
    if (!authLoading && !user) router.push('/login');
  }, [user, authLoading, router]);

  // Poll conversations — NEVER auto-select, just update the list
  useEffect(() => {
    if (!user) return;
    const fetchConvos = () => {
      getConversations()
        .then(setConversations)
        .catch(() => {})
        .finally(() => setLoading(false));
    };
    fetchConvos();
    const interval = setInterval(fetchConvos, 5000);
    return () => clearInterval(interval);
  }, [user]);

  function selectConversation(convo) {
    setActiveChat(convo);
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
        <h1 className="page-title">💬 Messages</h1>
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
          {/* Left panel: conversation list */}
          <div className="inbox-sidebar">
            {conversations.map((convo) => (
              <div
                key={convo.id}
                className={`inbox-item ${activeChat?.id === convo.id ? 'active' : ''}`}
                onClick={() => selectConversation(convo)}
              >
                <div className="inbox-avatar">
                  {convo.other_user?.username?.[0]?.toUpperCase() || '?'}
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
          </div>

          {/* Right panel: active chat */}
          <div className="inbox-chatpanel">
            {activeChat ? (
              <>
                <div className="inbox-chat-header">
                  <button className="inbox-back-btn" onClick={handleBackToList}>
                    ←
                  </button>
                  <div className="inbox-avatar" style={{ width: 36, height: 36, fontSize: '0.9rem' }}>
                    {activeChat.other_user?.username?.[0]?.toUpperCase() || '?'}
                  </div>
                  <div style={{ fontWeight: 600, fontSize: '0.95rem' }}>
                    {activeChat.other_user?.username}
                  </div>
                </div>
                <ChatBox
                  key={activeChat.id}
                  conversationId={activeChat.id}
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

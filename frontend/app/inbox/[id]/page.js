'use client';

import { useParams } from 'next/navigation';
import { useEffect } from 'react';
import { useRouter } from 'next/navigation';
import { useAuth } from '@/lib/auth';
import ChatBox from '@/components/ChatBox';

export default function ConversationPage() {
  const params = useParams();
  const { id } = params;
  const { user, loading } = useAuth();
  const router = useRouter();

  useEffect(() => {
    if (!loading && !user) router.push('/login');
  }, [user, loading, router]);

  if (loading || !user) {
    return (
      <div className="container">
        <div className="loading"><div className="loading-spinner"></div> Loading...</div>
      </div>
    );
  }

  return (
    <div className="container">
      <div className="page-header">
        <div className="breadcrumb">
          <a href="/inbox">Messages</a>
          <span className="breadcrumb-sep">›</span>
          <span>Conversation</span>
        </div>
      </div>

      <div className="conversation-page">
        <ChatBox conversationId={parseInt(id)} />
      </div>
    </div>
  );
}

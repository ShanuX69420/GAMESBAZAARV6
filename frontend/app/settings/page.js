'use client';

import { useState, useRef, useCallback, useEffect } from 'react';
import { useRouter } from 'next/navigation';
import { useAuth } from '@/lib/auth';
import { updateProfile, changePassword, uploadAvatar, removeAvatar, requestEmailChange, confirmEmailChange } from '@/lib/api';

export default function SettingsPage() {
  const { user, loading, fetchUser } = useAuth();
  const router = useRouter();

  // Username form
  const [username, setUsername] = useState('');
  const [profileSaving, setProfileSaving] = useState(false);
  const [profileMsg, setProfileMsg] = useState(null);

  // Email change flow
  const [newEmail, setNewEmail] = useState('');
  const [emailStep, setEmailStep] = useState('idle'); // idle | pending | verify
  const [emailToken, setEmailToken] = useState('');
  const [emailCurrentCode, setEmailCurrentCode] = useState('');
  const [emailNewCode, setEmailNewCode] = useState('');
  const [emailSaving, setEmailSaving] = useState(false);
  const [emailMsg, setEmailMsg] = useState(null);

  // Password form
  const [currentPassword, setCurrentPassword] = useState('');
  const [newPassword, setNewPassword] = useState('');
  const [newPassword2, setNewPassword2] = useState('');
  const [passwordSaving, setPasswordSaving] = useState(false);
  const [passwordMsg, setPasswordMsg] = useState(null);
  const [showCurrentPw, setShowCurrentPw] = useState(false);
  const [showNewPw, setShowNewPw] = useState(false);

  // Avatar
  const [avatarUploading, setAvatarUploading] = useState(false);
  const [avatarMsg, setAvatarMsg] = useState(null);
  const [avatarPreview, setAvatarPreview] = useState(null);
  const [pendingAvatarFile, setPendingAvatarFile] = useState(null);
  const [dragOver, setDragOver] = useState(false);
  const fileInputRef = useRef(null);

  const [activeTab, setActiveTab] = useState('profile');

  useEffect(() => { if (!loading && !user) router.push('/login'); }, [user, loading, router]);
  useEffect(() => {
    if (user) {
      setUsername(user.username || '');
      setAvatarPreview(user.avatar_url || null);
      setPendingAvatarFile(null);
    }
  }, [user]);

  // ── Username cooldown helper ──
  function getUsernameCooldown() {
    if (!user?.username_changed_at) return null;
    const changed = new Date(user.username_changed_at);
    const now = new Date();
    const daysSince = Math.floor((now - changed) / (1000 * 60 * 60 * 24));
    const remaining = 90 - daysSince;
    return remaining > 0 ? remaining : null;
  }

  // ── Avatar handlers ──
  const handleAvatarFile = useCallback((file) => {
    if (!file) return;
    if (!file.type.startsWith('image/')) { setAvatarMsg({ type: 'error', text: 'Please select an image file.' }); return; }
    if (file.size > 5 * 1024 * 1024) { setAvatarMsg({ type: 'error', text: 'Image too large. Max 5MB.' }); return; }
    const reader = new FileReader();
    reader.onload = (e) => setAvatarPreview(e.target.result);
    reader.readAsDataURL(file);
    setPendingAvatarFile(file);
    setAvatarMsg(null);
  }, []);

  const handleConfirmUpload = async () => {
    if (!pendingAvatarFile) return;
    setAvatarUploading(true); setAvatarMsg(null);
    try {
      await uploadAvatar(pendingAvatarFile);
      await fetchUser();
      setPendingAvatarFile(null);
      setAvatarMsg({ type: 'success', text: 'Profile picture updated!' });
    } catch (err) {
      setAvatarMsg({ type: 'error', text: err.message });
      setAvatarPreview(user?.avatar_url || null);
      setPendingAvatarFile(null);
    } finally { setAvatarUploading(false); }
  };

  const handleCancelPreview = () => {
    setAvatarPreview(user?.avatar_url || null);
    setPendingAvatarFile(null); setAvatarMsg(null);
    if (fileInputRef.current) fileInputRef.current.value = '';
  };

  const handleRemoveAvatar = async () => {
    setAvatarUploading(true); setAvatarMsg(null);
    try {
      await removeAvatar(); await fetchUser();
      setAvatarPreview(null); setPendingAvatarFile(null);
      setAvatarMsg({ type: 'success', text: 'Profile picture removed.' });
    } catch (err) { setAvatarMsg({ type: 'error', text: err.message }); }
    finally { setAvatarUploading(false); }
  };

  const handleDrop = useCallback((e) => { e.preventDefault(); setDragOver(false); const f = e.dataTransfer?.files?.[0]; if (f) handleAvatarFile(f); }, [handleAvatarFile]);

  // ── Username save ──
  const handleProfileSave = async (e) => {
    e.preventDefault();
    if (username === user.username) { setProfileMsg({ type: 'info', text: 'No changes to save.' }); return; }
    setProfileSaving(true); setProfileMsg(null);
    try {
      await updateProfile({ username });
      await fetchUser();
      setProfileMsg({ type: 'success', text: 'Username updated!' });
    } catch (err) { setProfileMsg({ type: 'error', text: err.message }); }
    finally { setProfileSaving(false); }
  };

  // ── Email change step 1: request code ──
  const handleRequestEmailChange = async (e) => {
    e.preventDefault();
    if (!newEmail.trim()) return;
    setEmailSaving(true); setEmailMsg(null);
    try {
      const data = await requestEmailChange(newEmail.trim());
      setEmailToken(data.token);
      setEmailStep('verify');
      setEmailMsg({ type: 'success', text: 'Verification codes sent to both email addresses.' });
    } catch (err) { setEmailMsg({ type: 'error', text: err.message }); }
    finally { setEmailSaving(false); }
  };

  // ── Email change step 2: verify code ──
  const handleConfirmEmailChange = async (e) => {
    e.preventDefault();
    if (emailCurrentCode.length !== 6 || emailNewCode.length !== 6) { setEmailMsg({ type: 'error', text: 'Enter both 6-digit codes.' }); return; }
    setEmailSaving(true); setEmailMsg(null);
    try {
      await confirmEmailChange(emailToken, emailCurrentCode.trim(), emailNewCode.trim());
      await fetchUser();
      setEmailStep('idle'); setNewEmail(''); setEmailCurrentCode(''); setEmailNewCode(''); setEmailToken('');
      setEmailMsg({ type: 'success', text: 'Email updated successfully!' });
    } catch (err) { setEmailMsg({ type: 'error', text: err.message }); }
    finally { setEmailSaving(false); }
  };

  const handleCancelEmailChange = () => {
    setEmailStep('idle'); setNewEmail(''); setEmailCurrentCode(''); setEmailNewCode(''); setEmailToken(''); setEmailMsg(null);
  };

  // ── Password change ──
  const handlePasswordChange = async (e) => {
    e.preventDefault();
    if (newPassword !== newPassword2) { setPasswordMsg({ type: 'error', text: 'New passwords do not match.' }); return; }
    setPasswordSaving(true); setPasswordMsg(null);
    try {
      await changePassword(currentPassword, newPassword, newPassword2);
      await fetchUser();
      setCurrentPassword(''); setNewPassword(''); setNewPassword2('');
      setPasswordMsg({ type: 'success', text: 'Password changed successfully!' });
    } catch (err) { setPasswordMsg({ type: 'error', text: err.message }); }
    finally { setPasswordSaving(false); }
  };

  if (loading) return (
    <div className="settings-page container">
      <div className="settings-loading"><div className="settings-loading-spinner"></div><p>Loading settings...</p></div>
    </div>
  );
  if (!user) return null;

  const memberSince = user.date_joined ? new Date(user.date_joined).toLocaleDateString('en-US', { month: 'long', year: 'numeric' }) : '';
  const cooldownDays = getUsernameCooldown();

  return (
    <div className="settings-page container">
      <div className="settings-header">
        <h1>Account Settings</h1>
        <p className="settings-subtitle">Manage your profile, security, and preferences</p>
      </div>

      <div className="settings-layout">
        {/* Sidebar */}
        <nav className="settings-sidebar">
          <div className="settings-sidebar-profile">
            <div className="settings-sidebar-avatar">
              <img src={avatarPreview || '/avatar-default.svg'} alt={user.username} />
            </div>
            <div className="settings-sidebar-info">
              <div className="settings-sidebar-name">{user.username}</div>
              <div className="settings-sidebar-email">{user.email}</div>
            </div>
          </div>
          <div className="settings-sidebar-nav">
            {['profile', 'security'].map(tab => (
              <button key={tab} className={`settings-nav-item ${activeTab === tab ? 'settings-nav-active' : ''}`} onClick={() => setActiveTab(tab)}>
                {tab === 'profile' ? (
                  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" width="18" height="18"><path d="M20 21v-2a4 4 0 00-4-4H8a4 4 0 00-4 4v2" strokeLinecap="round" strokeLinejoin="round"/><circle cx="12" cy="7" r="4"/></svg>
                ) : (
                  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" width="18" height="18"><rect x="3" y="11" width="18" height="11" rx="2" ry="2"/><path d="M7 11V7a5 5 0 0110 0v4" strokeLinecap="round" strokeLinejoin="round"/></svg>
                )}
                {tab.charAt(0).toUpperCase() + tab.slice(1)}
              </button>
            ))}
          </div>
          {memberSince && (
            <div className="settings-sidebar-member">
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" width="14" height="14"><circle cx="12" cy="12" r="10"/><path d="M12 6v6l4 2" strokeLinecap="round" strokeLinejoin="round"/></svg>
              Member since {memberSince}
            </div>
          )}
        </nav>

        {/* Content */}
        <div className="settings-content">
          {activeTab === 'profile' && (
            <>
              {/* Avatar */}
              <section className="settings-section">
                <div className="settings-section-header"><div><h2>Profile Picture</h2><p className="settings-section-desc">Upload a photo to personalize your account</p></div></div>
                <div className="settings-avatar-area">
                  <div className={`settings-avatar-dropzone ${dragOver ? 'settings-avatar-dragover' : ''} ${avatarUploading ? 'settings-avatar-uploading' : ''}`}
                    onDrop={handleDrop} onDragOver={(e) => { e.preventDefault(); setDragOver(true); }} onDragLeave={() => setDragOver(false)}
                    onClick={() => fileInputRef.current?.click()}>
                    <div className="settings-avatar-large">
                      <img src={avatarPreview || '/avatar-default.svg'} alt={user.username} />
                      {avatarUploading && <div className="settings-avatar-overlay"><div className="settings-avatar-spinner"></div></div>}
                      <div className="settings-avatar-edit-badge">
                        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" width="14" height="14"><path d="M23 19a2 2 0 01-2 2H3a2 2 0 01-2-2V8a2 2 0 012-2h4l2-3h6l2 3h4a2 2 0 012 2z"/><circle cx="12" cy="13" r="4"/></svg>
                      </div>
                    </div>
                    <div className="settings-avatar-text">
                      <p className="settings-avatar-cta"><span className="settings-avatar-link">Click to upload</span> or drag and drop</p>
                      <p className="settings-avatar-hint">JPG, PNG or WebP. Max 5MB</p>
                    </div>
                  </div>
                  <input ref={fileInputRef} type="file" accept="image/jpeg,image/png,image/webp" className="settings-avatar-input" onChange={(e) => handleAvatarFile(e.target.files?.[0])} />
                  {pendingAvatarFile && (
                    <div className="settings-avatar-confirm">
                      <button className="settings-btn-primary" onClick={handleConfirmUpload} disabled={avatarUploading}>
                        {avatarUploading ? <><span className="settings-btn-spinner"></span>Uploading...</> : 'Upload Photo'}
                      </button>
                      <button className="settings-btn-secondary" onClick={handleCancelPreview} disabled={avatarUploading}>Cancel</button>
                    </div>
                  )}
                  {!pendingAvatarFile && avatarPreview && (
                    <button className="settings-avatar-remove" onClick={(e) => { e.stopPropagation(); handleRemoveAvatar(); }} disabled={avatarUploading}>
                      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" width="14" height="14"><path d="M3 6h18M19 6v14a2 2 0 01-2 2H7a2 2 0 01-2-2V6m3 0V4a2 2 0 012-2h4a2 2 0 012 2v2"/></svg>
                      Remove photo
                    </button>
                  )}
                </div>
                {avatarMsg && <div className={`settings-msg settings-msg-${avatarMsg.type}`} style={{ margin: '0 24px 16px' }}>{avatarMsg.text}</div>}
              </section>

              {/* Username */}
              <section className="settings-section">
                <div className="settings-section-header">
                  <div><h2>Username</h2><p className="settings-section-desc">You can change your username once every 90 days</p></div>
                  {cooldownDays && (
                    <div className="settings-section-badge">
                      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" width="14" height="14"><circle cx="12" cy="12" r="10"/><path d="M12 6v6l4 2"/></svg>
                      {cooldownDays}d remaining
                    </div>
                  )}
                </div>
                <form onSubmit={handleProfileSave} className="settings-form">
                  <div className="settings-form-group">
                    <label htmlFor="settings-username" className="settings-label">Username</label>
                    <div className="settings-input-wrapper">
                      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" width="16" height="16" className="settings-input-icon"><path d="M20 21v-2a4 4 0 00-4-4H8a4 4 0 00-4 4v2"/><circle cx="12" cy="7" r="4"/></svg>
                      <input id="settings-username" type="text" value={username} onChange={(e) => setUsername(e.target.value)} className="settings-input" required disabled={!!cooldownDays} />
                    </div>
                    {cooldownDays && <p className="settings-field-hint">You can change your username again in {cooldownDays} days.</p>}
                  </div>
                  {profileMsg && <div className={`settings-msg settings-msg-${profileMsg.type}`}>{profileMsg.text}</div>}
                  <div className="settings-form-actions">
                    <button type="button" className="settings-btn-secondary" onClick={() => { setUsername(user.username); setProfileMsg(null); }}>Cancel</button>
                    <button type="submit" className="settings-btn-primary" disabled={profileSaving || !!cooldownDays || username === user.username}>
                      {profileSaving ? <><span className="settings-btn-spinner"></span>Saving...</> : 'Save Username'}
                    </button>
                  </div>
                </form>
              </section>

              {/* Email */}
              <section className="settings-section">
                <div className="settings-section-header">
                  <div><h2>Email Address</h2><p className="settings-section-desc">A verification code will be sent to your current email</p></div>
                  <div className="settings-section-badge">
                    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" width="14" height="14"><path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/></svg>
                    Verified
                  </div>
                </div>
                <div className="settings-form">
                  <div className="settings-form-group">
                    <label className="settings-label">Current Email</label>
                    <div className="settings-input-wrapper">
                      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" width="16" height="16" className="settings-input-icon"><path d="M4 4h16c1.1 0 2 .9 2 2v12c0 1.1-.9 2-2 2H4c-1.1 0-2-.9-2-2V6c0-1.1.9-2 2-2z"/><polyline points="22,6 12,13 2,6"/></svg>
                      <input type="email" value={user.email} className="settings-input" disabled />
                    </div>
                  </div>

                  {emailStep === 'idle' && (
                    <form onSubmit={handleRequestEmailChange}>
                      <div className="settings-form-group" style={{ marginBottom: 16 }}>
                        <label htmlFor="settings-new-email" className="settings-label">New Email Address</label>
                        <div className="settings-input-wrapper">
                          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" width="16" height="16" className="settings-input-icon"><path d="M4 4h16c1.1 0 2 .9 2 2v12c0 1.1-.9 2-2 2H4c-1.1 0-2-.9-2-2V6c0-1.1.9-2 2-2z"/><polyline points="22,6 12,13 2,6"/></svg>
                          <input id="settings-new-email" type="email" value={newEmail} onChange={(e) => setNewEmail(e.target.value)} className="settings-input" placeholder="Enter new email address" required />
                        </div>
                      </div>
                      {emailMsg && <div className={`settings-msg settings-msg-${emailMsg.type}`} style={{ marginBottom: 16 }}>{emailMsg.text}</div>}
                      <div className="settings-form-actions">
                        <button type="submit" className="settings-btn-primary" disabled={emailSaving || !newEmail.trim()}>
                          {emailSaving ? <><span className="settings-btn-spinner"></span>Sending...</> : 'Send Verification Code'}
                        </button>
                      </div>
                    </form>
                  )}

                  {emailStep === 'verify' && (
                    <form onSubmit={handleConfirmEmailChange}>
                      <div className="settings-email-verify-box">
                        <div className="settings-verify-icon">📧</div>
                        <p className="settings-verify-text">Enter the codes sent to <strong>{user.email}</strong> and <strong>{newEmail}</strong></p>
                        <div className="settings-form-row" style={{ marginTop: 12 }}>
                          <div className="settings-form-group">
                            <label htmlFor="settings-current-email-code" className="settings-label">Current Email Code</label>
                            <input id="settings-current-email-code" type="text" value={emailCurrentCode} onChange={(e) => setEmailCurrentCode(e.target.value.replace(/\D/g, '').slice(0, 6))}
                              className="settings-input settings-code-input" placeholder="000000" maxLength={6} autoFocus style={{ textAlign: 'center', letterSpacing: '0.3em', fontSize: '1.2rem', fontWeight: 700, padding: '14px' }} />
                          </div>
                          <div className="settings-form-group">
                            <label htmlFor="settings-new-email-code" className="settings-label">New Email Code</label>
                            <input id="settings-new-email-code" type="text" value={emailNewCode} onChange={(e) => setEmailNewCode(e.target.value.replace(/\D/g, '').slice(0, 6))}
                              className="settings-input settings-code-input" placeholder="000000" maxLength={6} style={{ textAlign: 'center', letterSpacing: '0.3em', fontSize: '1.2rem', fontWeight: 700, padding: '14px' }} />
                          </div>
                        </div>
                        <p className="settings-verify-hint">Changing to: <strong>{newEmail}</strong></p>
                      </div>
                      {emailMsg && <div className={`settings-msg settings-msg-${emailMsg.type}`} style={{ marginTop: 12 }}>{emailMsg.text}</div>}
                      <div className="settings-form-actions" style={{ marginTop: 16 }}>
                        <button type="button" className="settings-btn-secondary" onClick={handleCancelEmailChange} disabled={emailSaving}>Cancel</button>
                        <button type="submit" className="settings-btn-primary" disabled={emailSaving || emailCurrentCode.length !== 6 || emailNewCode.length !== 6}>
                          {emailSaving ? <><span className="settings-btn-spinner"></span>Verifying...</> : 'Confirm Change'}
                        </button>
                      </div>
                    </form>
                  )}
                </div>
              </section>
            </>
          )}

          {activeTab === 'security' && (
            <section className="settings-section">
              <div className="settings-section-header">
                <div><h2>Change Password</h2><p className="settings-section-desc">Keep your account secure with a strong password</p></div>
                <div className="settings-section-badge">
                  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" width="14" height="14"><path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/></svg>
                  Secure
                </div>
              </div>
              <form onSubmit={handlePasswordChange} className="settings-form">
                <div className="settings-form-group">
                  <label htmlFor="settings-current-pw" className="settings-label">Current Password</label>
                  <div className="settings-input-wrapper">
                    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" width="16" height="16" className="settings-input-icon"><rect x="3" y="11" width="18" height="11" rx="2" ry="2"/><path d="M7 11V7a5 5 0 0110 0v4"/></svg>
                    <input id="settings-current-pw" type={showCurrentPw ? 'text' : 'password'} value={currentPassword} onChange={(e) => setCurrentPassword(e.target.value)} className="settings-input" required placeholder="Enter current password" />
                    <button type="button" className="settings-pw-toggle" onClick={() => setShowCurrentPw(!showCurrentPw)}>
                      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" width="16" height="16">
                        {showCurrentPw ? <><path d="M17.94 17.94A10.07 10.07 0 0112 20c-7 0-11-8-11-8a18.45 18.45 0 015.06-5.94M9.9 4.24A9.12 9.12 0 0112 4c7 0 11 8 11 8a18.5 18.5 0 01-2.16 3.19m-6.72-1.07a3 3 0 11-4.24-4.24"/><line x1="1" y1="1" x2="23" y2="23"/></> : <><path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z"/><circle cx="12" cy="12" r="3"/></>}
                      </svg>
                    </button>
                  </div>
                </div>
                <div className="settings-form-row">
                  <div className="settings-form-group">
                    <label htmlFor="settings-new-pw" className="settings-label">New Password</label>
                    <div className="settings-input-wrapper">
                      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" width="16" height="16" className="settings-input-icon"><path d="M21 2l-2 2m-7.61 7.61a5.5 5.5 0 11-7.78 7.77 5.5 5.5 0 017.78-7.77zm0 0L15.5 7.5m0 0l3 3L22 7l-3-3m-3.5 3.5L19 4"/></svg>
                      <input id="settings-new-pw" type={showNewPw ? 'text' : 'password'} value={newPassword} onChange={(e) => setNewPassword(e.target.value)} className="settings-input" required minLength={6} placeholder="Enter new password" />
                      <button type="button" className="settings-pw-toggle" onClick={() => setShowNewPw(!showNewPw)}>
                        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" width="16" height="16">
                          {showNewPw ? <><path d="M17.94 17.94A10.07 10.07 0 0112 20c-7 0-11-8-11-8a18.45 18.45 0 015.06-5.94"/><line x1="1" y1="1" x2="23" y2="23"/></> : <><path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z"/><circle cx="12" cy="12" r="3"/></>}
                        </svg>
                      </button>
                    </div>
                  </div>
                  <div className="settings-form-group">
                    <label htmlFor="settings-new-pw2" className="settings-label">Confirm New Password</label>
                    <div className="settings-input-wrapper">
                      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" width="16" height="16" className="settings-input-icon"><path d="M22 11.08V12a10 10 0 11-5.93-9.14"/><polyline points="22 4 12 14.01 9 11.01"/></svg>
                      <input id="settings-new-pw2" type={showNewPw ? 'text' : 'password'} value={newPassword2} onChange={(e) => setNewPassword2(e.target.value)} className="settings-input" required minLength={6} placeholder="Confirm new password" />
                    </div>
                    {newPassword && newPassword2 && newPassword !== newPassword2 && <p className="settings-field-error">Passwords do not match</p>}
                  </div>
                </div>
                {newPassword && (
                  <div className="settings-pw-strength">
                    <div className="settings-pw-strength-bar">
                      <div className={`settings-pw-strength-fill ${newPassword.length >= 12 ? 'pw-strong' : newPassword.length >= 8 ? 'pw-medium' : 'pw-weak'}`}
                        style={{ width: `${Math.min(100, (newPassword.length / 12) * 100)}%` }}></div>
                    </div>
                    <span className="settings-pw-strength-text">{newPassword.length >= 12 ? 'Strong' : newPassword.length >= 8 ? 'Medium' : 'Weak'}</span>
                  </div>
                )}
                {passwordMsg && <div className={`settings-msg settings-msg-${passwordMsg.type}`}>{passwordMsg.text}</div>}
                <div className="settings-form-actions">
                  <button type="button" className="settings-btn-secondary" onClick={() => { setCurrentPassword(''); setNewPassword(''); setNewPassword2(''); setPasswordMsg(null); }}>Cancel</button>
                  <button type="submit" className="settings-btn-primary" disabled={passwordSaving || !currentPassword || !newPassword || !newPassword2}>
                    {passwordSaving ? <><span className="settings-btn-spinner"></span>Changing...</> : 'Change Password'}
                  </button>
                </div>
              </form>
            </section>
          )}
        </div>
      </div>
    </div>
  );
}

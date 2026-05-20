import { createPublicMetadata } from '@/lib/seo';

export const metadata = {
  ...createPublicMetadata({
    title: 'Privacy Policy',
    description: 'Learn how GamesBazaar collects, uses, and protects your personal information. Your privacy matters to us.',
    path: '/privacy-policy',
  }),
};

export default function PrivacyPolicyPage() {
  return (
    <div className="legal-page container">
      <div className="legal-header">
        <div className="legal-icon">🔒</div>
        <h1>Privacy Policy</h1>
        <p className="legal-subtitle">
          Your privacy matters to us. Here&rsquo;s a clear explanation of how we handle your information &mdash; no confusing legal jargon, we promise.
        </p>
        <div className="legal-updated">Last updated: May 20, 2026</div>
      </div>

      <div className="legal-content">
        {/* Section 1 */}
        <section className="legal-section" id="privacy-intro">
          <div className="legal-section-icon">👋</div>
          <h2>Welcome</h2>
          <p>
            GamesBazaar (&ldquo;we&rdquo;, &ldquo;us&rdquo;, or &ldquo;our&rdquo;) is Pakistan&rsquo;s digital gaming marketplace where you can buy and sell game accounts, top-ups, in-game items, and boosting services. This Privacy Policy explains what information we collect, why we collect it, and how we keep it safe.
          </p>
          <p>
            By using GamesBazaar, you agree to the practices described in this policy. If you have any questions, feel free to reach out to us anytime.
          </p>
        </section>

        {/* Section 2 */}
        <section className="legal-section" id="privacy-what-we-collect">
          <div className="legal-section-icon">📋</div>
          <h2>What Information We Collect</h2>

          <div className="legal-card">
            <h3>Information You Give Us</h3>
            <ul>
              <li><strong>Account details:</strong> Your username, email address, and password when you sign up.</li>
              <li><strong>Profile info:</strong> Your profile picture and any other details you choose to share.</li>
              <li><strong>Seller info:</strong> If you apply to become a seller, we collect your WhatsApp number and any information you provide in your application.</li>
              <li><strong>Payment details:</strong> Bank account title, account number, and bank name when you request withdrawals.</li>
              <li><strong>Transaction &amp; protection data:</strong> Order details, confirmation timestamps, and buyer protection hold status. For orders covered by our 14-Day Buyer Protection, we retain transaction records for at least 14 days after delivery confirmation to facilitate dispute resolution.</li>
              <li><strong>Messages:</strong> The conversations you have with other users through our built-in chat system.</li>
              <li><strong>Reviews &amp; reports:</strong> Any reviews you write or reports you submit.</li>
            </ul>
          </div>

          <div className="legal-card">
            <h3>Information We Collect Automatically</h3>
            <ul>
              <li><strong>Usage data:</strong> Which pages you visit, what you search for, and how you interact with the platform.</li>
              <li><strong>Device info:</strong> Your browser type, operating system, and screen size to give you a better experience.</li>
              <li><strong>IP address:</strong> Used for security, fraud prevention, and to ensure the platform is used within Pakistan.</li>
              <li><strong>Cookies and similar technologies:</strong> Small files and tracking tools used to keep you logged in, remember preferences, measure site performance, and understand how our ads are working.</li>
            </ul>
          </div>
        </section>

        {/* Section 3 */}
        <section className="legal-section" id="privacy-how-we-use">
          <div className="legal-section-icon">⚙️</div>
          <h2>How We Use Your Information</h2>
          <p>We use your information to:</p>
          <div className="legal-grid">
            <div className="legal-grid-item">
              <span className="legal-grid-icon">🛡️</span>
              <div>
                <strong>Keep you safe</strong>
                <p>Protect your account and prevent fraud, scams, or unauthorized access.</p>
              </div>
            </div>
            <div className="legal-grid-item">
              <span className="legal-grid-icon">🛒</span>
              <div>
                <strong>Process your orders</strong>
                <p>Handle transactions, manage wallet balances, and process withdrawal requests.</p>
              </div>
            </div>
            <div className="legal-grid-item">
              <span className="legal-grid-icon">💬</span>
              <div>
                <strong>Enable communication</strong>
                <p>Let you chat with buyers and sellers through our platform.</p>
              </div>
            </div>
            <div className="legal-grid-item">
              <span className="legal-grid-icon">🛡️</span>
              <div>
                <strong>Enforce Buyer Protection</strong>
                <p>Manage the 14-day fund hold, track protection windows, and process post-delivery disputes.</p>
              </div>
            </div>
            <div className="legal-grid-item">
              <span className="legal-grid-icon">🔔</span>
              <div>
                <strong>Send notifications</strong>
                <p>Keep you updated about orders, messages, protection hold releases, and important account activity.</p>
              </div>
            </div>
            <div className="legal-grid-item">
              <span className="legal-grid-icon">📊</span>
              <div>
                <strong>Improve our platform</strong>
                <p>Understand how people use GamesBazaar so we can make it better for everyone.</p>
              </div>
            </div>
            <div className="legal-grid-item">
              <span className="legal-grid-icon">📣</span>
              <div>
                <strong>Measure ads and marketing</strong>
                <p>Understand which campaigns bring people to GamesBazaar, measure ad performance, and show more relevant promotions.</p>
              </div>
            </div>
            <div className="legal-grid-item">
              <span className="legal-grid-icon">⚖️</span>
              <div>
                <strong>Resolve disputes</strong>
                <p>Investigate issues between buyers and sellers and enforce our rules fairly, including during the 14-day protection window.</p>
              </div>
            </div>
          </div>
        </section>

        {/* Section 4 */}
        <section className="legal-section" id="privacy-sharing">
          <div className="legal-section-icon">🤝</div>
          <h2>Who We Share Your Information With</h2>
          <p>We do <strong>not</strong> sell your personal information to anyone. Period. We may share limited information in these situations:</p>
          <ul>
            <li><strong>Other users:</strong> Your username, profile picture, and seller profile (if applicable) are visible to other users on the platform.</li>
            <li><strong>Payment processors:</strong> We share necessary details to process your withdrawals through Pakistani banking channels.</li>
            <li><strong>Analytics and advertising partners:</strong> We may use tools such as Google Analytics, Google Ads, Google Tag Manager, and Meta Pixel. These tools may receive limited usage, device, browser, and event information to help us measure traffic, understand ad performance, and improve our marketing.</li>
            <li><strong>Law enforcement:</strong> If required by Pakistani law or a valid court order, we may share information with authorities.</li>
            <li><strong>Platform safety:</strong> To investigate fraud, abuse, or violations of our terms.</li>
          </ul>
        </section>

        {/* Section 5 */}
        <section className="legal-section" id="privacy-security">
          <div className="legal-section-icon">🔐</div>
          <h2>How We Keep Your Data Safe</h2>
          <p>We take the security of your information seriously:</p>
          <ul>
            <li>Passwords are hashed and never stored in plain text &mdash; even we can&rsquo;t see them.</li>
            <li>All communication between your browser and our servers is encrypted.</li>
            <li>We use secure authentication tokens that expire automatically.</li>
            <li>Two-step verification is required for sensitive actions like changing your email.</li>
            <li>We regularly review and update our security practices.</li>
          </ul>
          <div className="legal-callout">
            <span className="legal-callout-icon">💡</span>
            <div>
              <strong>Tip:</strong> Always use a strong, unique password for your GamesBazaar account. Never share your login details with anyone, including people claiming to be from our team.
            </div>
          </div>
        </section>

        {/* Section 6 */}
        <section className="legal-section" id="privacy-cookies">
          <div className="legal-section-icon">🍪</div>
          <h2>Cookies</h2>
          <p>
            We use cookies (small text files) and similar technologies to keep you logged in, remember your preferences, make the platform work smoothly, measure site performance, and understand how our advertising is performing.
          </p>
          <p>
            We may use trusted analytics and advertising tools, including Google Analytics, Google Ads, Google Tag Manager, and Meta Pixel. These tools can help us understand visits, actions taken on GamesBazaar, and whether our ads are useful. They may set or read their own cookies according to their own privacy policies.
          </p>
          <p>
            You can disable cookies in your browser settings, but this may prevent some features from working properly (like staying logged in).
          </p>
        </section>

        {/* Section 7 */}
        <section className="legal-section" id="privacy-your-rights">
          <div className="legal-section-icon">✅</div>
          <h2>Your Rights</h2>
          <p>You have the right to:</p>
          <ul>
            <li><strong>Access your data:</strong> See what information we have about you through your account settings.</li>
            <li><strong>Update your information:</strong> Change your username, email, password, and profile picture anytime from your settings page.</li>
            <li><strong>Delete your account:</strong> Contact our support team to request account deletion. Please note that some transaction records may be kept for legal and dispute resolution purposes.</li>
            <li><strong>Download your data:</strong> Request a copy of your personal data by contacting us.</li>
          </ul>
        </section>

        {/* Section 8 */}
        <section className="legal-section" id="privacy-children">
          <div className="legal-section-icon">👦</div>
          <h2>Children&rsquo;s Privacy</h2>
          <p>
            GamesBazaar is designed for users aged 13 and above. We do not knowingly collect information from children under 13. If you believe a child under 13 has created an account, please contact us and we will take appropriate action.
          </p>
        </section>

        {/* Section 9 */}
        <section className="legal-section" id="privacy-changes">
          <div className="legal-section-icon">📝</div>
          <h2>Changes to This Policy</h2>
          <p>
            We may update this Privacy Policy from time to time. When we do, we&rsquo;ll update the &ldquo;Last updated&rdquo; date at the top. For significant changes, we&rsquo;ll notify you through the platform. We encourage you to check this page occasionally.
          </p>
        </section>

        {/* Section 10 */}
        <section className="legal-section" id="privacy-contact">
          <div className="legal-section-icon">📬</div>
          <h2>Contact Us</h2>
          <p>
            If you have any questions about this Privacy Policy or how we handle your data, get in touch with us:
          </p>
          <div className="legal-contact-card">
            <div className="legal-contact-row">
              <span>📧</span>
              <span>support@gamesbazaar.pk</span>
            </div>
            <div className="legal-contact-row">
              <span>🌐</span>
              <span>GamesBazaar — Pakistan&rsquo;s #1 Gaming Marketplace</span>
            </div>
          </div>
        </section>
      </div>
    </div>
  );
}

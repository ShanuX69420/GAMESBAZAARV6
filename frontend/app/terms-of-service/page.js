export const metadata = {
  title: 'Terms of Service — GamesBazaar',
  description: 'Read the Terms of Service for GamesBazaar, Pakistan\'s trusted digital gaming marketplace. Know your rights and responsibilities.',
};

export default function TermsOfServicePage() {
  return (
    <div className="legal-page container">
      <div className="legal-header">
        <div className="legal-icon">📜</div>
        <h1>Terms of Service</h1>
        <p className="legal-subtitle">
          These are the rules of our marketplace. We&rsquo;ve kept them as straightforward as possible &mdash; no 50-page legalese.
        </p>
        <div className="legal-updated">Last updated: May 6, 2026</div>
      </div>

      <div className="legal-content">
        {/* Section 1 */}
        <section className="legal-section" id="tos-overview">
          <div className="legal-section-icon">🎮</div>
          <h2>What is GamesBazaar?</h2>
          <p>
            GamesBazaar is Pakistan&rsquo;s digital gaming marketplace. We connect buyers and sellers of game accounts, top-ups, in-game items, and boosting services. Think of us as the bridge between gamers who want to buy and gamers who want to sell.
          </p>
          <p>
            By creating an account or using our platform, you agree to these Terms of Service. If you don&rsquo;t agree, please don&rsquo;t use the platform.
          </p>
        </section>

        {/* Section 2 */}
        <section className="legal-section" id="tos-eligibility">
          <div className="legal-section-icon">✋</div>
          <h2>Who Can Use GamesBazaar?</h2>
          <div className="legal-card">
            <ul>
              <li>You must be <strong>at least 13 years old</strong> to create an account.</li>
              <li>You must be a resident of <strong>Pakistan</strong>. This platform currently operates only within Pakistan.</li>
              <li>You can only have <strong>one account</strong>. Creating multiple accounts is not allowed and may result in a ban.</li>
              <li>All information you provide must be <strong>accurate and truthful</strong>.</li>
            </ul>
          </div>
        </section>

        {/* Section 3 */}
        <section className="legal-section" id="tos-accounts">
          <div className="legal-section-icon">🔑</div>
          <h2>Your Account</h2>
          <p>When you create a GamesBazaar account:</p>
          <ul>
            <li>You are responsible for keeping your password secure. Don&rsquo;t share it with anyone.</li>
            <li>You are responsible for all activity on your account, so keep it secure.</li>
            <li>You can change your username once every 90 days.</li>
            <li>If you suspect unauthorized access to your account, contact us immediately.</li>
            <li>We reserve the right to suspend or permanently ban accounts that violate our rules.</li>
          </ul>
        </section>

        {/* Section 4 */}
        <section className="legal-section" id="tos-buying">
          <div className="legal-section-icon">🛒</div>
          <h2>Buying on GamesBazaar</h2>
          <p>When you purchase something on our platform:</p>
          <div className="legal-steps">
            <div className="legal-step">
              <div className="legal-step-number">1</div>
              <div>
                <strong>Place your order</strong>
                <p>Browse listings, choose what you want, and place your order. Your payment is held safely by GamesBazaar.</p>
              </div>
            </div>
            <div className="legal-step">
              <div className="legal-step-number">2</div>
              <div>
                <strong>Seller delivers</strong>
                <p>The seller will deliver what you ordered (account credentials, top-up, items, etc.).</p>
              </div>
            </div>
            <div className="legal-step">
              <div className="legal-step-number">3</div>
              <div>
                <strong>You confirm</strong>
                <p>Once you&rsquo;ve received and verified everything, confirm the order. The payment is then released to the seller.</p>
              </div>
            </div>
          </div>
          <div className="legal-callout">
            <span className="legal-callout-icon">⚠️</span>
            <div>
              <strong>Important:</strong> Always verify what you&rsquo;ve received before confirming. Once confirmed, the payment is released to the seller and cannot be reversed.
            </div>
          </div>
        </section>

        {/* Section 5 */}
        <section className="legal-section" id="tos-selling">
          <div className="legal-section-icon">💰</div>
          <h2>Selling on GamesBazaar</h2>
          <p>To sell on GamesBazaar, you must first apply and be approved as a seller. As a seller, you agree to:</p>
          <ul>
            <li><strong>Be honest:</strong> Only list items or services you can actually deliver. Misleading descriptions will result in action against your account.</li>
            <li><strong>Deliver promptly:</strong> Deliver what was ordered within a reasonable time. Delays hurt your reputation and may lead to disputes.</li>
            <li><strong>Set fair prices:</strong> All prices are in Pakistani Rupees (PKR). Price manipulation or deceptive pricing is not allowed.</li>
            <li><strong>Respond to buyers:</strong> Keep communication open through our chat system. Ignoring buyers after they place an order is not acceptable.</li>
            <li><strong>Follow the rules:</strong> Don&rsquo;t try to take transactions outside the platform. All orders must go through GamesBazaar.</li>
          </ul>
        </section>

        {/* Section 6 */}
        <section className="legal-section" id="tos-wallet">
          <div className="legal-section-icon">💳</div>
          <h2>Wallet &amp; Withdrawals</h2>
          <ul>
            <li>All transactions on GamesBazaar use our internal wallet system in <strong>Pakistani Rupees (PKR)</strong>.</li>
            <li>When a buyer confirms an order, the payment is released to the seller&rsquo;s wallet.</li>
            <li>The <strong>minimum withdrawal amount is PKR 500</strong>.</li>
            <li>Withdrawals are processed to Pakistani bank accounts. You must provide accurate bank details (account title, account number, and bank name).</li>
            <li>Withdrawal requests are reviewed and processed by our team. Processing times may vary.</li>
            <li>GamesBazaar is not responsible for delays caused by your bank.</li>
          </ul>
        </section>

        {/* Section 7 */}
        <section className="legal-section" id="tos-disputes">
          <div className="legal-section-icon">⚖️</div>
          <h2>Disputes &amp; Refunds</h2>
          <p>We understand that sometimes things don&rsquo;t go as planned. Here&rsquo;s how we handle disputes:</p>
          <div className="legal-card">
            <ul>
              <li>If there&rsquo;s a problem with your order, you can raise a dispute through the order page.</li>
              <li>Our team will review the dispute and may ask both parties for evidence.</li>
              <li>We aim to resolve disputes fairly, but our decision is final.</li>
              <li>Refunds, when approved, are credited back to the buyer&rsquo;s GamesBazaar wallet.</li>
              <li>Repeatedly raising false disputes may result in account restrictions.</li>
            </ul>
          </div>
          <div className="legal-callout">
            <span className="legal-callout-icon">💡</span>
            <div>
              <strong>Pro tip:</strong> Use the in-app chat to try resolving issues with the other party before raising a formal dispute. Most problems can be sorted out through good communication.
            </div>
          </div>
        </section>

        {/* Section 8 */}
        <section className="legal-section" id="tos-prohibited">
          <div className="legal-section-icon">🚫</div>
          <h2>What&rsquo;s Not Allowed</h2>
          <p>To keep GamesBazaar safe for everyone, the following are strictly prohibited:</p>
          <div className="legal-grid">
            <div className="legal-grid-item legal-grid-item-danger">
              <span className="legal-grid-icon">❌</span>
              <div>
                <strong>Scamming or fraud</strong>
                <p>Attempting to cheat buyers or sellers in any way.</p>
              </div>
            </div>
            <div className="legal-grid-item legal-grid-item-danger">
              <span className="legal-grid-icon">❌</span>
              <div>
                <strong>Off-platform deals</strong>
                <p>Taking transactions outside GamesBazaar to avoid our protection system.</p>
              </div>
            </div>
            <div className="legal-grid-item legal-grid-item-danger">
              <span className="legal-grid-icon">❌</span>
              <div>
                <strong>Fake listings</strong>
                <p>Listing items or services you don&rsquo;t actually have or can&rsquo;t deliver.</p>
              </div>
            </div>
            <div className="legal-grid-item legal-grid-item-danger">
              <span className="legal-grid-icon">❌</span>
              <div>
                <strong>Harassment &amp; abuse</strong>
                <p>Threatening, abusing, or harassing other users in chat or reviews.</p>
              </div>
            </div>
            <div className="legal-grid-item legal-grid-item-danger">
              <span className="legal-grid-icon">❌</span>
              <div>
                <strong>Multiple accounts</strong>
                <p>Creating more than one account to manipulate the platform.</p>
              </div>
            </div>
            <div className="legal-grid-item legal-grid-item-danger">
              <span className="legal-grid-icon">❌</span>
              <div>
                <strong>Illegal content</strong>
                <p>Selling stolen accounts, using stolen payment methods, or any activity that violates Pakistani law.</p>
              </div>
            </div>
          </div>
          <p style={{ marginTop: '16px' }}>
            Violations may result in warnings, temporary suspensions, permanent bans, and/or withholding of wallet funds.
          </p>
        </section>

        {/* Section 9 */}
        <section className="legal-section" id="tos-reviews">
          <div className="legal-section-icon">⭐</div>
          <h2>Reviews &amp; Feedback</h2>
          <ul>
            <li>After completing an order, buyers can leave a review with a star rating and comment.</li>
            <li>Reviews should be <strong>honest and based on your actual experience</strong>.</li>
            <li>You can edit your review if you change your mind.</li>
            <li>Sellers can reply once to each review.</li>
            <li>Fake reviews, review manipulation, or threatening someone over a review is not allowed and will result in action against your account.</li>
          </ul>
        </section>

        {/* Section 10 */}
        <section className="legal-section" id="tos-intellectual-property">
          <div className="legal-section-icon">©️</div>
          <h2>Intellectual Property</h2>
          <p>
            The GamesBazaar name, logo, design, and all original content on our platform belong to us. You may not copy, modify, or use our branding without permission.
          </p>
          <p>
            Game names, logos, and related content belong to their respective publishers and developers. GamesBazaar is not affiliated with or endorsed by any game publisher.
          </p>
        </section>

        {/* Section 11 */}
        <section className="legal-section" id="tos-liability">
          <div className="legal-section-icon">📌</div>
          <h2>Our Responsibilities &amp; Limitations</h2>
          <div className="legal-card">
            <h3>What we do</h3>
            <ul>
              <li>Provide a secure marketplace for digital gaming transactions.</li>
              <li>Hold payments safely until buyers confirm delivery.</li>
              <li>Investigate and resolve disputes between users.</li>
              <li>Keep improving the platform for a better experience.</li>
            </ul>
          </div>
          <div className="legal-card" style={{ marginTop: '16px' }}>
            <h3>What we&rsquo;re not responsible for</h3>
            <ul>
              <li>The quality or authenticity of items sold by third-party sellers &mdash; we facilitate, but sellers are responsible for what they sell.</li>
              <li>Issues with game accounts after the transaction is confirmed (e.g., account bans by the game publisher).</li>
              <li>Losses from sharing your account credentials with others.</li>
              <li>Service interruptions due to technical issues, maintenance, or events beyond our control.</li>
            </ul>
          </div>
        </section>

        {/* Section 12 */}
        <section className="legal-section" id="tos-governing-law">
          <div className="legal-section-icon">🏛️</div>
          <h2>Governing Law</h2>
          <p>
            These Terms of Service are governed by and interpreted in accordance with the laws of the <strong>Islamic Republic of Pakistan</strong>. Any disputes arising from these terms will be subject to the jurisdiction of Pakistani courts.
          </p>
        </section>

        {/* Section 13 */}
        <section className="legal-section" id="tos-changes">
          <div className="legal-section-icon">📝</div>
          <h2>Changes to These Terms</h2>
          <p>
            We may update these Terms of Service as our platform evolves. When we make significant changes, we&rsquo;ll notify you through the platform. Continued use of GamesBazaar after changes means you accept the updated terms.
          </p>
        </section>

        {/* Section 14 */}
        <section className="legal-section" id="tos-contact">
          <div className="legal-section-icon">📬</div>
          <h2>Questions?</h2>
          <p>
            If anything in these terms is unclear, or if you have questions, don&rsquo;t hesitate to reach out:
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

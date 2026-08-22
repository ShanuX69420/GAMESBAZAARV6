import { createPublicMetadata } from '@/lib/seo';

export const metadata = {
  ...createPublicMetadata({
    title: 'Terms of Service',
    description: 'Read the Terms of Service for GamesBazaar, Pakistan\'s trusted digital gaming store. Know your rights and responsibilities.',
    path: '/terms-of-service',
  }),
};

export default function TermsOfServicePage() {
  return (
    <div className="legal-page container">
      <div className="legal-header">
        <h1>Terms of Service</h1>
        <p className="legal-subtitle">
          These are the rules of our store. We&rsquo;ve kept them as straightforward as possible &mdash; no 50-page legalese.
        </p>
        <div className="legal-updated">Last updated: August 22, 2026</div>
      </div>

      <div className="legal-content">
        {/* Section 1 */}
        <section className="legal-section" id="tos-overview">
          <h2>What is GamesBazaar?</h2>
          <p>
            GamesBazaar is Pakistan&rsquo;s digital gaming store. We sell game keys, accounts, top-ups, gift cards, and in-game items &mdash; delivered fast and priced in Pakistani Rupees.
          </p>
          <p>
            By creating an account or using our platform, you agree to these Terms of Service. If you don&rsquo;t agree, please don&rsquo;t use the platform.
          </p>
        </section>

        {/* Section 2 */}
        <section className="legal-section" id="tos-eligibility">
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
                <strong>We deliver</strong>
                <p>We deliver what you ordered (game key, account credentials, top-up, etc.) &mdash; instantly for many items.</p>
              </div>
            </div>
            <div className="legal-step">
              <div className="legal-step-number">3</div>
              <div>
                <strong>You confirm</strong>
                <p>Once you&rsquo;ve received and verified everything, confirm the order. For categories with Buyer Protection, you keep a safety net for an additional 14 days after confirmation to report any issues.</p>
              </div>
            </div>
          </div>
          <div className="legal-callout">
            <div>
              <strong>Important:</strong> Always verify what you&rsquo;ve received before confirming. For orders <strong>without</strong> Buyer Protection, the sale is final once you confirm delivery.
            </div>
          </div>
        </section>

        {/* Section 4b — Buyer Protection */}
        <section className="legal-section" id="tos-buyer-protection">
          <h2>14-Day Buyer Protection</h2>
          <p>
            For eligible categories, GamesBazaar offers a <strong>14-Day Buyer Protection</strong> program. This feature is designed to safeguard buyers against fraud, misrepresentation, and post-delivery issues.
          </p>
          <div className="legal-card">
            <h3>How It Works</h3>
            <ul>
              <li><strong>Protection hold:</strong> When you confirm delivery on a protected order, your purchase stays covered by GamesBazaar for <strong>14 calendar days</strong>.</li>
              <li><strong>Dispute window:</strong> During those 14 days, you can raise a dispute if you discover issues with the delivered item (e.g., incorrect credentials, account recovery by original owner, or items not matching the description).</li>
              <li><strong>Window closes:</strong> If no dispute is raised within 14 days, the protection window closes and the order is final.</li>
              <li><strong>Category-based:</strong> Buyer Protection is enabled on a per-category basis. Whether a listing is covered is clearly indicated on the listing page with a Buyer Protection badge.</li>
            </ul>
          </div>
          <div className="legal-card" style={{ marginTop: '16px' }}>
            <h3>What&rsquo;s Covered</h3>
            <ul>
              <li>Items that don&rsquo;t match the listing description.</li>
              <li>Account credentials that are invalid or don&rsquo;t work as described.</li>
              <li>Accounts recovered by the original owner during the protection period.</li>
              <li>Undelivered in-game items, top-ups, or services that were marked as completed.</li>
            </ul>
          </div>
          <div className="legal-card" style={{ marginTop: '16px' }}>
            <h3>What&rsquo;s Not Covered</h3>
            <ul>
              <li>Issues arising after the 14-day protection window has expired.</li>
              <li>Account bans imposed by the game publisher for buyer&rsquo;s own actions after delivery.</li>
              <li>Buyer&rsquo;s remorse or change of mind after confirming a valid delivery.</li>
              <li>Issues caused by sharing account credentials with third parties.</li>
            </ul>
          </div>
          <div className="legal-callout">
            <div>
              <strong>Tip:</strong> You can check the real-time status and countdown of your held orders in the <strong>Held Balance</strong> section of your Wallet page.
            </div>
          </div>
        </section>

        {/* Section 5 */}
        <section className="legal-section" id="tos-our-promise">
          <h2>Our Promise to You</h2>
          <p>When you buy from GamesBazaar, we commit to:</p>
          <ul>
            <li><strong>Honest listings:</strong> We only list items we can actually deliver, described accurately.</li>
            <li><strong>Prompt delivery:</strong> Every listing shows its delivery time up front, and many items are delivered instantly.</li>
            <li><strong>Fair prices:</strong> All prices are in Pakistani Rupees (PKR) with no hidden charges at checkout.</li>
            <li><strong>Responsive support:</strong> If something goes wrong with your order, reach us through the order page, support, or WhatsApp &mdash; we&rsquo;ll make it right.</li>
          </ul>
        </section>

        {/* Section 6 */}
        <section className="legal-section" id="tos-wallet">
          <h2>Wallet &amp; Withdrawals</h2>
          <ul>
            <li>All transactions on GamesBazaar use our internal wallet system in <strong>Pakistani Rupees (PKR)</strong>.</li>
            <li>When you place an order, the amount is paid from your wallet balance. Approved refunds are credited straight back to your wallet.</li>
            <li>The <strong>minimum withdrawal amount is PKR 500</strong>.</li>
            <li>Withdrawals are processed to Pakistani bank accounts. You must provide accurate bank details (account title, account number, and bank name).</li>
            <li>Withdrawal requests are reviewed and processed by our team. Processing times may vary.</li>
            <li>GamesBazaar is not responsible for delays caused by your bank.</li>
          </ul>
        </section>

        {/* Section 7 */}
        <section className="legal-section" id="tos-disputes">
          <h2>Disputes &amp; Refunds</h2>
          <p>We understand that sometimes things don&rsquo;t go as planned. Here&rsquo;s how we handle disputes:</p>
          <div className="legal-card">
            <ul>
              <li>If there&rsquo;s a problem with your order, you can raise a dispute through the order page.</li>
              <li>For orders covered by <strong>14-Day Buyer Protection</strong>, you can raise a dispute even after confirming delivery &mdash; as long as it falls within the 14-day protection window.</li>
              <li>Our team will review the dispute and may ask you for evidence.</li>
              <li>We aim to resolve disputes fairly, but our decision is final.</li>
              <li>Refunds, when approved, are credited back to the buyer&rsquo;s GamesBazaar wallet.</li>
              <li>If a dispute is raised during the protection period, the held funds will remain frozen until the dispute is resolved.</li>
              <li>Repeatedly raising false disputes may result in account restrictions.</li>
            </ul>
          </div>
          <div className="legal-callout">
            <div>
              <strong>Pro tip:</strong> Message us from your order page before raising a formal dispute. Most problems can be sorted out through good communication.
            </div>
          </div>
        </section>

        {/* Section 8 */}
        <section className="legal-section" id="tos-prohibited">
          <h2>What&rsquo;s Not Allowed</h2>
          <p>To keep GamesBazaar safe for everyone, the following are strictly prohibited:</p>
          <div className="legal-grid">
            <div className="legal-grid-item legal-grid-item-danger">
              <div>
                <strong>Scamming or fraud</strong>
                <p>Attempting to cheat GamesBazaar or other users in any way.</p>
              </div>
            </div>
            <div className="legal-grid-item legal-grid-item-danger">
              <div>
                <strong>Off-platform deals</strong>
                <p>Taking transactions outside GamesBazaar to avoid our protection system.</p>
              </div>
            </div>
            <div className="legal-grid-item legal-grid-item-danger">
              <div>
                <strong>Payment abuse</strong>
                <p>Using stolen payment methods or filing false payment reversals.</p>
              </div>
            </div>
            <div className="legal-grid-item legal-grid-item-danger">
              <div>
                <strong>Harassment &amp; abuse</strong>
                <p>Threatening, abusing, or harassing other users in chat or reviews.</p>
              </div>
            </div>
            <div className="legal-grid-item legal-grid-item-danger">
              <div>
                <strong>Multiple accounts</strong>
                <p>Creating more than one account to manipulate the platform.</p>
              </div>
            </div>
            <div className="legal-grid-item legal-grid-item-danger">
              <div>
                <strong>Illegal activity</strong>
                <p>Reselling stolen accounts or any activity that violates Pakistani law.</p>
              </div>
            </div>
          </div>
          <p style={{ marginTop: '16px' }}>
            Violations may result in warnings, temporary suspensions, permanent bans, and/or withholding of wallet funds.
          </p>
        </section>

        {/* Section 9 */}
        <section className="legal-section" id="tos-reviews">
          <h2>Reviews &amp; Feedback</h2>
          <ul>
            <li>After completing an order, buyers can leave a review with a star rating and comment.</li>
            <li>Reviews should be <strong>honest and based on your actual experience</strong>.</li>
            <li>You can edit your review if you change your mind.</li>
            <li>We may reply once to each review.</li>
            <li>Fake reviews, review manipulation, or threatening someone over a review is not allowed and will result in action against your account.</li>
          </ul>
        </section>

        {/* Section 10 */}
        <section className="legal-section" id="tos-intellectual-property">
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
          <h2>Our Responsibilities &amp; Limitations</h2>
          <div className="legal-card">
            <h3>What we do</h3>
            <ul>
              <li>Provide a secure store for digital gaming purchases.</li>
              <li>Hold payments safely until buyers confirm delivery.</li>
              <li>Enforce the 14-Day Buyer Protection hold on eligible categories to give buyers a post-delivery safety net.</li>
              <li>Investigate and resolve disputes between users.</li>
              <li>Keep improving the platform for a better experience.</li>
            </ul>
          </div>
          <div className="legal-card" style={{ marginTop: '16px' }}>
            <h3>What we&rsquo;re not responsible for</h3>
            <ul>
              <li>Issues with game accounts after the transaction is confirmed (e.g., account bans by the game publisher).</li>
              <li>Losses from sharing your account credentials with others.</li>
              <li>Service interruptions due to technical issues, maintenance, or events beyond our control.</li>
            </ul>
          </div>
        </section>

        {/* Section 12 */}
        <section className="legal-section" id="tos-governing-law">
          <h2>Governing Law</h2>
          <p>
            These Terms of Service are governed by and interpreted in accordance with the laws of the <strong>Islamic Republic of Pakistan</strong>. Any disputes arising from these terms will be subject to the jurisdiction of Pakistani courts.
          </p>
        </section>

        {/* Section 13 */}
        <section className="legal-section" id="tos-changes">
          <h2>Changes to These Terms</h2>
          <p>
            We may update these Terms of Service as our platform evolves. When we make significant changes, we&rsquo;ll notify you through the platform. Continued use of GamesBazaar after changes means you accept the updated terms.
          </p>
        </section>

        {/* Section 14 */}
        <section className="legal-section" id="tos-contact">
          <h2>Questions?</h2>
          <p>
            If anything in these terms is unclear, or if you have questions, don&rsquo;t hesitate to reach out:
          </p>
          <div className="legal-contact-card">
            <div className="legal-contact-row">
              <span>support@gamesbazaar.pk</span>
            </div>
            <div className="legal-contact-row">
              <span>GamesBazaar — Pakistan&rsquo;s Gaming Store</span>
            </div>
          </div>
        </section>
      </div>
    </div>
  );
}

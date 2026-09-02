import Link from 'next/link';
import JsonLd from '@/components/JsonLd';
import { fetchSiteReviews } from '@/lib/api';
import { BUSINESS, whatsappUrl } from '@/lib/business';
import {
  absoluteUrl,
  breadcrumbJsonLd,
  createPublicMetadata,
  organizationJsonLd,
} from '@/lib/seo';

const PAGE_TITLE = 'About GamesBazaar';
const PAGE_DESCRIPTION =
  `GamesBazaar is an independently owned online game store based in ${BUSINESS.city}, ` +
  `${BUSINESS.country}, open since ${BUSINESS.foundedYear}. Game keys, accounts, gift cards, ` +
  'subscriptions and PlayStation rentals at rupee prices, paid by JazzCash, Easypaisa or bank transfer.';

export const metadata = createPublicMetadata({
  title: 'About Us',
  description: PAGE_DESCRIPTION,
  path: '/about',
});

// The Organization block already ships sitewide from the root layout; here it
// is nested as the subject of the AboutPage so the page says, in structured
// form, "this page is about that business".
function aboutPageJsonLd() {
  const { '@context': _context, ...organization } = organizationJsonLd();
  return {
    '@context': 'https://schema.org',
    '@type': 'AboutPage',
    name: PAGE_TITLE,
    url: absoluteUrl('/about'),
    description: PAGE_DESCRIPTION,
    mainEntity: organization,
  };
}

function renderStars(rating) {
  return '★'.repeat(Math.round(rating)) + '☆'.repeat(5 - Math.round(rating));
}

const CATALOG = [
  {
    href: '/keys',
    name: 'Game keys',
    text: 'Official Steam keys and Pakistan-region Steam gifts, delivered to your order chat the moment payment goes through.',
  },
  {
    href: '/accounts',
    name: 'Game accounts',
    text: 'Ready-to-play accounts for PC and console games, with the login details and instructions delivered after purchase.',
  },
  {
    href: '/gift-cards',
    name: 'Gift cards',
    text: 'Steam, PlayStation, Xbox, Roblox and other store credit, sorted by region so the code redeems on your account.',
  },
  {
    href: '/subscriptions',
    name: 'Subscriptions',
    text: 'PlayStation Plus and Xbox Game Pass membership codes by tier, duration and region, redeemed on your own account.',
  },
  {
    href: '/rentals',
    name: 'PlayStation rentals',
    text: 'Play a full PlayStation game on your own console for a fixed period at a fraction of the purchase price.',
  },
];

export default async function AboutPage() {
  let summary = null;
  try {
    const data = await fetchSiteReviews();
    summary = data?.summary || null;
  } catch {
    // The numbers are a bonus. The page must render without them.
  }
  const hasReviews = summary?.average != null && summary.count > 0;

  return (
    <div className="legal-page about-page container">
      <JsonLd
        data={[
          aboutPageJsonLd(),
          breadcrumbJsonLd([
            { name: 'Home', path: '/' },
            { name: 'About', path: '/about' },
          ]),
        ]}
      />

      <div className="legal-header">
        <h1>About GamesBazaar</h1>
        <p className="legal-subtitle">
          An independent Pakistani store for game keys, accounts, gift cards, subscriptions and
          PlayStation rentals &mdash; priced in rupees and paid the local way.
        </p>
        <div className="legal-updated">
          Independently owned &middot; {BUSINESS.city}, {BUSINESS.country} &middot; Since {BUSINESS.foundedYear}
        </div>
      </div>

      <div className="legal-content">
        <section className="legal-section" id="about-glance">
          <h2>GamesBazaar at a glance</h2>
          <div className="legal-contact-card about-facts">
            <div className="legal-contact-row">
              <span><strong>What it is:</strong> an online game store. Every order is sold, delivered and supported by GamesBazaar directly.</span>
            </div>
            <div className="legal-contact-row">
              <span><strong>Where:</strong> based in {BUSINESS.city}, {BUSINESS.country}, selling to buyers anywhere in Pakistan.</span>
            </div>
            <div className="legal-contact-row">
              <span><strong>Since:</strong> {BUSINESS.foundedYear}.</span>
            </div>
            <div className="legal-contact-row">
              <span><strong>Prices:</strong> Pakistani rupees only. No dollar conversions and no international card needed.</span>
            </div>
            <div className="legal-contact-row">
              <span><strong>Payments:</strong> JazzCash at checkout, or Easypaisa and bank transfer over WhatsApp.</span>
            </div>
            <div className="legal-contact-row">
              <span><strong>Delivery:</strong> instant on most orders; otherwise in your order chat within the delivery time shown on the listing.</span>
            </div>
            <div className="legal-contact-row">
              <span><strong>If something goes wrong:</strong> message us from the order page and we fix it fast or refund you to your wallet.</span>
            </div>
          </div>
        </section>

        <section className="legal-section" id="about-who">
          <h2>Who runs GamesBazaar</h2>
          <p>
            GamesBazaar is independently owned and run from {BUSINESS.city}. Sourcing, pricing,
            delivery and support are all handled in-house, so when you message support you reach
            the store itself, not an outsourced call centre, and whoever answers can act on your
            order right away.
          </p>
          <p>
            GamesBazaar launched as a marketplace where independent sellers listed their own items.
            In August 2026 it became a direct store: every item is now stocked, sold and supported by
            GamesBazaar, and the buyer protections are the same on every order. If you see it
            described as a marketplace elsewhere, that is the earlier setup.
          </p>
          <p>
            We opened in {BUSINESS.foundedYear} because buying games in Pakistan was harder than it
            should be. Foreign stores price in dollars and expect a card that works internationally.
            Sellers on classifieds and social media offer no comeback when a key fails or an account
            gets pulled. We wanted a store that prices in rupees, takes the payments Pakistanis
            actually use, delivers quickly, and stays reachable after the sale.
          </p>
        </section>

        <section className="legal-section" id="about-catalog">
          <h2>What we sell</h2>
          <div className="legal-grid">
            {CATALOG.map((item) => (
              <div key={item.href} className="legal-grid-item">
                <div>
                  <strong><Link href={item.href}>{item.name}</Link></strong>
                  <p>{item.text}</p>
                </div>
              </div>
            ))}
          </div>
          <p>
            The full list of games is on the <Link href="/games">games page</Link>. Each game has its
            own pages per category with live rupee prices and real stock.
          </p>
        </section>

        <section className="legal-section" id="about-how">
          <h2>How buying works</h2>
          <div className="legal-steps">
            <div className="legal-step">
              <div className="legal-step-number">1</div>
              <div>
                <strong>Pick an item and pay in rupees</strong>
                <p>
                  Pay from your wallet balance if you have one, otherwise JazzCash charges the amount at
                  checkout. Prefer WhatsApp? Order there and pay by Easypaisa or bank transfer.
                </p>
              </div>
            </div>
            <div className="legal-step">
              <div className="legal-step-number">2</div>
              <div>
                <strong>Get it delivered</strong>
                <p>
                  Most items arrive instantly. The rest arrive in your order chat within the delivery time
                  shown on the listing.
                </p>
              </div>
            </div>
            <div className="legal-step">
              <div className="legal-step-number">3</div>
              <div>
                <strong>Check it works</strong>
                <p>
                  If a key does not activate, a code does not redeem, or an item does not match its
                  description, message us from the order page. We fix it fast or refund you to your wallet.
                </p>
              </div>
            </div>
          </div>
        </section>

        <section className="legal-section" id="about-reviews">
          <h2>Our track record</h2>
          <p>
            Every review on GamesBazaar comes from a delivered order, and buyers can attach photos of
            what they received. Nothing is curated, so the ratings show the store as it actually
            performs.
          </p>
          {hasReviews ? (
            <div className="legal-callout">
              <div>
                <strong>
                  <span aria-hidden="true">{renderStars(summary.average)}</span>{' '}
                  {summary.average.toFixed(1)} average from {summary.count}{' '}
                  {summary.count === 1 ? 'review' : 'reviews'}
                </strong>
                <div>
                  Read every one of them on the <Link href="/reviews">reviews page</Link>.
                </div>
              </div>
            </div>
          ) : (
            <p>
              Read them on the <Link href="/reviews">reviews page</Link>.
            </p>
          )}
        </section>

        <section className="legal-section" id="about-contact">
          <h2>How to reach us</h2>
          <p>
            WhatsApp is the fastest way to reach the store. For anything about an existing order,
            message from the order page so the details are already in front of us.
          </p>
          <div className="legal-contact-card about-facts">
            <div className="legal-contact-row">
              <span>
                <strong>WhatsApp / phone:</strong>{' '}
                <a href={whatsappUrl()} target="_blank" rel="noopener noreferrer">{BUSINESS.phoneDisplay}</a>
              </span>
            </div>
            <div className="legal-contact-row">
              <span>
                <strong>Email:</strong>{' '}
                <a href={`mailto:${BUSINESS.email}`}>{BUSINESS.email}</a>
              </span>
            </div>
            <div className="legal-contact-row">
              <span>
                <strong>Help centre:</strong>{' '}
                <Link href="/support">FAQ and support tickets</Link>
              </span>
            </div>
            <div className="legal-contact-row">
              <span>
                <strong>Social:</strong>{' '}
                <a href={BUSINESS.instagram} target="_blank" rel="noopener noreferrer">Instagram</a>
                {' '}&middot;{' '}
                <a href={BUSINESS.facebook} target="_blank" rel="noopener noreferrer">Facebook</a>
              </span>
            </div>
            <div className="legal-contact-row">
              <span>
                <strong>Location:</strong> {BUSINESS.city}, {BUSINESS.country}
              </span>
            </div>
          </div>
        </section>

        <section className="legal-section" id="about-fine-print">
          <h2>The fine print</h2>
          <p>
            Our <Link href="/terms-of-service">Terms of Service</Link> and{' '}
            <Link href="/privacy-policy">Privacy Policy</Link> spell out how orders, refunds and your
            data are handled. GamesBazaar operates under the laws of the Islamic Republic of Pakistan.
          </p>
        </section>
      </div>
    </div>
  );
}

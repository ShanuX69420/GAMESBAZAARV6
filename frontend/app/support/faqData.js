// Shared between the client FAQ accordion (page.js) and the server layout,
// which emits this same content as FAQPage JSON-LD — keep them identical so
// the structured data always matches what visitors actually see.
export const FAQ_ITEMS = [
  {
    category: 'Buying',
    questions: [
      {
        q: 'How do I buy something on GamesBazaar?',
        a: 'Browse games, find a listing you like, click "Buy Now", and pay — from your wallet balance or directly at checkout. Many items are delivered instantly; the rest arrive in your order chat within the delivery time shown on the listing.',
      },
      {
        q: 'What if I don\'t receive my order?',
        a: 'If your order isn\'t delivered within the expected time, message us from the order page — it goes straight to our team. We\'ll deliver it, fix it, or refund you in full.',
      },
      {
        q: 'Can I get a refund?',
        a: 'Yes! If your order isn\'t delivered or the item doesn\'t match the description, message us from the order page and we\'ll sort it out. Refunds are credited back instantly as wallet balance.',
      },
    ],
  },
  {
    category: 'Payments & Wallet',
    questions: [
      {
        q: 'How do I add funds to my wallet?',
        a: 'You don\'t need a wallet balance to buy — checkout can charge your JazzCash account directly. To add funds anyway, go to your Wallet page and click "Add Funds" — pay instantly with JazzCash, or message us on WhatsApp (0371 2101998) to pay via Easypaisa or bank transfer. Your wallet is credited within minutes.',
      },
      {
        q: 'How do I withdraw money from my wallet?',
        a: 'Go to your Wallet page and request a withdrawal (minimum PKR 500). Provide your account details and we\'ll process it within 1-2 business days.',
      },
      {
        q: 'Are my payments secure?',
        a: 'Absolutely. Every payment goes through our secure checkout, and if anything is wrong with your order we fix it or refund you — refunds are credited back to your wallet instantly.',
      },
    ],
  },
  {
    category: 'Account',
    questions: [
      {
        q: 'How do I change my username?',
        a: 'Go to Settings and update your username. Note: you can only change it once every 90 days.',
      },
      {
        q: 'How do I change my email?',
        a: 'Go to Settings and request an email change. We\'ll send verification codes to both your current and new email for security.',
      },
      {
        q: 'I forgot my password. What do I do?',
        a: 'Click "Forgot Password?" on the login page. We\'ll send a reset code to your registered email address.',
      },
    ],
  },
  {
    category: 'Safety',
    questions: [
      {
        q: 'How do I report a scam or suspicious user?',
        a: 'You can report any listing or user directly from their profile or listing page. Click the report button and select a reason. Our team reviews all reports.',
      },
      {
        q: 'What should I do if someone asks me to trade outside GamesBazaar?',
        a: 'Never trade outside the platform. All transactions must go through GamesBazaar to ensure you\'re protected. Report anyone who suggests off-platform trading.',
      },
    ],
  },
];

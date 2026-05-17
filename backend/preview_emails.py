"""
Render email templates into static HTML files for preview.
Run: python manage.py shell < preview_emails.py
"""
import os
import sys

# Setup Django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'gamesbazaar.settings')
os.environ.setdefault('DJANGO_ENV', 'development')

import django
django.setup()

from django.template.loader import render_to_string

PREVIEW_DIR = os.path.join(os.path.dirname(__file__), '_email_previews')
os.makedirs(PREVIEW_DIR, exist_ok=True)


def save(name, html):
    path = os.path.join(PREVIEW_DIR, f'{name}.html')
    with open(path, 'w', encoding='utf-8') as f:
        f.write(html)
    print(f'  Saved: {path}')


# 1. Order Placed (seller)
save('order_placed', render_to_string('email/transactional.html', {
    'email_subject': 'New Order Received',
    'username': 'ProSeller',
    'message_body': 'A new order has been placed.',
    'detail_rows': [
        ('Order', '#GB-7X2K9'),
        ('Listing', 'Valorant Premium Account — Gold Rank'),
        ('Quantity', '1'),
        ('Order Total', 'PKR 2500'),
    ],
    'status_text': 'New Order',
    'status_class': 'info',
}))

# 2. Order Delivered (buyer)
save('order_delivered', render_to_string('email/transactional.html', {
    'email_subject': 'Order Delivered',
    'username': 'HappyBuyer',
    'message_body': 'Your order has been delivered. Open the order page to review the delivery details.',
    'detail_rows': [
        ('Order', '#GB-7X2K9'),
        ('Listing', 'Valorant Premium Account — Gold Rank'),
        ('Quantity', '1'),
    ],
    'status_text': 'Delivered',
    'status_class': 'success',
}))

# 3. Order Completed (seller)
save('order_completed', render_to_string('email/transactional.html', {
    'email_subject': 'Order Completed',
    'username': 'ProSeller',
    'message_body': 'This order has been completed.',
    'detail_rows': [
        ('Order', '#GB-7X2K9'),
        ('Listing', 'Valorant Premium Account — Gold Rank'),
        ('Quantity', '1'),
    ],
    'status_text': 'Completed',
    'status_class': 'success',
}))

# 4. Order Disputed (seller)
save('order_disputed', render_to_string('email/transactional.html', {
    'email_subject': 'Order Disputed',
    'username': 'ProSeller',
    'message_body': 'A dispute has been opened for this order.',
    'detail_rows': [
        ('Order', '#GB-7X2K9'),
        ('Listing', 'Valorant Premium Account — Gold Rank'),
        ('Quantity', '1'),
    ],
    'status_text': 'Disputed',
    'status_class': 'warning',
}))

# 5. Top-up Approved
save('topup_approved', render_to_string('email/transactional.html', {
    'email_subject': 'Top-up Approved',
    'username': 'HappyBuyer',
    'message_body': 'Your top-up request for PKR 5000 has been approved.',
    'detail_rows': [('Amount', 'PKR 5000')],
    'status_text': 'Approved',
    'status_class': 'success',
    'extra_message': 'The funds have been credited to your wallet.',
}))

# 6. Withdrawal Rejected (with admin note)
save('withdraw_rejected', render_to_string('email/transactional.html', {
    'email_subject': 'Withdrawal Rejected',
    'username': 'ProSeller',
    'message_body': 'Your withdrawal request for PKR 3000 was rejected.',
    'detail_rows': [('Amount', 'PKR 3000')],
    'status_text': 'Rejected',
    'status_class': 'danger',
    'admin_note': 'Account details did not match. Please update your payment info and try again.',
    'extra_message': 'The held amount has been returned to your wallet.',
}))

# 7. Top-up Pending
save('topup_pending', render_to_string('email/transactional.html', {
    'email_subject': 'Top-up Request Received',
    'username': 'HappyBuyer',
    'message_body': 'We received your top-up request for PKR 2000.',
    'detail_rows': [('Amount', 'PKR 2000')],
    'status_text': 'Pending Review',
    'status_class': 'warning',
    'extra_message': 'We will email you again when it is approved or rejected.',
}))

# 8. Dispute Resolved — Refund
save('dispute_resolved_refund', render_to_string('email/transactional.html', {
    'email_subject': 'Dispute Result',
    'username': 'HappyBuyer',
    'message_body': 'The dispute for your order was resolved and the order was refunded.',
    'detail_rows': [
        ('Order', '#GB-7X2K9'),
        ('Listing', 'Valorant Premium Account — Gold Rank'),
        ('Quantity', '1'),
    ],
    'status_text': 'Refunded',
    'status_class': 'success',
}))

# 9. Verification Code — Password Reset
save('password_reset', render_to_string('email/verification_code.html', {
    'username': 'HappyBuyer',
    'code': '482917',
    'message_body': 'Use the code below to reset your password.',
}))

# 10. Verification Code — Email Change
save('email_change', render_to_string('email/verification_code.html', {
    'username': 'ProSeller',
    'code': '739251',
    'message_body': 'Use the code below to verify your email change request.',
}))

print(f'\nAll previews saved to: {PREVIEW_DIR}')
print('Open any .html file in a browser to preview.')

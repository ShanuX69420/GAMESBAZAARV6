"""Offline-activation auto-delivery + on-demand Steam Guard codes.

Covers the TOTP generator, instant credential delivery at purchase, the
order-page guard-code endpoint, and the !code chat command.
"""

import base64
from datetime import timedelta
from decimal import Decimal
from unittest.mock import patch

from django.contrib.auth.models import User
from django.core.cache import cache
from django.core.exceptions import ValidationError
from django.test import SimpleTestCase, TestCase, override_settings
from django.utils import timezone
from rest_framework.test import APIClient

from . import guardmail, steamguard
from .models import (
    Category, Game, GameCategory, Listing, Message, Notification,
    OfflineAccount, Order, Wallet,
)
from .services import (
    ENCRYPTED_TEXT_V1_PREFIX,
    ENCRYPTED_TEXT_V2_PREFIX,
    decrypt_sensitive_text,
)
from .views import execute_listing_purchase

# Frozen vector: base64 of b'gamesbazaar-test-secret'. The expected codes
# were produced by this implementation, whose math matches the reference
# Steam Guard implementations (HMAC-SHA1, 30s window, 26-char alphabet) —
# the vector locks the behavior against regressions.
TEST_SECRET = 'Z2FtZXNiYXphYXItdGVzdC1zZWNyZXQ='


class SteamGuardAlgorithmTests(SimpleTestCase):
    def test_frozen_vector(self):
        self.assertEqual(steamguard.generate_code(TEST_SECRET, 1700000000), 'KVKMV')
        self.assertEqual(steamguard.generate_code(TEST_SECRET, 1700000030), '4QK4G')

    def test_code_stable_within_window_and_rotates_across(self):
        window_start = 1700000010  # 56666667 * 30
        self.assertEqual(
            steamguard.generate_code(TEST_SECRET, window_start),
            steamguard.generate_code(TEST_SECRET, window_start + 29),
        )
        self.assertNotEqual(
            steamguard.generate_code(TEST_SECRET, window_start),
            steamguard.generate_code(TEST_SECRET, window_start + 30),
        )

    def test_code_shape(self):
        code = steamguard.generate_code(TEST_SECRET)
        self.assertEqual(len(code), 5)
        self.assertTrue(all(c in '23456789BCDFGHJKMNPQRTVWXY' for c in code))

    def test_invalid_secret_raises_value_error(self):
        with self.assertRaises(ValueError):
            steamguard.generate_code('not base64 !!!')

    def test_empty_secret_raises_value_error(self):
        # decrypt_sensitive_text returns '' for a value it cannot decrypt
        # (key mishap, blank paste) — that must fail loudly, never silently
        # become a plausible-looking wrong code.
        for empty in ('', '   '):
            with self.assertRaises(ValueError):
                steamguard.generate_code(empty)

    def test_seconds_remaining(self):
        self.assertEqual(steamguard.seconds_remaining(1700000012), 28)
        self.assertEqual(steamguard.seconds_remaining(1700000010), 30)

    def test_command_matching(self):
        for text in ('!code', ' !CODE ', '!guard', '!2fa', '! code', '!code!', '!code.'):
            self.assertTrue(steamguard.is_guard_command(text), text)
        for text in ('code', 'guard', '!codeword', 'need !code please', '', None, '!'):
            self.assertFalse(steamguard.is_guard_command(text), text)


STEAM_GUARD_EMAIL_BODY = """\
Dear gbacct1,

It looks like you are trying to log in from a new device. As an added
security measure, you will need to enter the Steam Guard code below.

Here is the Steam Guard code you need to log in to account gbacct1:

H7K2M

If this wasn't you, change your password.

The Steam Support Team
"""


class GuardMailParserTests(SimpleTestCase):
    def test_extracts_code_for_named_account(self):
        self.assertEqual(
            guardmail.extract_code(STEAM_GUARD_EMAIL_BODY, 'gbacct1'), 'H7K2M')

    def test_login_match_is_case_insensitive(self):
        self.assertEqual(
            guardmail.extract_code(STEAM_GUARD_EMAIL_BODY, 'GBAcct1'), 'H7K2M')

    def test_other_accounts_email_is_ignored(self):
        self.assertIsNone(
            guardmail.extract_code(STEAM_GUARD_EMAIL_BODY, 'someoneelse'))

    def test_body_without_code_returns_none(self):
        self.assertIsNone(
            guardmail.extract_code('Dear gbacct1, welcome to Steam!', 'gbacct1'))

    def test_five_char_uppercase_login_is_not_mistaken_for_code(self):
        body = (
            'Dear ABCDE,\n\n'
            'ABCDE\n\n'  # the login alone on a line, before the code
            'Here is the Steam Guard code you need to log in to account ABCDE:\n\n'
            'H7K2M\n'
        )
        self.assertEqual(guardmail.extract_code(body, 'ABCDE'), 'H7K2M')

    def test_only_login_code_subjects_are_parseable(self):
        # The mailbox is the account's second factor: only the login-code
        # template may ever be parsed, security emails never.
        for subject in (
            'Your Steam account: Access from new computer',
            'Your Steam account: Access from new web browser',
            'Your Steam Guard code',
        ):
            self.assertTrue(guardmail.is_login_code_subject(subject), subject)
        for subject in (
            'Your Steam account: Email change request',
            'Your Steam account: Password change request',
            'Your Steam account: Recovery request',
            'Thank you for your purchase!',
            '',
            None,
        ):
            self.assertFalse(guardmail.is_login_code_subject(subject), subject)


class OfflineAccountTestBase(TestCase):
    def setUp(self):
        cache.clear()  # guard-code cooldowns must not leak between tests
        self.client = APIClient()
        self.buyer = User.objects.create_user(username='oabuyer', password='pw12345678')
        self.seller = User.objects.create_user(username='oaseller', password='pw12345678')
        self.seller.profile.seller_status = 'approved'
        self.seller.profile.save(update_fields=['seller_status'])
        Wallet.objects.filter(user=self.buyer).update(balance=Decimal('50000.00'))

        game = Game.objects.create(name='OA Game', slug='oa-game')
        category = Category.objects.create(name='Offline Activation', slug='offline-activation')
        self.game_category = GameCategory.objects.create(game=game, category=category)

        self.account = OfflineAccount.objects.create(
            label='OA Game — account 1',
            login='steamuser1',
            password='hunter2-plaintext',
            shared_secret=TEST_SECRET,
        )
        self.listing = Listing.objects.create(
            seller=self.seller,
            game_category=self.game_category,
            title='OA Game (Offline Activation)',
            price=Decimal('1500.00'),
            quantity=None,
            status='active',
            offline_account=self.account,
        )
        self.client.force_authenticate(user=self.buyer)

    def buy(self, listing=None):
        order, error = execute_listing_purchase(
            buyer=self.buyer,
            listing_id=(listing or self.listing).pk,
            quantity=1,
        )
        self.assertIsNone(error)
        return order


class OfflineAccountModelTests(OfflineAccountTestBase):
    def test_secrets_encrypted_at_rest(self):
        self.account.refresh_from_db()
        for stored in (self.account.password, self.account.shared_secret):
            self.assertTrue(
                stored.startswith(ENCRYPTED_TEXT_V1_PREFIX)
                or stored.startswith(ENCRYPTED_TEXT_V2_PREFIX)
            )
        self.assertEqual(decrypt_sensitive_text(self.account.password),
                         'hunter2-plaintext')

    def test_resave_keeps_encrypted_values_readable(self):
        self.account.refresh_from_db()
        self.account.save()
        self.assertEqual(decrypt_sensitive_text(self.account.password),
                         'hunter2-plaintext')
        self.assertEqual(decrypt_sensitive_text(self.account.shared_secret),
                         TEST_SECRET)

    def test_current_code_matches_generator(self):
        self.account.refresh_from_db()
        self.assertEqual(len(self.account.current_code()), 5)


class OfflinePurchaseTests(OfflineAccountTestBase):
    def test_purchase_delivers_credentials_instantly(self):
        order = self.buy()
        self.assertEqual(order.status, 'delivered')
        self.assertTrue(order.was_auto_delivery)
        self.assertIsNotNone(order.delivered_at)

        note = decrypt_sensitive_text(order.delivery_note)
        self.assertIn('steamuser1', note)
        self.assertIn('hunter2-plaintext', note)
        self.assertIn('«Get Steam Guard code»', note)
        self.assertNotIn('!code', note)

        delivery_messages = Message.objects.filter(
            conversation=order.conversation, message_type='delivery',
        )
        self.assertEqual(delivery_messages.count(), 1)

        # Evergreen: nothing consumed, listing stays active.
        self.listing.refresh_from_db()
        self.assertIsNone(self.listing.quantity)
        self.assertEqual(self.listing.status, 'active')

    def test_second_buyer_gets_same_account(self):
        first = self.buy()
        buyer2 = User.objects.create_user(username='oabuyer2', password='pw12345678')
        Wallet.objects.filter(user=buyer2).update(balance=Decimal('50000.00'))
        second, error = execute_listing_purchase(
            buyer=buyer2, listing_id=self.listing.pk, quantity=1,
        )
        self.assertIsNone(error)
        self.assertEqual(
            decrypt_sensitive_text(first.delivery_note),
            decrypt_sensitive_text(second.delivery_note),
        )

    def test_disabled_account_falls_back_to_manual(self):
        self.account.enabled = False
        self.account.save()
        order = self.buy()
        self.assertEqual(order.status, 'pending')
        self.assertFalse(order.was_auto_delivery)
        self.assertEqual(order.delivery_note, '')


class GuardCodeEndpointTests(OfflineAccountTestBase):
    def request_code(self, order):
        return self.client.post(f'/api/orders/{order.pk}/guard-code/')

    def test_buyer_gets_current_code_and_chat_message(self):
        order = self.buy()
        response = self.request_code(order)
        self.assertEqual(response.status_code, 200)
        code = response.data['code']
        self.account.refresh_from_db()
        self.assertEqual(code, self.account.current_code())
        self.assertGreaterEqual(response.data['valid_for'], 1)
        self.assertLessEqual(response.data['valid_for'], 30)

        guard_messages = Message.objects.filter(
            conversation=order.conversation, system_event='guard_code',
        )
        self.assertEqual(guard_messages.count(), 1)
        self.assertIn(code, guard_messages.first().content)

    def test_code_can_only_be_issued_once(self):
        order = self.buy()
        self.assertEqual(self.request_code(order).status_code, 200)

        response = self.request_code(order)
        self.assertEqual(response.status_code, 400)
        self.assertIn('already received', response.data['error'])
        # No second code posted; the allowance is spent.
        self.assertEqual(
            Message.objects.filter(
                conversation=order.conversation, system_event='guard_code',
            ).count(),
            1,
        )
        order.refresh_from_db()
        self.assertIsNotNone(order.guard_code_issued_at)

    def test_availability_flips_off_once_used(self):
        order = self.buy()
        detail = self.client.get(f'/api/orders/{order.pk}/').data
        self.assertTrue(detail['guard_code_available'])
        self.assertFalse(detail['guard_code_used'])

        self.request_code(order)
        detail = self.client.get(f'/api/orders/{order.pk}/').data
        self.assertFalse(detail['guard_code_available'])
        self.assertTrue(detail['guard_code_used'])

    def test_seller_cannot_request(self):
        order = self.buy()
        self.client.force_authenticate(user=self.seller)
        self.assertEqual(self.request_code(order).status_code, 404)

    def test_pending_order_rejected(self):
        self.account.enabled = False
        self.account.save()
        order = self.buy()
        self.account.enabled = True
        self.account.save()
        response = self.request_code(order)
        self.assertEqual(response.status_code, 400)
        self.assertIn('delivered', response.data['error'])

    def test_completed_order_still_eligible(self):
        order = self.buy()
        Order.objects.filter(pk=order.pk).update(status='completed')
        order.refresh_from_db()
        self.assertEqual(self.request_code(order).status_code, 200)

    def test_window_expiry(self):
        order = self.buy()
        Order.objects.filter(pk=order.pk).update(
            delivered_at=timezone.now() - timedelta(days=8),
        )
        order.refresh_from_db()
        response = self.request_code(order)
        self.assertEqual(response.status_code, 400)
        self.assertIn('window', response.data['error'])

        # 0 = no limit
        self.account.code_window_days = 0
        self.account.save()
        self.assertEqual(self.request_code(order).status_code, 200)

    def test_listing_without_account_rejected(self):
        plain = Listing.objects.create(
            seller=self.seller,
            game_category=self.game_category,
            title='Plain listing',
            price=Decimal('500.00'),
            quantity=None,
            status='active',
        )
        order, error = execute_listing_purchase(
            buyer=self.buyer, listing_id=plain.pk, quantity=1,
        )
        self.assertIsNone(error)
        Order.objects.filter(pk=order.pk).update(status='delivered')
        order.refresh_from_db()
        self.assertEqual(self.request_code(order).status_code, 400)

    def test_order_detail_exposes_availability_to_buyer_only(self):
        order = self.buy()
        response = self.client.get(f'/api/orders/{order.pk}/')
        self.assertTrue(response.data['guard_code_available'])

        self.client.force_authenticate(user=self.seller)
        response = self.client.get(f'/api/orders/{order.pk}/')
        self.assertFalse(response.data['guard_code_available'])


class GuardCommandTests(OfflineAccountTestBase):
    def send_chat(self, order, text):
        return self.client.post(
            f'/api/chat/{order.conversation_id}/send/', {'content': text},
            format='json',
        )

    def guard_messages(self, order):
        return Message.objects.filter(
            conversation_id=order.conversation_id, system_event='guard_code',
        )

    def test_code_command_posts_current_code(self):
        order = self.buy()
        response = self.send_chat(order, '!code')
        self.assertEqual(response.status_code, 201)
        messages = self.guard_messages(order)
        self.assertEqual(messages.count(), 1)
        self.account.refresh_from_db()
        self.assertIn(self.account.current_code(), messages.first().content)

    def test_guard_alias_works(self):
        order = self.buy()
        self.send_chat(order, '!guard')
        self.assertEqual(self.guard_messages(order).count(), 1)

    def test_normal_message_is_ignored(self):
        order = self.buy()
        self.send_chat(order, 'hello, is this account still available?')
        self.assertEqual(self.guard_messages(order).count(), 0)

    def test_command_from_seller_is_ignored(self):
        order = self.buy()
        self.client.force_authenticate(user=self.seller)
        self.send_chat(order, '!code')
        self.assertEqual(self.guard_messages(order).count(), 0)

    def test_expired_window_gets_explanation_not_code(self):
        order = self.buy()
        Order.objects.filter(pk=order.pk).update(
            delivered_at=timezone.now() - timedelta(days=8),
        )
        self.send_chat(order, '!code')
        messages = self.guard_messages(order)
        self.assertEqual(messages.count(), 1)
        self.assertIn('window', messages.first().content)

    def test_command_after_code_used_explains_already_issued(self):
        order = self.buy()
        self.assertEqual(
            self.client.post(f'/api/orders/{order.pk}/guard-code/').status_code,
            200,
        )
        # The one code is spent — !code now explains instead of re-posting it.
        self.send_chat(order, '!code')
        contents = [m.content for m in self.guard_messages(order)]
        self.assertEqual(len(contents), 2)
        self.assertTrue(any('already received' in c for c in contents))


# Force-unset the mailbox settings: the developer's real .env may hold live
# IMAP credentials, and tests must never touch the real mailbox (the patched
# tests bypass config; the unconfigured test depends on it being empty).
@override_settings(GUARD_EMAIL_IMAP_HOST='', GUARD_EMAIL_IMAP_USER='',
                   GUARD_EMAIL_IMAP_PASSWORD='')
class EmailGuardTests(OfflineAccountTestBase):
    """guard_type='email': codes come from the shared mailbox, not TOTP."""

    def setUp(self):
        super().setUp()
        self.account.guard_type = 'email'
        self.account.shared_secret = ''
        self.account.save()

    def request_code(self, order):
        return self.client.post(f'/api/orders/{order.pk}/guard-code/')

    def test_model_validation(self):
        self.account.full_clean()  # email type needs no shared_secret
        totp = OfflineAccount(
            label='x', login='y', password='z', guard_type='totp',
        )
        with self.assertRaises(ValidationError):
            totp.full_clean()

    def test_purchase_still_delivers_credentials(self):
        order = self.buy()
        self.assertEqual(order.status, 'delivered')

    @patch('core.guardmail.fetch_latest_code', return_value='H7K2M')
    def test_code_fetched_from_mailbox(self, fetch):
        order = self.buy()
        response = self.request_code(order)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['code'], 'H7K2M')
        self.assertEqual(response.data['label'], 'Steam Guard code')
        self.assertNotIn('valid_for', response.data)
        fetch.assert_called_once_with(self.account)

        messages = Message.objects.filter(
            conversation=order.conversation, system_event='guard_code',
        )
        self.assertEqual(messages.count(), 1)
        # The delivered message carries the "re-enter the same code" guidance.
        self.assertIn('H7K2M', messages.first().content)
        self.assertIn('same code', messages.first().content)

    @patch('core.guardmail.fetch_latest_code', return_value='H7K2M')
    def test_email_code_issued_only_once(self, fetch):
        order = self.buy()
        self.assertEqual(self.request_code(order).status_code, 200)
        response = self.request_code(order)
        self.assertEqual(response.status_code, 400)
        self.assertIn('already received', response.data['error'])
        # Second request must not re-read the mailbox or re-post a code.
        fetch.assert_called_once_with(self.account)
        self.assertEqual(
            Message.objects.filter(
                conversation=order.conversation, system_event='guard_code',
            ).count(),
            1,
        )

    @patch('core.guardmail.fetch_latest_code', return_value=None)
    def test_pending_does_not_consume_the_single_code(self, fetch):
        order = self.buy()
        response = self.request_code(order)
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.data['pending'])
        self.assertEqual(
            Message.objects.filter(
                conversation=order.conversation, system_event='guard_code',
            ).count(),
            0,
        )
        order.refresh_from_db()
        self.assertIsNone(order.guard_code_issued_at)
        # A no-email-yet result leaves the one allowance intact — once the
        # login email lands, the real code still delivers.
        fetch.return_value = 'H7K2M'
        cache.delete(f'core:guard-code:fetch:{self.account.pk}')  # step past the fetch cooldown
        response = self.request_code(order)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['code'], 'H7K2M')

    @patch('core.guardmail.fetch_latest_code',
           side_effect=guardmail.GuardMailError('login failed'))
    def test_mailbox_failure_alerts_seller_once(self, fetch):
        order = self.buy()
        response = self.request_code(order)
        self.assertEqual(response.status_code, 400)
        self.assertIn('notified', response.data['error'])
        alerts = Notification.objects.filter(
            recipient=self.seller, notification_type='fulfillment_alert',
        )
        self.assertEqual(alerts.count(), 1)
        # A second failure within the hour must not re-alert. (Clear only
        # the fetch cooldown so the retry really reaches the mailbox again.)
        cache.delete(f'core:guard-code:fetch:{self.account.pk}')
        self.request_code(order)
        self.assertEqual(alerts.count(), 1)
        self.assertEqual(fetch.call_count, 2)

    @patch('core.guardmail.fetch_latest_code', return_value=None)
    def test_rapid_retries_hit_mailbox_only_once(self, fetch):
        # The shared mailbox serves every email-guard account — rapid
        # retries (order-page polling, !code spam) must not each open IMAP.
        order = self.buy()
        self.assertTrue(self.request_code(order).data['pending'])
        self.assertTrue(self.request_code(order).data['pending'])
        fetch.assert_called_once_with(self.account)

    @patch('core.guardmail.fetch_latest_code', return_value=None)
    def test_command_explains_login_first(self, fetch):
        order = self.buy()
        self.client.post(
            f'/api/chat/{order.conversation_id}/send/', {'content': '!code'},
            format='json',
        )
        messages = Message.objects.filter(
            conversation_id=order.conversation_id, system_event='guard_code',
        )
        self.assertEqual(messages.count(), 1)
        self.assertIn('Start the Steam login', messages.first().content)

    def test_unconfigured_mailbox_fails_gracefully(self):
        # No GUARD_EMAIL_IMAP_* settings in tests — the real fetch raises
        # GuardMailError('guard mailbox is not configured').
        order = self.buy()
        response = self.request_code(order)
        self.assertEqual(response.status_code, 400)
        self.assertIn('notified', response.data['error'])


# Shared mailbox force-unset (same reason as EmailGuardTests): these tests
# prove the account's OWN credentials alone are enough.
@override_settings(GUARD_EMAIL_IMAP_HOST='', GUARD_EMAIL_IMAP_USER='',
                   GUARD_EMAIL_IMAP_PASSWORD='')
class OwnMailboxTests(TestCase):
    """Accounts whose registered mailbox cannot forward (e.g. Rambler)
    carry their own IMAP credentials and are read directly."""

    def make_account(self, **overrides):
        fields = dict(
            label='Rambler acct', platform='steam', login='gbacct1',
            password='acct-pass', guard_type='email',
            mailbox_host='imap.rambler.ru', mailbox_user='acct@rambler.ru',
            mailbox_password='mail-pass',
        )
        fields.update(overrides)
        account = OfflineAccount(**fields)
        account.save()
        return account

    def test_partial_mailbox_config_rejected(self):
        account = OfflineAccount(
            label='x', platform='steam', login='y', password='z',
            guard_type='email', mailbox_host='imap.rambler.ru',
        )
        with self.assertRaises(ValidationError) as ctx:
            account.full_clean()
        self.assertIn('mailbox_user', ctx.exception.message_dict)
        self.assertIn('mailbox_password', ctx.exception.message_dict)

    def test_full_mailbox_config_validates(self):
        self.make_account().full_clean()

    def test_mailbox_password_encrypted_on_save(self):
        account = self.make_account()
        account.refresh_from_db()
        self.assertNotEqual(account.mailbox_password, 'mail-pass')
        self.assertEqual(
            decrypt_sensitive_text(account.mailbox_password), 'mail-pass')

    @patch('core.guardmail.imaplib.IMAP4_SSL')
    def test_fetch_connects_to_the_accounts_own_mailbox(self, imap_cls):
        account = self.make_account()
        conn = imap_cls.return_value
        conn.search.return_value = ('OK', [b''])
        self.assertIsNone(guardmail.fetch_latest_code(account))
        imap_cls.assert_called_once_with(
            'imap.rambler.ru', guardmail.OWN_MAILBOX_PORT,
            timeout=guardmail.IMAP_TIMEOUT_SECONDS)
        conn.login.assert_called_once_with('acct@rambler.ru', 'mail-pass')

    def test_undecryptable_mailbox_password_fails_loudly(self):
        # decrypt_sensitive_text returns '' on a key mishap — that must
        # raise, never silently fall back to the shared mailbox.
        account = self.make_account()
        OfflineAccount.objects.filter(pk=account.pk).update(mailbox_password='')
        account.refresh_from_db()
        with self.assertRaises(guardmail.GuardMailError):
            guardmail.fetch_latest_code(account)


class PlatformMailParserTests(SimpleTestCase):
    """Ubisoft/EA subject vetting and digit-code extraction."""

    def test_ea_login_code_subject_allowed(self):
        self.assertTrue(guardmail.subject_allowed(
            'ea', 'Your EA Security Code is: 869817'))

    def test_ubisoft_code_subject_allowed(self):
        self.assertTrue(guardmail.subject_allowed(
            'ubisoft', 'Your Ubisoft verification code'))

    def test_epic_code_subject_allowed(self):
        self.assertTrue(guardmail.subject_allowed(
            'epic', 'Your Epic Games sign-in code'))

    def test_account_security_subjects_blocked_even_if_they_mention_code(self):
        # The blocklist wins over the allowlist: a password-reset email that
        # also says "code" must NEVER be parsed — relaying it would hand a
        # buyer the account.
        for platform, subject in (
            ('ea', 'Your EA password reset code'),
            ('ea', 'Reset your EA password'),
            ('ubisoft', 'Password change code for your Ubisoft account'),
            ('ubisoft', 'Recover your Ubisoft account'),
            ('epic', 'Your code to remove two-factor authentication'),
            ('epic', 'Epic Games password reset code'),
            ('ea', ''),
            ('ubisoft', None),
        ):
            self.assertFalse(
                guardmail.subject_allowed(platform, subject), (platform, subject))

    def test_extract_code_from_ea_subject(self):
        self.assertEqual(
            guardmail.extract_generic_code(
                'Your EA Security Code is: 869817', 'irrelevant body'),
            '869817')

    def test_extract_code_from_ubisoft_body_line(self):
        body = 'Hello,\n\nYour verification code:\n\n1234\n\nThe Ubisoft team\n'
        self.assertEqual(guardmail.extract_generic_code('', body), '1234')

    def test_extract_code_from_epic_body(self):
        body = ('Hi,\n\nHere is your sign-in code:\n\n483920\n\n'
                'The Epic Games team\n')
        self.assertEqual(guardmail.extract_generic_code('', body), '483920')

    def test_no_code_in_marketing_text(self):
        body = ('Big sale! Save 70% until July 20, 2026.\n'
                '© 2026 Electronic Arts Inc.\n')
        self.assertIsNone(guardmail.extract_generic_code('', body))


class UbisoftEaAccountTests(OfflineAccountTestBase):
    """platform='ubisoft'/'ea': email-only guard, matched by guard_email."""

    def setUp(self):
        super().setUp()
        self.ea_account = OfflineAccount.objects.create(
            label='FC 26 — EA account 1',
            platform='ea',
            login='eauser1',
            password='ea-hunter2',
            guard_type='email',
            guard_email='gb.guard+ea1@gmail.com',
        )
        self.ea_listing = Listing.objects.create(
            seller=self.seller,
            game_category=self.game_category,
            title='FC 26 (Offline Activation)',
            price=Decimal('2000.00'),
            quantity=None,
            status='active',
            offline_account=self.ea_account,
        )

    def test_validation_rules(self):
        self.ea_account.full_clean()  # valid as created
        with self.assertRaises(ValidationError):
            OfflineAccount(
                label='x', platform='ubisoft', login='y', password='z',
                guard_type='totp', shared_secret=TEST_SECRET,
            ).full_clean()  # non-Steam platforms are email-only
        with self.assertRaises(ValidationError):
            OfflineAccount(
                label='x', platform='ea', login='y', password='z',
                guard_type='email', guard_email='',
            ).full_clean()  # guard_email required off-Steam

    def test_purchase_delivers_platform_wording(self):
        order = self.buy(self.ea_listing)
        self.assertEqual(order.status, 'delivered')
        note = decrypt_sensitive_text(order.delivery_note)
        self.assertIn('eauser1', note)
        self.assertIn('EA security code', note)
        self.assertNotIn('!code', note)

    @patch('core.guardmail.fetch_latest_code', return_value='869817')
    def test_code_and_label_delivered(self, fetch):
        order = self.buy(self.ea_listing)
        detail = self.client.get(f'/api/orders/{order.pk}/').data
        self.assertEqual(detail['guard_code_label'], 'EA security code')

        response = self.client.post(f'/api/orders/{order.pk}/guard-code/')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['code'], '869817')
        self.assertEqual(response.data['label'], 'EA security code')
        fetch.assert_called_once_with(self.ea_account)

        message = Message.objects.filter(
            conversation=order.conversation, system_event='guard_code',
        ).first()
        self.assertTrue(message.content.startswith('869817\n'))

    @patch('core.guardmail.fetch_latest_code', return_value=None)
    def test_pending_message_names_the_platform(self, fetch):
        order = self.buy(self.ea_listing)
        response = self.client.post(f'/api/orders/{order.pk}/guard-code/')
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.data['pending'])
        self.assertIn('EA', response.data['message'])
        self.assertNotIn('Steam', response.data['message'])


class EpicAccountTests(OfflineAccountTestBase):
    """platform='epic': same email-guard flow as Ubisoft/EA."""

    def setUp(self):
        super().setUp()
        self.epic_account = OfflineAccount.objects.create(
            label='Alan Wake 2 — Epic account 1',
            platform='epic',
            login='epicuser1',
            password='epic-hunter2',
            guard_type='email',
            guard_email='gb.guard+epic1@gmail.com',
        )
        self.epic_listing = Listing.objects.create(
            seller=self.seller,
            game_category=self.game_category,
            title='Alan Wake 2 (Offline Activation)',
            price=Decimal('2500.00'),
            quantity=None,
            status='active',
            offline_account=self.epic_account,
        )

    def test_validation_rules(self):
        self.epic_account.full_clean()  # valid as created
        with self.assertRaises(ValidationError):
            OfflineAccount(
                label='x', platform='epic', login='y', password='z',
                guard_type='totp', shared_secret=TEST_SECRET,
            ).full_clean()  # email-only, like Ubisoft/EA
        with self.assertRaises(ValidationError):
            OfflineAccount(
                label='x', platform='epic', login='y', password='z',
                guard_type='email', guard_email='',
            ).full_clean()

    def test_purchase_delivers_platform_wording(self):
        order = self.buy(self.epic_listing)
        self.assertEqual(order.status, 'delivered')
        note = decrypt_sensitive_text(order.delivery_note)
        self.assertIn('epicuser1', note)
        self.assertIn('Epic Games security code', note)
        self.assertNotIn('!code', note)

    @patch('core.guardmail.fetch_latest_code', return_value='483920')
    def test_code_and_label_delivered(self, fetch):
        order = self.buy(self.epic_listing)
        detail = self.client.get(f'/api/orders/{order.pk}/').data
        self.assertEqual(detail['guard_code_label'], 'Epic Games security code')

        response = self.client.post(f'/api/orders/{order.pk}/guard-code/')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['code'], '483920')
        self.assertEqual(response.data['label'], 'Epic Games security code')
        fetch.assert_called_once_with(self.epic_account)

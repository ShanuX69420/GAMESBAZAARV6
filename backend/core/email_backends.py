import smtplib

import dkim
from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
from django.core.mail.backends.smtp import EmailBackend as SMTPEmailBackend
from django.core.mail.message import sanitize_address


class DKIMSMTPEmailBackend(SMTPEmailBackend):
    """SMTP backend that signs outgoing messages with the app's DKIM key."""

    def _send(self, email_message):
        if not email_message.recipients():
            return False

        encoding = email_message.encoding or settings.DEFAULT_CHARSET
        from_email = sanitize_address(email_message.from_email, encoding)
        recipients = [
            sanitize_address(addr, encoding) for addr in email_message.recipients()
        ]
        try:
            message = email_message.message()
            message_bytes = message.as_bytes(linesep='\r\n')
            signed_message = self._dkim_sign(message_bytes)
            self.connection.sendmail(from_email, recipients, signed_message)
        except (
            dkim.DKIMException,
            ImproperlyConfigured,
            OSError,
            UnicodeError,
            smtplib.SMTPException,
        ):
            if not self.fail_silently:
                raise
            return False
        return True

    def _dkim_sign(self, message_bytes):
        selector = getattr(settings, 'DKIM_SELECTOR', '').strip()
        domain = getattr(settings, 'DKIM_DOMAIN', '').strip()
        private_key = self._dkim_private_key()

        if not selector or not domain or not private_key:
            raise ImproperlyConfigured(
                'DKIM_SELECTOR, DKIM_DOMAIN, and DKIM_PRIVATE_KEY or '
                'DKIM_PRIVATE_KEY_PATH are required for DKIMSMTPEmailBackend.'
            )

        signature = dkim.sign(
            message_bytes,
            selector=selector.encode('ascii'),
            domain=domain.encode('ascii'),
            privkey=private_key,
            include_headers=[
                b'from',
                b'to',
                b'subject',
                b'date',
                b'message-id',
                b'mime-version',
                b'content-type',
            ],
            canonicalize=(b'relaxed', b'relaxed'),
        )
        return signature + message_bytes

    def _dkim_private_key(self):
        private_key = getattr(settings, 'DKIM_PRIVATE_KEY', '').strip()
        if private_key:
            return private_key.replace('\\n', '\n').encode('ascii')

        private_key_path = getattr(settings, 'DKIM_PRIVATE_KEY_PATH', '').strip()
        if not private_key_path:
            return b''

        with open(private_key_path, 'rb') as key_file:
            return key_file.read()

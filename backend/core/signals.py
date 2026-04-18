from django.db.models.signals import post_save
from django.dispatch import receiver
from django.conf import settings
from .models import UserProfile, Wallet


@receiver(post_save, sender=settings.AUTH_USER_MODEL)
def create_user_profile_and_wallet(sender, instance, created, **kwargs):
    """Automatically create a UserProfile and Wallet when a User is created."""
    if created:
        UserProfile.objects.get_or_create(user=instance)
        Wallet.objects.get_or_create(user=instance)

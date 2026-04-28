from django.core.cache import cache
from django.db.models.signals import post_delete, post_save
from django.dispatch import receiver
from django.conf import settings
from .models import Listing, Order, Review, UserProfile, Wallet


@receiver(post_save, sender=settings.AUTH_USER_MODEL)
def create_user_profile_and_wallet(sender, instance, created, **kwargs):
    """Automatically create a UserProfile and Wallet when a User is created."""
    if created:
        UserProfile.objects.get_or_create(user=instance)
        Wallet.objects.get_or_create(user=instance)


def invalidate_seller_dashboard(user_id):
    if user_id:
        cache.delete(f'seller-dashboard:v1:{user_id}')


@receiver([post_save, post_delete], sender=Order)
def invalidate_seller_dashboard_for_order(sender, instance, **kwargs):
    invalidate_seller_dashboard(instance.seller_id)


@receiver([post_save, post_delete], sender=Review)
def invalidate_seller_dashboard_for_review(sender, instance, **kwargs):
    invalidate_seller_dashboard(instance.seller_id)


@receiver([post_save, post_delete], sender=Listing)
def invalidate_seller_dashboard_for_listing(sender, instance, **kwargs):
    invalidate_seller_dashboard(instance.seller_id)

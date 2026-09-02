from django.core.cache import cache
from django.db.models.signals import post_delete, post_save, pre_delete
from django.dispatch import receiver
from django.conf import settings
from .models import Listing, Order, Review, UserProfile, Wallet


@receiver(pre_delete, sender=Listing)
def record_listing_retirement(sender, instance, **kwargs):
    """Every deleted listing leaves a RetiredListing behind so its URL can
    redirect instead of 404. pre_delete (not post_delete) because the snapshot
    needs the game/category rows, which a cascade removes right after. Having a
    listener here also turns QuerySet.delete() into per-object deletes, so the
    seeding tools' bulk deletes leave records too."""
    from .listing_lifecycle import snapshot_retirement

    snapshot_retirement(instance)


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

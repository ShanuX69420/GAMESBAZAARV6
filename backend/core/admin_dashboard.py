"""
Custom Django admin site with an analytics dashboard.

Replaces the default admin site to add a rich analytics dashboard
on the index page, with live KPI cards, charts, and activity feeds.
"""
from datetime import timedelta

from django.contrib import admin
from django.contrib.admin import AdminSite
from django.db.models import Count, Sum, Avg, Q, F
from django.db.models.functions import TruncDate
from django.http import JsonResponse
from django.urls import path
from django.utils import timezone


class GamesBazaarAdminSite(AdminSite):
    site_header = '🎮 GamesBazaar Admin'
    site_title = 'GamesBazaar'
    index_title = 'Dashboard'
    index_template = 'admin/dashboard_index.html'

    def get_urls(self):
        custom = [
            path(
                'dashboard/stats/',
                self.admin_view(self.dashboard_stats_view),
                name='dashboard_stats',
            ),
            path(
                'core/conversation/<int:conversation_id>/chatbox/',
                self.admin_view(self.conversation_chatbox_view),
                name='conversation_chatbox',
            ),
            path(
                'core/message/<int:message_id>/image/',
                self.admin_view(self.conversation_message_image_view),
                name='conversation_message_image',
            ),
        ]
        return custom + super().get_urls()

    # ── Conversation Chatbox ────────────────────────────────────────

    def _can_view_conversation(self, user):
        return user.is_superuser or user.has_perm('core.view_conversation')

    def _can_send_admin_message(self, user):
        return user.is_superuser or user.has_perm('core.add_message')

    def conversation_chatbox_view(self, request, conversation_id):
        """Render a modern chatbox for a conversation, and handle admin messages."""
        from django.core.exceptions import PermissionDenied
        from django.shortcuts import get_object_or_404, render, redirect
        from core.models import Conversation, Message

        can_view_conversation = self._can_view_conversation(request.user)
        if not can_view_conversation:
            raise PermissionDenied

        can_send_admin_message = self._can_send_admin_message(request.user)

        conversation = get_object_or_404(
            Conversation.objects.prefetch_related('participants', 'messages__sender'),
            pk=conversation_id,
        )
        participants = list(conversation.participants.all())
        messages_list = list(conversation.messages.select_related('sender').all())

        # Try to find the related order (if opened from order page)
        order = None
        order_id = request.GET.get('order')
        if order_id:
            from core.models import Order
            order = Order.objects.filter(pk=order_id, conversation=conversation).first()
        if not order:
            order = conversation.orders.select_related('buyer', 'seller').first()

        alert_message = None
        alert_type = None

        if request.method == 'POST':
            if not can_send_admin_message:
                raise PermissionDenied

            content = request.POST.get('message', '').strip()
            if content:
                # Add admin to participants if not already there
                if request.user not in participants:
                    conversation.participants.add(request.user)

                Message.objects.create(
                    conversation=conversation,
                    sender=request.user,
                    content=content,
                )
                # Touch updated_at
                conversation.save(update_fields=['updated_at'])

                # Redirect to avoid double-submit (PRG pattern)
                redirect_url = f'{request.path}?sent=1'
                if order_id:
                    redirect_url += f'&order={order_id}'
                return redirect(redirect_url)
            else:
                alert_message = 'Message cannot be empty.'
                alert_type = 'error'

        if request.GET.get('sent') == '1':
            alert_message = 'Message sent successfully as admin.'
            alert_type = 'success'
            # Refresh messages after send
            messages_list = list(conversation.messages.select_related('sender').all())

        context = {
            **self.each_context(request),
            'title': f'Chat — {conversation}',
            'conversation': conversation,
            'participants': participants,
            'messages_list': messages_list,
            'order': order,
            'alert_message': alert_message,
            'alert_type': alert_type,
            'can_send_admin_message': can_send_admin_message,
        }
        return render(request, 'admin/core/conversation_chatbox.html', context)

    def conversation_message_image_view(self, request, message_id):
        """Serve chat message images through admin permissions."""
        from django.core.exceptions import PermissionDenied
        from django.shortcuts import get_object_or_404
        from core.models import Message
        from core.views import private_file_response

        if not self._can_view_conversation(request.user):
            raise PermissionDenied

        message = get_object_or_404(Message, pk=message_id)
        return private_file_response(message.image)

    # ── JSON stats endpoint ─────────────────────────────────────────────

    def dashboard_stats_view(self, request):
        """Return aggregated platform stats as JSON for dashboard widgets."""
        from django.contrib.auth import get_user_model
        from core.models import (
            Order, Listing, UserProfile, Wallet,
            TopUpRequest, Review, Game, Conversation,
            Message,
        )

        User = get_user_model()
        now = timezone.now()

        # Time range from query param
        range_key = request.GET.get('range', '30d')
        range_map = {
            '7d': timedelta(days=7),
            '30d': timedelta(days=30),
            '90d': timedelta(days=90),
            '1y': timedelta(days=365),
            'all': None,
        }
        delta = range_map.get(range_key, timedelta(days=30))
        since = (now - delta) if delta else None

        def _since_filter(field='created_at'):
            if since:
                return Q(**{f'{field}__gte': since})
            return Q()

        # ── Core KPIs ───────────────────────────────────────────────────

        total_users = User.objects.count()
        new_users = User.objects.filter(_since_filter('date_joined')).count() if since else total_users

        total_sellers = UserProfile.objects.filter(seller_status='approved').count()
        pending_sellers = UserProfile.objects.filter(seller_status='pending').count()

        total_listings = Listing.objects.count()
        active_listings = Listing.objects.filter(status='active').count()
        new_listings = Listing.objects.filter(_since_filter()).count() if since else total_listings

        # Orders
        orders_qs = Order.objects.filter(_since_filter()) if since else Order.objects.all()
        total_orders = orders_qs.count()
        orders_by_status = dict(
            orders_qs.values_list('status').annotate(c=Count('id')).values_list('status', 'c')
        )
        completed_orders = orders_by_status.get('completed', 0)
        pending_orders = orders_by_status.get('pending', 0)
        delivered_orders = orders_by_status.get('delivered', 0)
        disputed_orders = orders_by_status.get('disputed', 0)
        cancelled_orders = orders_by_status.get('cancelled', 0)

        # Revenue
        revenue_agg = orders_qs.filter(status='completed').aggregate(
            total_revenue=Sum('total_amount'),
            total_commission=Sum('commission_amount'),
            total_seller_payouts=Sum('seller_amount'),
            avg_order_value=Avg('total_amount'),
        )
        total_revenue = float(revenue_agg['total_revenue'] or 0)
        total_commission = float(revenue_agg['total_commission'] or 0)
        total_seller_payouts = float(revenue_agg['total_seller_payouts'] or 0)
        avg_order_value = float(revenue_agg['avg_order_value'] or 0)

        # GMV (all non-cancelled orders)
        gmv = float(
            orders_qs.exclude(status='cancelled').aggregate(
                gmv=Sum('total_amount')
            )['gmv'] or 0
        )

        # Wallets
        wallet_agg = Wallet.objects.aggregate(
            total_balance=Sum('balance'),
            wallet_count=Count('id'),
        )
        total_wallet_balance = float(wallet_agg['total_balance'] or 0)

        # Top-ups
        topup_qs = TopUpRequest.objects.filter(_since_filter()) if since else TopUpRequest.objects.all()
        pending_topups = topup_qs.filter(status='pending').count()
        approved_topups_amount = float(
            topup_qs.filter(status='approved').aggregate(s=Sum('amount'))['s'] or 0
        )

        # Reviews
        review_qs = Review.objects.filter(_since_filter()) if since else Review.objects.all()
        total_reviews = review_qs.count()
        avg_rating = float(review_qs.aggregate(avg=Avg('rating'))['avg'] or 0)

        # Chat
        total_conversations = Conversation.objects.count()
        total_messages = Message.objects.count()
        new_messages = Message.objects.filter(_since_filter()).count() if since else total_messages

        # Games
        total_games = Game.objects.filter(is_active=True).count()

        # Online users (active in last 2 mins)
        online_threshold = now - timedelta(minutes=2)
        online_users = UserProfile.objects.filter(last_active__gte=online_threshold).count()

        # ── Charts: Daily order/revenue trend ────────────────────────────

        chart_since = since or (now - timedelta(days=365))
        daily_orders = list(
            Order.objects.filter(created_at__gte=chart_since)
            .annotate(day=TruncDate('created_at'))
            .values('day')
            .annotate(
                count=Count('id'),
                revenue=Sum('total_amount', filter=Q(status='completed')),
                commission=Sum('commission_amount', filter=Q(status='completed')),
            )
            .order_by('day')
        )
        chart_labels = [d['day'].strftime('%b %d') for d in daily_orders]
        chart_order_counts = [d['count'] for d in daily_orders]
        chart_revenue = [float(d['revenue'] or 0) for d in daily_orders]
        chart_commission = [float(d['commission'] or 0) for d in daily_orders]

        # ── Charts: Orders by status (pie) ───────────────────────────────

        status_pie = {
            'Completed': completed_orders,
            'Pending': pending_orders,
            'Delivered': delivered_orders,
            'Disputed': disputed_orders,
            'Cancelled': cancelled_orders,
        }

        # ── Top sellers ──────────────────────────────────────────────────

        seller_base = Order.objects.filter(status='completed')
        if since:
            seller_base = seller_base.filter(_since_filter())
        top_sellers = list(
            seller_base
            .values('seller__username')
            .annotate(
                order_count=Count('id'),
                total_earned=Sum('seller_amount'),
            )
            .order_by('-total_earned')[:10]
        )
        for s in top_sellers:
            s['total_earned'] = float(s['total_earned'] or 0)

        # ── Top games by listings ────────────────────────────────────────

        top_games = list(
            Listing.objects.filter(status='active')
            .values(game_name=F('game_category__game__name'))
            .annotate(listing_count=Count('id'))
            .order_by('-listing_count')[:10]
        )

        # ── Recent orders ────────────────────────────────────────────────

        recent_orders = list(
            Order.objects.select_related('buyer', 'seller')
            .order_by('-created_at')[:10]
            .values(
                'id', 'listing_title', 'total_amount', 'status',
                'created_at', 'buyer__username', 'seller__username',
            )
        )
        for o in recent_orders:
            o['total_amount'] = float(o['total_amount'])
            o['created_at'] = o['created_at'].strftime('%b %d, %H:%M')

        # ── Daily new users trend ────────────────────────────────────────

        daily_users = list(
            User.objects.filter(date_joined__gte=chart_since)
            .annotate(day=TruncDate('date_joined'))
            .values('day')
            .annotate(count=Count('id'))
            .order_by('day')
        )
        user_chart_labels = [d['day'].strftime('%b %d') for d in daily_users]
        user_chart_counts = [d['count'] for d in daily_users]

        return JsonResponse({
            'kpis': {
                'total_users': total_users,
                'new_users': new_users,
                'total_sellers': total_sellers,
                'pending_sellers': pending_sellers,
                'online_users': online_users,
                'total_listings': total_listings,
                'active_listings': active_listings,
                'new_listings': new_listings,
                'total_orders': total_orders,
                'completed_orders': completed_orders,
                'pending_orders': pending_orders,
                'delivered_orders': delivered_orders,
                'disputed_orders': disputed_orders,
                'cancelled_orders': cancelled_orders,
                'total_revenue': total_revenue,
                'total_commission': total_commission,
                'total_seller_payouts': total_seller_payouts,
                'avg_order_value': avg_order_value,
                'gmv': gmv,
                'total_wallet_balance': total_wallet_balance,
                'pending_topups': pending_topups,
                'approved_topups_amount': approved_topups_amount,
                'total_reviews': total_reviews,
                'avg_rating': round(avg_rating, 2),
                'total_conversations': total_conversations,
                'total_messages': total_messages,
                'new_messages': new_messages,
                'total_games': total_games,
            },
            'charts': {
                'daily_orders': {
                    'labels': chart_labels,
                    'orders': chart_order_counts,
                    'revenue': chart_revenue,
                    'commission': chart_commission,
                },
                'status_pie': status_pie,
                'daily_users': {
                    'labels': user_chart_labels,
                    'counts': user_chart_counts,
                },
            },
            'top_sellers': top_sellers,
            'top_games': top_games,
            'recent_orders': recent_orders,
            'range': range_key,
        })

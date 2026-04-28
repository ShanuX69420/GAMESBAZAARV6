from django.urls import path
from . import views

urlpatterns = [
    # Public — games & categories
    path('games/', views.GameListView.as_view(), name='game-list'),
    path('games/<slug:slug>/', views.GameDetailView.as_view(), name='game-detail'),
    path('games/<slug:game_slug>/<slug:category_slug>/',
         views.GameCategoryDetailView.as_view(), name='game-category-detail'),

    # Auth
    path('auth/register/', views.RegisterView.as_view(), name='register'),
    path('auth/login/', views.LoginView.as_view(), name='token-obtain'),
    path('auth/refresh/', views.RefreshTokenView.as_view(), name='token-refresh'),
    path('auth/logout/', views.LogoutView.as_view(), name='logout'),
    path('auth/me/', views.MeView.as_view(), name='me'),
    path('auth/profile/', views.UpdateProfileView.as_view(), name='update-profile'),
    path('auth/password/', views.ChangePasswordView.as_view(), name='change-password'),
    path('auth/password/reset-request/', views.RequestPasswordResetView.as_view(), name='request-password-reset'),
    path('auth/password/reset-confirm/', views.ConfirmPasswordResetView.as_view(), name='confirm-password-reset'),
    path('auth/avatar/', views.AvatarUploadView.as_view(), name='avatar-upload'),
    path('auth/email/request-change/', views.RequestEmailChangeView.as_view(), name='request-email-change'),
    path('auth/email/confirm-change/', views.ConfirmEmailChangeView.as_view(), name='confirm-email-change'),

    # Seller
    path('seller/apply/', views.SellerApplyView.as_view(), name='seller-apply'),
    path('seller/status/', views.SellerStatusView.as_view(), name='seller-status'),
    path('seller/dashboard/', views.SellerDashboardView.as_view(), name='seller-dashboard'),

    # Listings
    path('listings/', views.ListingCreateView.as_view(), name='listing-create'),
    path('listings/mine/', views.MyListingsView.as_view(), name='my-listings'),
    path('listings/<int:pk>/restock/', views.AutoDeliveryRestockView.as_view(), name='listing-restock'),
    path('listings/<int:pk>/', views.ListingDetailView.as_view(), name='listing-detail'),

    # Chat
    path('chat/', views.ConversationListView.as_view(), name='conversation-list'),
    path('chat/start/', views.StartConversationView.as_view(), name='start-conversation'),
    path('chat/unread/', views.UnreadCountView.as_view(), name='unread-count'),
    path('chat/<int:pk>/', views.ConversationDetailView.as_view(), name='conversation-detail'),
    path('chat/<int:pk>/ws-ticket/', views.ChatWebSocketTicketView.as_view(), name='chat-ws-ticket'),
    path('chat/<int:pk>/send/', views.SendMessageView.as_view(), name='send-message'),
    path('chat/<int:pk>/send-image/', views.SendImageView.as_view(), name='send-image'),
    path('chat/messages/<int:pk>/image/', views.ChatMessageImageView.as_view(), name='chat-message-image'),

    # Presence
    path('heartbeat/', views.HeartbeatView.as_view(), name='heartbeat'),

    # Wallet
    path('wallet/', views.WalletView.as_view(), name='wallet'),
    path('wallet/transactions/', views.WalletTransactionsView.as_view(), name='wallet-transactions'),
    path('wallet/top-up/', views.TopUpRequestView.as_view(), name='topup-request'),
    path('wallet/top-up/<int:pk>/proof/', views.TopUpProofView.as_view(), name='topup-proof'),

    # Orders
    path('orders/buy/', views.BuyListingView.as_view(), name='buy-listing'),
    path('orders/mine/', views.MyOrdersView.as_view(), name='my-orders'),
    path('orders/sales/', views.MySalesView.as_view(), name='my-sales'),
    path('orders/<int:pk>/', views.OrderDetailView.as_view(), name='order-detail'),
    path('orders/<int:pk>/deliver/', views.DeliverOrderView.as_view(), name='deliver-order'),
    path('orders/<int:pk>/confirm/', views.ConfirmOrderView.as_view(), name='confirm-order'),
    path('orders/<int:pk>/dispute/', views.DisputeOrderView.as_view(), name='dispute-order'),
    path('orders/<int:pk>/refund/', views.RefundOrderView.as_view(), name='refund-order'),
    path('admin/orders/<int:pk>/resolve-dispute/',
         views.ResolveDisputeView.as_view(), name='admin-resolve-dispute'),

    # Reviews
    path('reviews/', views.CreateReviewView.as_view(), name='create-review'),
    path('reviews/seller/<str:username>/', views.SellerReviewsView.as_view(), name='seller-reviews'),

    # Seller Profile
    path('seller/profile/<str:username>/', views.SellerProfileView.as_view(), name='seller-profile'),

    # Search
    path('search/', views.SearchView.as_view(), name='search'),

    # Notifications
    path('notifications/', views.NotificationListView.as_view(), name='notification-list'),
    path('notifications/read/', views.NotificationMarkReadView.as_view(), name='notification-mark-read'),
    path('notifications/unread-count/', views.NotificationUnreadCountView.as_view(), name='notification-unread-count'),
]

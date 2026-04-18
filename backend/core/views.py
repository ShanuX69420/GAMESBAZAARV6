from rest_framework import generics, status, permissions
from rest_framework.response import Response
from rest_framework.views import APIView
from django.shortcuts import get_object_or_404
from django.db.models import Q
from .models import Game, GameCategory, UserProfile, Listing
from .serializers import (
    GameListSerializer, GameDetailSerializer, GameCategoryDetailSerializer,
    RegisterSerializer, UserSerializer, SellerApplicationSerializer,
    ListingSerializer, CreateListingSerializer,
)


# ── Public Game / Category / Filter views ────────────────────────────────────

class GameListView(generics.ListAPIView):
    """GET /api/games/ — List all active games."""
    serializer_class = GameListSerializer
    queryset = Game.objects.filter(is_active=True).prefetch_related('game_categories')


class GameDetailView(generics.RetrieveAPIView):
    """GET /api/games/{slug}/ — Game detail with its categories."""
    serializer_class = GameDetailSerializer
    lookup_field = 'slug'
    queryset = Game.objects.filter(is_active=True).prefetch_related(
        'game_categories__category'
    )


class GameCategoryDetailView(APIView):
    """GET /api/games/{game_slug}/{category_slug}/ — Category with filters + listings."""

    def get(self, request, game_slug, category_slug):
        game_category = get_object_or_404(
            GameCategory.objects.select_related('game', 'category').prefetch_related(
                'assigned_filters__filter__options'
            ),
            game__slug=game_slug,
            category__slug=category_slug,
            game__is_active=True,
        )

        # Build category detail (filters)
        from .serializers import GameCategoryDetailSerializer
        cat_data = GameCategoryDetailSerializer(game_category).data

        # Query listings with optional filters
        listings_qs = Listing.objects.filter(
            game_category=game_category,
            status='active',
        ).select_related('seller', 'game_category__game', 'game_category__category')

        # Apply filter params from query string: ?filter_{filter_id}={option_value}
        for key, value in request.query_params.items():
            if key.startswith('filter_') and value:
                filter_id = key.replace('filter_', '')
                # Use __contains for proper dict key matching (numeric-looking keys
                # are misinterpreted as array indices by Django's __ path lookup)
                listings_qs = listings_qs.filter(
                    filter_values__contains={filter_id: value}
                )

        listings_data = ListingSerializer(listings_qs, many=True).data
        cat_data['listings'] = listings_data
        return Response(cat_data)


# ── Auth views ───────────────────────────────────────────────────────────────

class RegisterView(generics.CreateAPIView):
    """POST /api/auth/register/ — Register a new user."""
    serializer_class = RegisterSerializer

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = serializer.save()
        return Response({
            'message': 'Account created successfully.',
            'user': UserSerializer(user).data,
        }, status=status.HTTP_201_CREATED)


class MeView(APIView):
    """GET /api/auth/me/ — Get current user info."""
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        return Response(UserSerializer(request.user).data)


# ── Seller views ─────────────────────────────────────────────────────────────

class SellerApplyView(APIView):
    """POST /api/seller/apply/ — Submit a seller application."""
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        profile = request.user.profile
        if profile.seller_status == 'approved':
            return Response({'error': 'You are already an approved seller.'},
                            status=status.HTTP_400_BAD_REQUEST)
        if profile.seller_status == 'pending':
            return Response({'error': 'Your application is already pending.'},
                            status=status.HTTP_400_BAD_REQUEST)

        serializer = SellerApplicationSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        profile.seller_status = 'pending'
        profile.seller_application_note = serializer.validated_data['note']
        profile.save()

        return Response({'message': 'Seller application submitted.'})


class SellerStatusView(APIView):
    """GET /api/seller/status/ — Check seller application status."""
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        profile = request.user.profile
        return Response({
            'seller_status': profile.seller_status,
            'is_seller': profile.is_seller,
            'application_note': profile.seller_application_note,
        })


# ── Listing views ────────────────────────────────────────────────────────────

class ListingCreateView(generics.CreateAPIView):
    """POST /api/listings/ — Create a listing (sellers only)."""
    serializer_class = CreateListingSerializer
    permission_classes = [permissions.IsAuthenticated]

    def perform_create(self, serializer):
        if not self.request.user.profile.is_seller:
            from rest_framework.exceptions import PermissionDenied
            raise PermissionDenied('You must be an approved seller to create listings.')
        serializer.save()


class MyListingsView(generics.ListAPIView):
    """GET /api/listings/mine/ — Get current user's listings."""
    serializer_class = ListingSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        return Listing.objects.filter(
            seller=self.request.user
        ).select_related('game_category__game', 'game_category__category')


class ListingDetailView(generics.RetrieveAPIView):
    """GET /api/listings/{id}/ — Get listing detail."""
    serializer_class = ListingSerializer
    queryset = Listing.objects.select_related(
        'seller', 'game_category__game', 'game_category__category'
    )

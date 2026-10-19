
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework import status
from rest_framework_simplejwt.tokens import RefreshToken
from rest_framework_simplejwt.exceptions import TokenError
from django.contrib.auth.models import User
from django.contrib.auth import authenticate
from django.db.models import Prefetch
from django.shortcuts import get_object_or_404

from .models import (
    Language,
    Unit,
    Skill,
    Lesson,
    Exercise,
    UserStats,
    UserProgress,
    UserLessonAttempt,
    LeaderboardEntry,
    Achievement,
    UserAchievement,
)
from .serializers import (
    UnitPathSerializer,
    LessonSerializer,
    UserStatsSerializer,
    LeaderboardEntrySerializer,
    AchievementSerializer,
)
from .services import (
    calculate_user_hearts,
    record_lesson_completion,
    get_leaderboard_rank,
    update_user_achievements,
    build_leaderboard_payload,
    ensure_active_league,
    ACTIVE_LEAGUE,
)


# ─── HELPERS ────────────────────────────────────────────────────────────────

def get_tokens_for_user(user):
    """Generate JWT access and refresh tokens for a user."""
    refresh = RefreshToken.for_user(user)
    return {
        'refresh': str(refresh),
        'access': str(refresh.access_token),
    }


def auth_user_response(user):
    """Standard authentication response."""
    return {
        'user': {
            'id': user.id,
            'username': user.username,
            'email': user.email,
        },
        **get_tokens_for_user(user),
    }


def get_requested_language(request, data=None):
    """
    Get the requested course language.
    English ('en') is the default.
    For POST requests, the body language takes priority.
    """
    language_code = None

    if data is not None:
        language_code = data.get('language')

    if not language_code:
        language_code = request.query_params.get('language', 'en')

    return str(language_code).strip().lower()


def language_not_found_response(language_code):
    """Return a consistent error when a course language does not exist."""
    if not Language.objects.filter(code=language_code).exists():
        return Response(
            {'detail': 'Language not found.'},
            status=status.HTTP_404_NOT_FOUND,
        )
    return None


# ─── AUTH ENDPOINTS ─────────────────────────────────────────────────────────

@api_view(['GET'])
@permission_classes([AllowAny])
def health_check(request):
    """GET /api/health/ - Lightweight backend health check."""
    return Response({'status': 'ok'})


@api_view(['POST'])
@permission_classes([AllowAny])
def register_user(request):
    """POST /api/auth/register/ - Create a user account."""
    username = request.data.get('username', '').strip()
    email = request.data.get('email', '').strip()
    password = request.data.get('password', '')

    if not username or not password:
        return Response(
            {'detail': 'Username and password are required.'},
            status=status.HTTP_400_BAD_REQUEST,
        )

    if len(password) < 6:
        return Response(
            {'detail': 'Password must be at least 6 characters.'},
            status=status.HTTP_400_BAD_REQUEST,
        )

    if User.objects.filter(username=username).exists():
        return Response(
            {'detail': 'Username already taken.'},
            status=status.HTTP_400_BAD_REQUEST,
        )

    if email and User.objects.filter(email=email).exists():
        return Response(
            {'detail': 'Email already in use.'},
            status=status.HTTP_400_BAD_REQUEST,
        )

    user = User.objects.create_user(
        username=username,
        email=email,
        password=password,
    )

    UserStats.objects.get_or_create(user=user)
    LeaderboardEntry.objects.get_or_create(
        user=user,
        defaults={'league': ACTIVE_LEAGUE},
    )

    return Response(
        {
            'user': {
                'id': user.id,
                'username': user.username,
                'email': user.email,
            },
            **get_tokens_for_user(user),
        },
        status=status.HTTP_201_CREATED,
    )


@api_view(['POST'])
@permission_classes([AllowAny])
def login_user(request):
    """POST /api/auth/login/ - Login with username or email."""
    identifier = request.data.get('username', '').strip()
    password = request.data.get('password', '')

    if not identifier or not password:
        return Response(
            {'detail': 'Username and password are required.'},
            status=status.HTTP_400_BAD_REQUEST,
        )

    user = None

    if '@' in identifier:
        try:
            user_obj = User.objects.get(email=identifier)
            user = authenticate(
                request,
                username=user_obj.username,
                password=password,
            )
        except User.DoesNotExist:
            pass
    else:
        user = authenticate(
            request,
            username=identifier,
            password=password,
        )

    if user is None:
        return Response(
            {'detail': 'Invalid credentials.'},
            status=status.HTTP_401_UNAUTHORIZED,
        )

    if not user.is_active:
        return Response(
            {'detail': 'Account is disabled.'},
            status=status.HTTP_403_FORBIDDEN,
        )

    return Response({
        'user': {
            'id': user.id,
            'username': user.username,
            'email': user.email,
        },
        **get_tokens_for_user(user),
    })


@api_view(['POST'])
@permission_classes([AllowAny])
def logout_user(request):
    """POST /api/auth/logout/ - Blacklist the refresh token."""
    refresh_token = request.data.get('refresh')

    if not refresh_token:
        return Response(
            {'detail': 'Refresh token required.'},
            status=status.HTTP_400_BAD_REQUEST,
        )

    try:
        token = RefreshToken(refresh_token)
        token.blacklist()
    except TokenError:
        pass

    return Response({'detail': 'Successfully logged out.'})


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def get_me(request):
    """GET /api/auth/me/ - Return current user information."""
    user = request.user

    stats, _ = UserStats.objects.get_or_create(user=user)
    calculate_user_hearts(stats)

    return Response({
        'id': user.id,
        'username': user.username,
        'email': user.email,
        'date_joined': user.date_joined,
        'stats': UserStatsSerializer(stats).data,
    })


# ─── LEARNING PATH HELPERS ──────────────────────────────────────────────────

def _build_path_payload(user, language_code='en'):
    """
    Build the learning path for one language only.
    User progress is preserved and matched by skill ID.
    """
    units = (
        Unit.objects.filter(language__code=language_code)
        .prefetch_related(
            Prefetch(
                'skills',
                queryset=Skill.objects.prefetch_related(
                    Prefetch(
                        'lessons',
                        queryset=Lesson.objects.prefetch_related(
                            'exercises'
                        ).order_by('order'),
                    )
                ).order_by('order'),
            )
        )
        .order_by('order')
    )

    progress_map = {
        progress.skill_id: progress
        for progress in UserProgress.objects.filter(
            user=user
        ).only(
            'skill_id',
            'is_unlocked',
            'is_completed',
            'completed_lessons',
            'current_crown',
        )
    }

    serializer = UnitPathSerializer(
        units,
        many=True,
        context={
            'user': user,
            'progress_map': progress_map,
        },
    )

    return serializer.data


# ─── LEARNING PATH ENDPOINTS ────────────────────────────────────────────────

@api_view(['GET'])
@permission_classes([IsAuthenticated])
def get_path(request):
    """GET /api/path/?language=en - Learning path for the selected language."""
    language_code = get_requested_language(request)

    error_response = language_not_found_response(language_code)
    if error_response:
        return error_response

    return Response(
        _build_path_payload(request.user, language_code)
    )


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def get_dashboard(request):
    """GET /api/dashboard/?language=en - Selected path and user statistics."""
    user = request.user
    language_code = get_requested_language(request)

    error_response = language_not_found_response(language_code)
    if error_response:
        return error_response

    stats, _ = UserStats.objects.get_or_create(user=user)
    calculate_user_hearts(stats)

    return Response({
        'path': _build_path_payload(user, language_code),
        'stats': UserStatsSerializer(stats).data,
    })


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def get_skill_lesson(request, skill_id):
    """
    GET /api/skills/<skill_id>/lesson/?language=en
    Fetch the next lesson for a skill in the selected language.
    """
    language_code = get_requested_language(request)

    error_response = language_not_found_response(language_code)
    if error_response:
        return error_response

    skill = get_object_or_404(
        Skill.objects.filter(
            unit__language__code=language_code
        ).select_related(
            'unit',
            'unit__language',
        ).prefetch_related(
            Prefetch(
                'lessons',
                queryset=Lesson.objects.prefetch_related(
                    'exercises'
                ).order_by('order'),
            )
        ),
        pk=skill_id,
    )

    progress = UserProgress.objects.filter(
        user=request.user,
        skill=skill,
    ).first()

    is_unlocked = (
        skill.order == 1 and skill.unit.order == 1
    ) or bool(progress and progress.is_unlocked)

    if not is_unlocked:
        return Response(
            {'detail': 'This skill is locked.'},
            status=status.HTTP_403_FORBIDDEN,
        )

    lessons = list(skill.lessons.all())

    if not lessons:
        return Response(
            {'detail': 'No lessons found for this skill.'},
            status=status.HTTP_404_NOT_FOUND,
        )

    completed_lessons = (
        progress.completed_lessons if progress else 0
    )
    lesson = lessons[completed_lessons % len(lessons)]

    serializer = LessonSerializer(lesson)
    return Response(serializer.data)


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def complete_lesson(request, lesson_id):
    """
    POST /api/lessons/<lesson_id>/complete/

    Payload:
    {
        "score": 100,
        "hearts_lost": 0,
        "language": "en"
    }

    The language field is optional; English is the default.
    """
    user = request.user
    language_code = get_requested_language(request, request.data)

    error_response = language_not_found_response(language_code)
    if error_response:
        return error_response

    # A lesson ID must belong to the requested course language.
    lesson = get_object_or_404(
        Lesson.objects.select_related(
            'skill__unit__language'
        ),
        pk=lesson_id,
        skill__unit__language__code=language_code,
    )

    try:
        score = int(request.data.get('score', 100))
        hearts_lost = int(request.data.get('hearts_lost', 0))
    except (TypeError, ValueError):
        return Response(
            {'detail': 'Invalid score or hearts_lost value.'},
            status=status.HTTP_400_BAD_REQUEST,
        )

    if not 0 <= score <= 100:
        return Response(
            {'detail': 'Score must be between 0 and 100.'},
            status=status.HTTP_400_BAD_REQUEST,
        )

    if not 0 <= hearts_lost <= 5:
        return Response(
            {'detail': 'hearts_lost must be between 0 and 5.'},
            status=status.HTTP_400_BAD_REQUEST,
        )

    skill = lesson.skill

    progress = UserProgress.objects.filter(
        user=user,
        skill=skill,
    ).first()

    is_unlocked = (
        skill.order == 1 and skill.unit.order == 1
    ) or bool(progress and progress.is_unlocked)

    if not is_unlocked:
        return Response(
            {'detail': 'Skill is locked.'},
            status=status.HTTP_403_FORBIDDEN,
        )

    lessons = list(
        skill.lessons.order_by('order')
    )

    if not lessons:
        return Response(
            {'detail': 'No lessons found for this skill.'},
            status=status.HTTP_404_NOT_FOUND,
        )

    completed_lessons = (
        progress.completed_lessons if progress else 0
    )
    expected_lesson = lessons[completed_lessons % len(lessons)]

    if expected_lesson.id != lesson.id:
        return Response(
            {
                'detail':
                    'Complete the current unlocked lesson first.'
            },
            status=status.HTTP_409_CONFLICT,
        )

    result = record_lesson_completion(
        user=user,
        lesson=lesson,
        score=score,
        hearts_lost=hearts_lost,
    )

    return Response(result, status=status.HTTP_200_OK)


# ─── USER STATISTICS ────────────────────────────────────────────────────────

@api_view(['GET'])
@permission_classes([IsAuthenticated])
def get_user_stats(request):
    """GET /api/user/stats/ - XP, streak, hearts and gems."""
    user = request.user

    stats, _ = UserStats.objects.get_or_create(user=user)
    calculate_user_hearts(stats)

    return Response(UserStatsSerializer(stats).data)


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def refill_hearts(request):
    """POST /api/user/hearts/refill/ - Refill the user's hearts."""
    user = request.user

    stats, _ = UserStats.objects.get_or_create(user=user)
    stats.hearts = stats.max_hearts
    stats.last_heart_loss_timestamp = None
    stats.save()

    return Response({
        'message': 'Hearts refilled successfully!',
        'hearts': stats.hearts,
    })


# ─── LEADERBOARD ────────────────────────────────────────────────────────────

@api_view(['GET'])
@permission_classes([AllowAny])
def get_leaderboard(request):
    """GET /api/leaderboard/ - Leaderboard ordered by weekly XP."""
    return Response(build_leaderboard_payload(limit=20))


# ─── PROFILE AND ACHIEVEMENTS ───────────────────────────────────────────────

@api_view(['GET'])
@permission_classes([IsAuthenticated])
def get_profile(request):
    """GET /api/user/profile/ - Stats, achievements and leaderboard data."""
    user = request.user

    stats, _ = UserStats.objects.get_or_create(user=user)
    calculate_user_hearts(stats)

    achievements = Achievement.objects.all()
    update_user_achievements(user, stats)

    user_achievements_map = {
        item.achievement_id: item
        for item in UserAchievement.objects.filter(
            user=user
        ).only(
            'achievement_id',
            'is_unlocked',
            'current_progress',
        )
    }

    achievements_serialized = AchievementSerializer(
        achievements,
        many=True,
        context={
            'user': user,
            'user_achievements_map': user_achievements_map,
        },
    ).data

    leaderboard_entry, _ = LeaderboardEntry.objects.get_or_create(
        user=user,
        defaults={'league': ACTIVE_LEAGUE},
    )
    ensure_active_league(leaderboard_entry)

    return Response({
        'username': user.username,
        'date_joined': user.date_joined,
        'stats': UserStatsSerializer(stats).data,
        'achievements': achievements_serialized,
        'leaderboard': {
            'rank': get_leaderboard_rank(user),
            'weekly_xp': leaderboard_entry.weekly_xp,
            'league': ACTIVE_LEAGUE,
        },
    })


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def get_achievements(request):
    """GET /api/achievements/ - Return the user's achievements."""
    user = request.user
    achievements = Achievement.objects.all()

    serializer = AchievementSerializer(
        achievements,
        many=True,
        context={'user': user},
    )

    return Response(serializer.data)

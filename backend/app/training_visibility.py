"""Ordinary history includes only trainings with a real attempt."""
from app.models import RouteAttempt, TrainingSession


def not_test_only():
    return TrainingSession.attempts.any(RouteAttempt.is_test.is_(False))

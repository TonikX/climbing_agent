"""History hides trainings containing only test attempts unless explicitly requested."""
from sqlalchemy import or_

from app.models import RouteAttempt, TrainingSession


def not_test_only():
    # An empty training is not known to be a test training.
    return or_(~TrainingSession.attempts.any(), TrainingSession.attempts.any(RouteAttempt.is_test.is_(False)))

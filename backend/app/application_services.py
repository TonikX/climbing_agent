"""Public service boundaries reuse the journal's existing domain implementation."""
from app import auth, jobs, service, tool_service


class TrainingService:
    start = staticmethod(service.start_training)
    append = staticmethod(service.append_attempt)
    finish = staticmethod(service.finish_training)
    list = staticmethod(service.list_trainings)
    current = staticmethod(tool_service._get_current)


class StatisticsService:
    read = staticmethod(tool_service._statistics)


class CatalogService:
    location = staticmethod(tool_service._area)
    section = staticmethod(tool_service._section)
    route = staticmethod(tool_service._route)


class AuthService:
    login = staticmethod(auth.telegram_login)
    authenticate = staticmethod(auth.authenticate)


class JobService:
    ingest = staticmethod(jobs.ingest)
    claim = staticmethod(jobs.claim)
    leased = staticmethod(jobs.leased)
    fail = staticmethod(jobs.fail)

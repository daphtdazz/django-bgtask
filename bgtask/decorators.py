import logging
from functools import wraps

from django.contrib.messages import INFO


from .models import BackgroundTask


log = logging.getLogger(__name__)


def bgtask_admin_action(func=None):
    if func is not None:
        return bgtask_admin_action()(func)

    def bgtask_admin_action_factory(func):

        task_name = f"AdminTask-{func.__name__}"

        @wraps(func)
        def bgtask_admin_action_wrapper(self, request, queryset):
            log.info("Running func %s", func.__name__)
            bg_task = self.start_bgtask(task_name)

            self.message_user(request, "Started background task", level=INFO)

            from .backends import default_backend

            default_backend.dispatch(_run_bg_task_func, func, bg_task, request, queryset)


        bgtask_admin_action_wrapper.bgtask_name = task_name

        return bgtask_admin_action_wrapper

    return bgtask_admin_action_factory


def _run_bg_task_func(func, bg_task, request, queryset):
    try:
        func(bg_task, request, queryset)
    except Exception as exc:
        bg_task.fail(exc)
    else:
        bg_task.succeed()

from utils.stack_context import stack_context

from .models import BackgroundTask


__all__ = ["bgtask_context"]


@stack_context(logging_param_name="bgtask_id")
def bgtask_context(id):
    return BackgroundTask.objects.get(id=id)

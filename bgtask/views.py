from django.core.exceptions import ValidationError
from django.db.models import Q
from django.forms.models import model_to_dict
from django.http import Http404, HttpResponseBadRequest, JsonResponse
from django.shortcuts import render

from .models import BackgroundTask


Q_NONE = Q(pk__in=[])


def _tasks_dict(tasks):
    td = {str(task.id): task.task_dict for task in tasks}
    return td


def background_tasks_view_html(request, task):
    return render(
        request,
        "bgtask/bgtask_view.html",
        {"tasks": _tasks_dict(task), "title": "Background tasks"},
    )


def background_tasks_view_json(tasks):
    return JsonResponse(_tasks_dict(tasks))


def background_tasks_view(request):
    tasks = request.GET.get("tasks", "")
    object_id = request.GET.get("object_id", None)
    if tasks is None and object_id is None:
        return HttpResponseBadRequest(
            "Must pass 'tasks' or 'object_id' as a query parameter"
        )
    try:
        task_ids = tasks.split(",")
        task_ids_q = Q(id__in=task_ids) if tasks else Q_NONE
        object_id_q = (
            Q(acted_on_object_id=object_id) if object_id is not None else Q_NONE
        )
        tasks = BackgroundTask.objects.filter(task_ids_q | object_id_q).order_by(
            "-created"
        )
        if len(tasks) == 0:
            raise ValidationError("Unfound tasks")
    except ValidationError:
        return HttpResponseBadRequest(f"Bad task id(s) {task_ids}")
    except BackgroundTask.DoesNotExist:
        raise Http404(f"Unknown task {task_ids}")

    accepts = request.headers.get("Accept", "").split(",")

    if "application/json" in accepts:
        return background_tasks_view_json(tasks)

    return background_tasks_view_html(request, tasks)

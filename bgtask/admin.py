from django.contrib import admin
from django.template.loader import render_to_string

from .models import BackgroundTask


def background_task_status(obj):
    if isinstance(obj, BackgroundTask):
        bgtask = obj
    else:
        bgtasks = BackgroundTask.objects.filter(acted_on_object_id=obj.id).order_by("-created")

        # for now just pick the most recent
        bgtask = bgtasks.first()

    output = render_to_string(
        "bgtask/bg_changelist_status_column.html", {"bgtask": bgtask and bgtask.task_dict}
    )
    return output


background_task_status.__name__ = "Task Status"


@admin.register(BackgroundTask)
class BackgroundTaskAdmin(admin.ModelAdmin):
    list_filter = ["state", "namespace", "name"]
    list_display = ("created", "namespace_name", background_task_status, "result", "completed_at")
    ordering = ["-created"]

    def namespace_name(self, bgtask):
        return ".".join(f for f in [bgtask.namespace, bgtask.name] if f)

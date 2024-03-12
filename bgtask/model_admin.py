from datetime import timedelta

from django.contrib import admin
from django.contrib.admin.utils import label_for_field
from django.db.models import Q
from django.utils import timezone

from .models import BackgroundTask


class BGTaskModelAdmin(admin.ModelAdmin):
    change_list_template = "bgtask/admin/change_list.html"

    def admin_bg_tasks(self, request):
        task_name_to_desc = {}
        for action, action_name, action_description in self.get_actions(request).values():
            if hasattr(action, "bgtask_name"):
                task_name_to_desc[action.bgtask_name] = action_description

        if not task_name_to_desc:
            return BackgroundTask.objects.none()

        bgts = list(BackgroundTask.objects.filter(name__in=task_name_to_desc).filter(
            Q(state=BackgroundTask.STATES.running)
            | (
                ~Q(state=BackgroundTask.STATES.not_started)
                & Q(completed_at__gt=timezone.now() - timedelta(minutes=30))
            )
        ))
        for bgt in bgts:
            bgt.admin_description = task_name_to_desc[bgt.name]

        return bgts


    def changelist_view(self, request, extra_context=None):
        extra_context = extra_context or {}
        extra_context["admin_bg_tasks"] = self.admin_bg_tasks(request)
        return super().changelist_view(request, extra_context=extra_context)

from datetime import timedelta

from django.contrib import admin
from django.contrib.admin.utils import label_for_field
from django.db.models import Q
from django.utils import timezone

from .models import BackgroundTask


class BGTaskModelAdmin(admin.ModelAdmin):
    # This is not overridden to avoid messing with the implicit logic for finding change list
    # templates that ModelAdmin uses. So you either need to specify this yourself on your
    # subclass or you need to extend from this in your custom template.
    # change_list_template = "bgtask/admin/change_list.html"

    # ----------------------------------------------------------------------------------------------
    # API for subclasses
    # ----------------------------------------------------------------------------------------------
    def start_bgtask(self, name, **kwargs):
        bgtask = BackgroundTask.objects.create(
            name=name,
            namespace=self._bgtask_namespace,
            **kwargs,
        )
        bgtask.start()
        return bgtask

    # ----------------------------------------------------------------------------------------------
    # Superclass overrides
    # ----------------------------------------------------------------------------------------------
    def changelist_view(self, request, extra_context=None):
        extra_context = extra_context or {}
        extra_context["admin_bg_tasks"] = self._admin_bg_tasks(request)
        return super().changelist_view(request, extra_context=extra_context)

    # ----------------------------------------------------------------------------------------------
    # Internal functions
    # ----------------------------------------------------------------------------------------------
    @property
    def _bgtask_namespace(self):
        return type(self).__module__ + "." + type(self).__name__

    def _admin_bg_tasks(self, request):
        task_name_to_desc = {}
        for action, action_name, action_description in self.get_actions(request).values():
            if hasattr(action, "bgtask_name"):
                task_name_to_desc[action.bgtask_name] = action_description

        for name in getattr(self, "bgtask_names", []):
            task_name_to_desc[name] = name

        if not task_name_to_desc:
            return BackgroundTask.objects.none()

        bgts = list(
            BackgroundTask.objects.filter(
                name__in=task_name_to_desc, namespace=self._bgtask_namespace
            )
            .filter(
                Q(state=BackgroundTask.STATES.running)
                | (
                    ~Q(state=BackgroundTask.STATES.not_started)
                    & Q(completed_at__gt=timezone.now() - timedelta(minutes=30))
                )
            )
            .order_by("-started_at")
        )
        for bgt in bgts:
            bgt.admin_description = task_name_to_desc[bgt.name]

        return bgts

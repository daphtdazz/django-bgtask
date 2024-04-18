from datetime import timedelta
from functools import wraps

from django.contrib import admin
from django.contrib.admin.utils import label_for_field
from django.contrib.messages import INFO
from django.db.models import Q
from django.utils import timezone

from .models import BackgroundTask


class BGTaskModelAdmin(admin.ModelAdmin):
    # This is not overridden to avoid messing with the implicit logic for finding change list
    # templates that ModelAdmin uses. So you either need to specify this yourself on your
    # subclass or you need to extend from this in your custom template.
    #
    # change_list_template = "bgtask/admin/change_list.html"

    # ----------------------------------------------------------------------------------------------
    # Class API
    # ----------------------------------------------------------------------------------------------
    @classmethod
    def starts_task(cls, name, **task_kwargs):

        def starts_task_decorator(func):

            @wraps(func)
            def starts_task_wrapper(self, request, *args, **kwargs):
                bgtask = self.start_bgtask(name, **task_kwargs)
                result = func(self, request, *args, bgtask=bgtask, **kwargs)
                self.message_user(request, f"Dispatched task {name}", INFO)

            func.bgtask_name = name

            return starts_task_wrapper

        return starts_task_decorator

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

    @staticmethod
    def _extract_bgtask_name_from_admin_action(action):
        # recurse through the potentially wrapped action until we find one that declares
        # the bgtask_name
        next_action = action
        while True:
            if hasattr(next_action, "bgtask_name"):
                return next_action.bgtask_name

            if not hasattr(next_action, "__wrapped__"):
                return None

            next_action = next_action.__wrapped__

    def _admin_bg_tasks(self, request):
        task_name_to_desc = {}
        for action, action_name, action_description in self.get_actions(request).values():
            bgtask_name = self._extract_bgtask_name_from_admin_action(action)
            if bgtask_name is not None:
                task_name_to_desc[bgtask_name] = action_description

        for name in getattr(self, "bgtask_names", []):
            task_name_to_desc[name] = name

        if not task_name_to_desc:
            return BackgroundTask.objects.none()

        bgts = list(
            BackgroundTask.objects.filter(
                name__in=task_name_to_desc, namespace=self._bgtask_namespace
            )
            .filter(
                (
                    Q(state=BackgroundTask.STATES.running)
                    & Q(started_at__gt=timezone.now() - timedelta(days=1))
                )
                | (
                    ~Q(state=BackgroundTask.STATES.not_started)
                    & Q(completed_at__gt=timezone.now() - timedelta(hours=2))
                )
            )
            .order_by("-started_at")
        )
        for bgt in bgts:
            bgt.admin_description = task_name_to_desc[bgt.name]

        return bgts

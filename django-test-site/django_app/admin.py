import logging
import time

from django.contrib import admin

from bgtask.decorators import bgtask_admin_action
from bgtask.model_admin import BGTaskModelAdmin

from .models import ModelWithBackgroundActions


log = logging.getLogger(__name__)


@bgtask_admin_action
def do_something_in_the_background(bg_task, request, queryset):
    log.info("Doing something to %d items", len(queryset))
    bg_task.steps_to_complete = 100
    bg_task.steps_completed = 10
    bg_task.save()

    time.sleep(2)

    bg_task.steps_completed = 20
    bg_task.save()

    time.sleep(2)

    bg_task.steps_completed = 30
    bg_task.save()

    time.sleep(2)

    bg_task.steps_completed = 35
    bg_task.save()

    time.sleep(2)

    bg_task.steps_completed = 50
    bg_task.save()

    time.sleep(2)

    bg_task.steps_completed = 63
    bg_task.save()

    time.sleep(2)

    bg_task.steps_completed = 85
    bg_task.save()

    time.sleep(2)

    bg_task.steps_completed = 99
    bg_task.save()

    time.sleep(1)


@admin.register(ModelWithBackgroundActions)
class ModelWithBackgroundActionsAdmin(BGTaskModelAdmin):
    list_display = ["name", "text"]

    actions = [
        do_something_in_the_background,
    ]


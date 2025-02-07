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
    change_list_template = "bgtask/admin/change_list.html"

    list_display = ["name", "text"]

    actions = [
        do_something_in_the_background,
        "queueing_action",
    ]

    bgtask_names = ["Queued task"]

    def queueing_action(self, request, queryset):
        from bgtask.backends import default_backend

        for obj in queryset:
            bgtask = self.queue_bgtask("Queued task")
            default_backend.dispatch(self.execute_queued_task, obj, bgtask)

    def execute_queued_task(self, obj, task):
        while pos_in_queue := task.get_position_in_queue():
            log.info("Not first in queue, sleeping %s", pos_in_queue)
            time.sleep(3)

        log.info("First in queue, go! %s", pos_in_queue)
        time.sleep(2)

        task.start()
        with task.finishes():
            log.info("Running task for obj %s", obj)
            time.sleep(5)
            log.info("Finished task for obj %s", obj)

import collections
import logging
import os
import time
import traceback
import uuid
from contextlib import contextmanager

from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.contenttypes.models import ContentType
from django.db import models
from django.forms.models import model_to_dict
from django.utils import timezone

from model_utils import Choices

from .utils import locked, only_if_state, q_or


log = logging.getLogger(__name__)


class BackgroundTaskQuerySet(models.QuerySet):
    def add_position_in_queue(self):
        """This evaluates the queryset and adds position_in_queue to each one (which requires
        more DB queries).
        """
        recent_unqueued_task_by_nsn = {(task.namespace, task.name): None for task in self}
        for ns, name in recent_unqueued_task_by_nsn:
            recent_unqueued_task_by_nsn[(ns, name)] = BackgroundTask.most_recently_unqueued_task(
                ns, name
            )

        queued_tasks_by_nsn = BackgroundTask.queued_tasks_in_order_by_nsn_like(self)

        for task in self:
            if task.state != task.STATES.queued:
                continue

            unqueued_task = recent_unqueued_task_by_nsn[(task.namespace, task.name)]
            if unqueued_task is not None and task.queued_at < unqueued_task.queued_at:
                # More recently queued task has already been dispatched so we should be going...
                task.position_in_queue = 0
                continue

            task.position_in_queue = 0
            for queued_task in queued_tasks_by_nsn[(task.namespace, task.name)]:
                if queued_task.queued_at >= task.queued_at:
                    break
                task.position_in_queue += 1

        return self


class BackgroundTask(models.Model):
    id = models.UUIDField(primary_key=True, editable=False, default=uuid.uuid4)
    namespace = models.CharField(
        max_length=1000,
        default="",
        blank=True,
        help_text=(
            "Optional namespace that can be used to avoid having to make names unique across an "
            "entire codebase, allowing them to be shorter and human readable"
        ),
    )
    name = models.CharField(
        max_length=1000,
        help_text=(
            "Name (or type) of this task, is not unique "
            "per task instance but generally per task functionality"
        ),
    )

    STATES = Choices("not_started", "queued", "running", "success", "partial_success", "failed")
    state = models.CharField(max_length=16, default=STATES.not_started, choices=STATES)
    steps_to_complete = models.PositiveIntegerField(
        null=True, blank=True, help_text="The number of steps in the task for it to be completed."
    )
    steps_completed = models.PositiveIntegerField(
        null=True, blank=True, help_text="The number of steps completed so far by this task"
    )

    queued_at = models.DateTimeField(null=True, blank=True)
    started_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    result = models.JSONField(null=True, blank=True, help_text="The result(s) of the task, if any")
    errors = models.JSONField(
        default=list, blank=True, help_text="Any errors that occurred during processing"
    )

    # This follows the pattern described in
    # https://docs.djangoproject.com/en/3.0/ref/contrib/contenttypes/#generic-relations
    content_type = models.ForeignKey(ContentType, on_delete=models.CASCADE, blank=True, null=True)
    acted_on_object_id = models.TextField(db_index=True, blank=True, null=True)
    content_object = GenericForeignKey("content_type", "acted_on_object_id")

    # Helpful to have these for debugging mostly
    created = models.DateTimeField(auto_now_add=True)
    updated = models.DateTimeField(auto_now=True)

    objects = models.Manager.from_queryset(BackgroundTaskQuerySet)()

    class Meta:
        ordering = ["created", "id"]

    # This needs to be added dynamically to model instances, and is done by
    # BackgroundTaskQuerySet.add_position_in_queue()
    position_in_queue = None

    @property
    def task_dict(self):
        task_dict = model_to_dict(self)
        return {
            "id": str(self.id),
            "updated": self.updated.isoformat(),
            "position_in_queue": self.position_in_queue,
            **task_dict,
        }

    @property
    def num_failed_steps(self):
        return sum(error.get("num_failed_steps", 0) for error in self.errors)

    @property
    def incomplete(self):
        return self.state in [self.STATES.not_started, self.STATES.running]

    @classmethod
    def most_recently_unqueued_task(cls, namespace, name):
        return (
            cls.objects.filter(queued_at__isnull=False, namespace=namespace, name=name)
            .exclude(state=cls.STATES.not_started)
            .exclude(state=cls.STATES.queued)
            .order_by("-queued_at")
            .first()
        )

    @classmethod
    def queued_tasks_in_order_by_nsn_like(cls, tasks):
        queued_by_nsn = collections.defaultdict(list)
        nsns = {(task.namespace, task.name) for task in tasks}
        for task in (
            cls.objects.filter(queued_at__isnull=False, state=cls.STATES.queued)
            .filter(q_or(models.Q(namespace=nsn[0], name=nsn[1]) for nsn in nsns))
            .order_by("queued_at")
        ):
            queued_by_nsn[(task.namespace, task.name)].append(task)
        return queued_by_nsn

    def set_steps_to_complete(self, steps_to_complete):
        self.steps_to_complete = steps_to_complete
        self.steps_completed = 0
        self.save()

    @contextmanager
    def runs_single_step(self):
        try:
            yield
        except Exception as exc:
            self.steps_failed(1, error=exc)
        else:
            self.add_successful_steps(1)

    @contextmanager
    def finishes(self):
        try:
            yield
        except Exception as exc:
            self.fail(exc)
        else:
            self.succeed()

    @contextmanager
    def fails_if_exception(self):
        try:
            yield
        except Exception as exc:
            self.fail(exc)
            raise

    @locked
    @only_if_state(STATES.not_started)
    def queue(self):
        log.info("Background Task queueing: %s", self.id)
        self.state = self.STATES.queued
        self.queued_at = timezone.now()
        self.save()

    @locked
    @only_if_state(
        (STATES.not_started, STATES.queued),
        # Allow start() to be called while running so that if a task's subtasks are queued and
        # asynchronous each can call .start() independently so the first one that is executed will
        # start the task.
        no_op_states=(STATES.running,),
    )
    def start(self):
        log.info("Background Task starting: %s", self.id)
        self.state = self.STATES.running
        self.started_at = timezone.now()
        self.save()

    @locked
    @only_if_state((STATES.queued, STATES.running))
    def fail(self, exc):
        """Call to indicate a complete and final failure of the task"""
        log.info("Background Task failed: %s %s", self.id, exc)
        self.state = self.STATES.failed
        self.completed_at = timezone.now()
        self.errors.append(
            {"datetime": self.completed_at.isoformat(), **self._error_dict_for_error(exc)},
        )
        self.save()

    @locked
    @only_if_state(STATES.running)
    def succeed(self, result=None):
        log.info("%s succeeded.", self)
        self.state = self.STATES.success
        self.steps_completed = self.steps_to_complete
        self.completed_at = timezone.now()
        self.result = self.serialize_result(result)
        self.save()

    @locked
    @only_if_state(STATES.running)
    def finish(self):
        """Mark task as finished, automatically deducing the final state."""
        if not self.errors:
            log.info("Finishing as success with no errors")
            self.state = self.STATES.success
        elif self.steps_to_complete is None:
            log.info("Finishing as success with no steps to complete configured")
            self.state = self.STATES.success
        elif self.num_failed_steps == self.steps_to_complete:
            log.info("Finishing as failure with all steps failed")
            self.state = self.STATES.failed
        else:
            log.info("Finishing as partial success with some steps failed")
            self.state = self.STATES.partial_success

        self.completed_at = timezone.now()
        self.save()

    @locked
    def add_successful_steps(self, num_steps):
        self.steps_completed += num_steps
        self._finish_or_save()

    @locked
    def steps_failed(self, num_steps, steps_identifier=None, error=None):
        self.steps_completed += num_steps
        error_dict = {
            "datetime": timezone.now().isoformat(),
            "num_failed_steps": num_steps,
        }
        if steps_identifier:
            error_dict["steps_identifier"] = steps_identifier

        error_dict.update(self._error_dict_for_error(error))

        self.errors.append(error_dict)
        self._finish_or_save()

    def dispatch(self):
        # double fork to avoid zombies
        pid = os.fork()

        if pid != 0:
            log.info("Waiting for child %d", pid)
            os.waitpid(pid, 0)
            log.info("Child exited")
            return

        # get fresh db connections in all children
        from django import db

        db.connections.close_all()

        pid2 = os.fork()
        if pid2 != 0:
            log.info("Child exiting %d", os.getpid())
            os._exit(0)

        self.start()

        time.sleep(5)
        self.steps_to_complete = 100
        self.steps_completed = 0
        self.save()

        def raise_an_exception():
            raise Exception("Some exception")

        for ii in range(100):
            time.sleep(0.2)

            if ii % 52 == 0:
                try:
                    raise_an_exception()
                except Exception as exc:
                    self.steps_failed(1, str(ii), error=exc)
            else:
                self.add_successful_steps(1)
            if ii % 10 == 0:
                log.info("Completed %d items", ii)

        os._exit(0)

    # ----------------------------------------------------------------------------------------------
    # For overriding by subclasses
    # ----------------------------------------------------------------------------------------------
    def __str__(self):
        return "%s %s %s" % (type(self).__name__, self.id, self.state)

    @staticmethod
    def serialize_result(result):
        return result

    # ----------------------------------------------------------------------------------------------
    # Internals
    # ----------------------------------------------------------------------------------------------
    @staticmethod
    def _error_dict_for_error(error):
        if not error:
            return {}

        error_dict = {"error_message": str(error)}

        if hasattr(error, "__traceback__"):
            error_dict["traceback"] = "".join(
                traceback.format_list(traceback.extract_tb(error.__traceback__))
            )
        return error_dict

    def _finish_or_save(self):
        if (
            self.steps_to_complete is not None
            and self.steps_completed is not None
            and self.steps_completed >= self.steps_to_complete
        ):
            self.finish()
        else:
            self.save()

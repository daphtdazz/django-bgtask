import functools
import logging
import os
import time
import traceback
import uuid
from contextlib import contextmanager

from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.contenttypes.models import ContentType
from django.db import models, transaction
from django.forms.models import model_to_dict
from django.utils import timezone

from model_utils import Choices


log = logging.getLogger(__name__)


def locked(meth):
    @functools.wraps(meth)
    def _locked_meth(self, *args, **kwargs):
        if getattr(self, "_locked", False):
            return meth(self, *args, **kwargs)

        with transaction.atomic():
            BackgroundTask.objects.filter(id=self.id).select_for_update().only("id").get()
            self.refresh_from_db()

            # Mark as locked in case we are called recursively
            self._locked = True
            try:
                return meth(self, *args, **kwargs)
            finally:
                self._locked = False

    return _locked_meth


def only_if_state(state):
    def only_if_state_decorator(meth):
        def only_if_state_wrapper(self, *args, **kwargs):
            if self.state != state:
                raise RuntimeError(
                    "%s cannot execute %s as in state %s not %s"
                    % (self, meth.__name__, self.state, state)
                )
            return meth(self, *args, **kwargs)

        return only_if_state_wrapper

    return only_if_state_decorator


class BackgroundTask(models.Model):
    id = models.UUIDField(primary_key=True, editable=False, default=uuid.uuid4)
    name = models.CharField(
        max_length=1000,
        help_text=(
            "Name (or type) of this task, is not unique "
            "per task instance but generally per task functionality"
        ),
    )
    namespace = models.CharField(
        max_length=1000,
        default="",
        blank=True,
        help_text=(
            "Optional namespace that can be used to avoid having to make names unique across an "
            "entire codebase, allowing them to be shorter and human readable"
        ),
    )

    STATES = Choices("not_started", "running", "success", "partial_success", "failed")
    state = models.CharField(max_length=16, default=STATES.not_started, choices=STATES)
    steps_to_complete = models.PositiveIntegerField(
        null=True, blank=True, help_text="The number of steps in the task for it to be completed."
    )
    steps_completed = models.PositiveIntegerField(
        null=True, blank=True, help_text="The number of steps completed so far by this task"
    )

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

    class Meta:
        ordering = ["created", "id"]

    @property
    def task_dict(self):
        task_dict = model_to_dict(self)
        return {"id": str(self.id), "updated": self.updated.isoformat(), **task_dict}

    @property
    def num_failed_steps(self):
        return sum(error.get("num_failed_steps", 0) for error in self.errors)

    @property
    def incomplete(self):
        return self.state in [self.STATES.not_started, self.STATES.running]

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

    @locked
    @only_if_state(STATES.not_started)
    def start(self):
        log.info("%s starting", self)
        self.state = self.STATES.running
        self.started_at = timezone.now()
        self.save()

    @locked
    @only_if_state(STATES.running)
    def fail(self, exc):
        """Call to indicate a complete and final failure of the task"""
        log.info("%s failed: %s", self, exc)
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

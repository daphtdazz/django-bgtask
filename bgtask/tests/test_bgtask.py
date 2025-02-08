import pytest

from django.utils import timezone

from bgtask.models import BackgroundTask

pytestmark = pytest.mark.django_db


@pytest.fixture
def a_task():
    return BackgroundTask.objects.create(name="A task")


def test_bgtask_immediate_failure(a_task):
    assert a_task.state == BackgroundTask.STATES.not_started

    for method in [a_task.succeed, a_task.finish]:
        with pytest.raises(RuntimeError, match=r"cannot execute.*as in state not_started"):
            method()

    for method in [a_task.fail, a_task.succeed]:
        with pytest.raises(RuntimeError, match=r"cannot execute.*as in state not_started"):
            method("Some result")

    a_task.start()
    assert a_task.state == BackgroundTask.STATES.running

    try:
        raise Exception("Some global failure")
    except Exception as exc:
        a_task.fail(exc)

    assert a_task.state == BackgroundTask.STATES.failed

    assert len(a_task.errors) == 1
    assert a_task.errors[0]["datetime"] == a_task.completed_at.isoformat()
    assert a_task.errors[0]["error_message"] == "Some global failure"
    assert "test_bgtask_immediate_failure" in a_task.errors[0]["traceback"]


def test_bgtask_start_again(a_task):
    a_task.start()
    import time
    time.sleep(0.001)

    curr_started_at = a_task.started_at
    assert timezone.now() > curr_started_at

    # Starting again is no-op
    a_task.start()
    assert a_task.started_at == curr_started_at


def test_fails_if_exception(a_task):
    a_task.start()

    with pytest.raises(Exception):
        with a_task.fails_if_exception():
            raise Exception("fail!")

    assert a_task.state == BackgroundTask.STATES.failed


def test_set_steps(a_task):
    a_task.steps_completed = 10
    a_task.set_steps_to_complete(20)
    a_task.refresh_from_db()
    assert a_task.steps_to_complete == 20
    assert a_task.steps_completed == 0

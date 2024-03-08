import pytest

from bgtask.models import BackgroundTask


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
    assert a_task.errors[0]["datetime"] == "1970-01-01T00:00:00+00:00"
    assert a_task.errors[0]["error_message"] == "Some global failure"
    assert "test_bgtask_immediate_failure" in a_task.errors[0]["trackeback"]

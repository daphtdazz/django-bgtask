import functools
import operator
from typing import Iterable

from django.db import models, transaction


# https://stackoverflow.com/questions/29900386/how-to-construct-django-q-object-matching-none
Q_NONE = models.Q(pk__in=[])


def q_or(q_objects: Iterable[models.Q]):
    """Chain an iterable of Q with OR.

    The more Q()s are passed, the more things are filtered in, so it
    makes sense if nothing is passed nothing is filtered in.
    """
    return functools.reduce(operator.or_, q_objects, models.Q()) or Q_NONE


def locked(meth):
    @functools.wraps(meth)
    def _locked_meth(self, *args, **kwargs):
        if getattr(self, "_locked", False):
            return meth(self, *args, **kwargs)

        with transaction.atomic():
            type(self).objects.filter(id=self.id).select_for_update().only("id").get()
            self.refresh_from_db()

            # Mark as locked in case we are called recursively
            self._locked = True
            try:
                return meth(self, *args, **kwargs)
            finally:
                self._locked = False

    return _locked_meth


def only_if_state(state, no_op_states=frozenset()):
    def only_if_state_decorator(meth):
        def only_if_state_wrapper(self, *args, no_op_if_already_in_state=False, **kwargs):
            if self.state in no_op_states:
                return
            states = (state,) if isinstance(state, str) else tuple(state)
            if self.state not in states:
                raise RuntimeError(
                    "%s cannot execute %s as in state %s not one of %s"
                    % (self, meth.__name__, self.state, states)
                )
            return meth(self, *args, **kwargs)

        return only_if_state_wrapper

    return only_if_state_decorator

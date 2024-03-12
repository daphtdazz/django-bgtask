from uuid import uuid4

from django.db.models import CharField, Model, TextField, UUIDField


class ModelWithBackgroundActions(Model):
    id = UUIDField(default=uuid4, primary_key=True, editable=False)
    name = CharField()
    text = TextField(blank=True, default='')


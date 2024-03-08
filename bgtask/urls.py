from django.urls import re_path

from . import views


app_name = "bgtask"

urlpatterns = [
    re_path(r"tasks$", views.background_tasks_view, name="tasks"),
]

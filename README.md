# django-bgtask

Background task monitoring tool for django apps

## Installation

Grab it from PyPI, e.g:

```
pip install django-admin-background-task
```

## Setup

Add it to your django apps:

```
INSTALLED_APPS = [
    ...
    "bgtask",
]
```

And mount the admin monitoring URLs:

```
urlpatterns = [
    # You should be able to mount them anywhere but I put them here
    path(r"admin/background-task/", include("bgtask.urls")),
    path("admin", admin.site.urls),
]
```

## Usage

### Creating a task and updating it

```
from bgtask.models import BackgroundTask

BackgroundTask.new(name)

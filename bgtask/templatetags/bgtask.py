from urllib.parse import parse_qsl, unquote, urlparse, urlunparse

from django import template
from django.contrib.admin.utils import quote
from django.urls import Resolver404, get_script_prefix, resolve
from django.utils.http import urlencode

register = template.Library()


@register.simple_tag(takes_context=True)
def bgtask_script(context, popup=False, to_field=None):
    return "hello bgtask_script world"

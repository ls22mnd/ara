import os

from django import template

from ara.api.models import Playbook

register = template.Library()


@register.filter(name='get_playbook_name')
def get_playbook_name(playbook: Playbook):
    return '/'.join(os.path.dirname(playbook['path']).split('/')[-2:])


@register.filter(name='get_play_alert_type')
def get_play_alert_type(status: str):
    if status == 'running':
        return 'info'
    elif status == 'success':
        return 'success'
    elif status == 'fail':
        return 'danger'
    return 'dark'

import os

from django import template

register = template.Library()


@register.filter(name='get_playbook_name')
def get_playbook_name(playbook):
    return '/'.join(os.path.dirname(playbook['path']).split('/')[-2:])


@register.filter(name='get_playbook_alert_type')
def get_playbook_alert_type(playbook):
    s = playbook['status']
    if s == 'running':
        return 'info'
    elif s == 'completed':
        return 'success'
    elif s == 'failed':
        return 'danger'
    return 'dark'

from __future__ import (absolute_import, division, print_function)


__metaclass__ = type


def common_args() -> dict:
    return dict(
        platform=dict(type='str', required=False, default="kubernetes", choices=["kubernetes", "podman", "docker", "systemd"]),
        kubeconfig=dict(type='str', required=False),
        context=dict(type='str', required=False),
        namespace=dict(type='str', required=False),
    )


def add_fact(result, d):
    facts = result['ansible_facts'] if 'ansible_facts' in result else dict()
    facts.update(d)
    result['changed'] = True
    result['ansible_facts'] = facts

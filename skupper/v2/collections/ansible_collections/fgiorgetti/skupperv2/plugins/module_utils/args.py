import ipaddress
import re
from urllib.parse import urlparse


def common_args() -> dict:
    return dict(
        platform=dict(type='str', required=False, default="kubernetes", choices=[
                      "kubernetes", "podman", "docker", "systemd"]),
        kubeconfig=dict(type='str', required=False),
        context=dict(type='str', required=False),
        namespace=dict(type='str', required=False),
    )


def add_fact(result, d):
    facts = result['ansible_facts'] if 'ansible_facts' in result else {}
    facts.update(d)
    result['changed'] = True
    result['ansible_facts'] = facts


def is_valid_name(name: str, ignore_case=False) -> bool:
    # rfc1123 name validation
    return re.search("^[a-z0-9]([-a-z0-9]*[a-z0-9])?$", name if not ignore_case else name.lower())


def is_valid_host_ip(addr: str) -> bool:
    try:
        ipaddress.ip_address(addr)
        return True
    except Exception:
        pass
    if re.search(addr, "[/:]"):
        return False
    domain = urlparse("http://{}".format(addr)).hostname
    return domain == addr

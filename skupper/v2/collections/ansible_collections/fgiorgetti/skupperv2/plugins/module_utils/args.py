import ipaddress
import regex
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


def is_valid_name(name: str) -> bool:
    # rfc1123 name validation
    return regex.search("^[a-z0-9]([-a-z0-9]*[a-z0-9])?$", name)


def is_valid_host_ip(addr: str) -> bool:
    try:
        ipaddress.ip_address(addr)
        return True
    except Exception:
        pass
    if addr.__contains__("/"):
        return False
    domain = urlparse("http://{}".format(addr)).netloc
    return domain == addr

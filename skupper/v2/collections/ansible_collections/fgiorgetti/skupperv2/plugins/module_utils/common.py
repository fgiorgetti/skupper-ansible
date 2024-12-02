import os


def namespace_home(namespace: str) -> str:
    base_path = os.getenv("XDG_DATA_HOME") or os.path.join(os.getenv("HOME"), ".local", "share")
    if os.getuid() == 0:
        base_path = "/var/lib"
    namespace_home = os.path.join(base_path, "skupper", "namespaces", namespace or "default")
    return namespace_home


def resources_home(namespace: str) -> str:
    return os.path.join(namespace_home(namespace), "input", "resources")


def is_non_kube(platform: str) -> bool:
    return platform in ("podman", "docker", "systemd")

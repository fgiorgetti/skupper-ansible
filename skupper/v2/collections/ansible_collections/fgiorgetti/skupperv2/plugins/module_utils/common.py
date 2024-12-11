import os


def data_home() -> str:
    base_path = os.getenv("XDG_DATA_HOME") or os.path.join(os.getenv("HOME"), ".local", "share")
    if os.getuid() == 0:
        base_path = "/var/lib"
    return os.path.join(base_path, "skupper")


def namespace_home(namespace: str) -> str:
    base_path = data_home()
    home = os.path.join(base_path, "namespaces", namespace or "default")
    return home


def resources_home(namespace: str) -> str:
    return os.path.join(namespace_home(namespace), "input", "resources")


def is_non_kube(platform: str) -> bool:
    return platform in ("podman", "docker", "systemd")


def runtime_dir() -> str:
    uid = os.getuid()
    if uid == 0:
        return "/run"
    return os.environ.get("XDG_RUNTIME_DIR", "/run/user/%d" %(uid))


def config_dir() -> str:
    uid = os.getuid()
    if uid == 0:
        return "/etc"
    default_dir = os.path.join(os.getenv("HOME"), ".config")
    return os.environ.get("XDG_CONFIG_HOME", default_dir)


def service_dir() -> str:
    base_path = config_dir()
    if os.getuid() == 0:
        return os.path.join(base_path, "systemd", "system")
    return os.path.join(base_path, "systemd", "user")

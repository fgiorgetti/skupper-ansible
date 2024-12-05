from typing import Final
from .common import runtime_dir, data_home, service_dir, namespace_home
from .command import run_command
from .exceptions import RuntimeException
from ansible.module_utils.basic import AnsibleModule
import grp
import os


def container_endpoint(engine: str = "podman") -> str:
    env = os.environ.get("CONTAINER_ENDPOINT")
    if env:
        return env
    base_path = os.path.join("unix://", runtime_dir())
    match engine:
        case "docker":
            return os.path.join(base_path, "docker.sock")
        case "podman":
            return os.path.join(base_path, "podman", "podman.sock")
    return ""


def is_sock_endpoint(endpoint: str) -> bool:
    return endpoint.startswith(("/", "unix://"))


def userns(engine: str = "podman") -> str:
    match engine:
        case "docker":
            return "host"
        case "podman":
            if os.getuid() == 0:
                return ""
            return "keep-id"


def runas(engine: str = "podman") -> str:
    uid = os.getuid()
    gid = os.getgid()
    if engine == "docker":
        try:
            docker_grp = grp.getgrnam("docker")
            gid = docker_grp.gr_gid
        except KeyError as ex:
            raise RuntimeException("unable to determine docker group id")
    return "%d:%d" % (uid, gid)


def mounts(platform: str, engine: str = "podman") -> dict:
    mounts = {
        data_home(): "/output",
    }
    endpoint = container_endpoint(engine)
    if platform != "systemd" and is_sock_endpoint(endpoint):
        mounts[endpoint] = "/%s.sock" % (engine)
    return mounts


def env(platform: str, engine: str = "podman") -> dict:
    env = {
        "SKUPPER_OUTPUT_PATH": data_home(),
        "SKUPPER_PLATFORM": platform,
    }
    endpoint = container_endpoint(engine)
    if platform != "systemd":
        if is_sock_endpoint(endpoint):
            env["CONTAINER_ENDPOINT"] = "/%s.sock" % (engine)
        else:
            env["CONTAINER_ENDPOINT"] = endpoint
    return env

def systemd_available(module: AnsibleModule) -> bool:
    base_command = ["systemctl"]
    if os.getuid() != 0:
        base_command.append("--user")
    list_units_command = base_command + ["list-units"]
    code, _, err = run_command(module, list_units_command)
    if code != 0:
        module.warn("unable to detect systemd: %s" % (err))
    return code == 0


def systemd_create(module: AnsibleModule, service_name: str, service_file: str) -> bool:
    with open(service_file, "r") as in_file:
        with open(os.path.join(service_dir(), service_name), "w") as out_file:
            content = in_file.read()
            out_file.write(content)
    base_command = ["systemctl"]
    if os.getuid() != 0:
        base_command.append("--user")
    enable_command = base_command + ["enable", "--now", service_name]
    reload_command = base_command + ["daemon-reload"]
    code, _, err = run_command(module, enable_command)
    if code != 0:
        module.warn(
            "error enabling service '%s': %s" % (service_name, err))
    code, _, err = run_command(module, reload_command)
    if code != 0:
        module.warn("error reloading systemd daemon: %s" % (err))
    return code == 0


def start_service(module: AnsibleModule, namespace: str) -> bool:
    return _systemd_command(module, namespace, "start")


def stop_service(module: AnsibleModule, namespace: str) -> bool:
    return _systemd_command(module, namespace, "stop")


def _systemd_command(module: AnsibleModule, namespace: str, command: str) -> bool:
    name = service_name(namespace)
    base_command = ["systemctl"]
    if os.getuid() != 0:
        base_command.append("--user")
    system_status = base_command + ["status", name]
    pre_status, _, _ = run_command(module, system_status)
    system_command = base_command + [command, name]
    code, _, err = run_command(module, system_command)
    if code != 0:
        module.warn(
            "error executing %s command for service '%s': %s" % (command, name, err))
    post_status, _, _ = run_command(module, system_status)
    changed = code == 0 and pre_status != post_status
    return changed


def service_name(namespace: str = "default") -> str:
    return "skupper-%s.service" % (namespace)


def create_service(module: AnsibleModule, namespace: str = "default") -> bool:
    if not systemd_available(module):
        return
    name = service_name(namespace)
    file = os.path.join(namespace_home(
        namespace), "internal", "scripts", name)
    if not os.path.isfile(file):
        module.warn(
            "SystemD service has not been defined: %s" % (file))
        return
    return systemd_create(module, name, file)

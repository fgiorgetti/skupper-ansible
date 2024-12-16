import grp
import os
from ansible.module_utils.basic import AnsibleModule
from .common import runtime_dir, data_home, service_dir, namespace_home
from .command import run_command
from .exceptions import RuntimeException


def container_endpoint(engine: str = "podman") -> str:
    env_endpoint = os.environ.get("CONTAINER_ENDPOINT")
    if env_endpoint:
        return env_endpoint
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
            raise RuntimeException("unable to determine docker group id") from ex
    return "%d:%d" % (uid, gid)


def mounts(namespace: str, platform: str, engine: str = "podman") -> dict:
    mount_points = {
        data_home(): "/output",
        os.path.join(namespace_home(namespace), "input", "resources"): "/input",
    }
    endpoint = container_endpoint(engine)
    if platform != "systemd" and is_sock_endpoint(endpoint):
        mount_points[endpoint] = "/%s.sock" % (engine)
    return mount_points


def env(platform: str, engine: str = "podman") -> dict:
    container_env = {
        "SKUPPER_OUTPUT_PATH": data_home(),
        "SKUPPER_PLATFORM": platform,
    }
    endpoint = container_endpoint(engine)
    if platform != "systemd":
        if is_sock_endpoint(endpoint):
            container_env["CONTAINER_ENDPOINT"] = "/%s.sock" % (engine)
        else:
            container_env["CONTAINER_ENDPOINT"] = endpoint
    return container_env

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
    changed = False
    target_service_file = os.path.join(service_dir(), service_name)
    try:
        with open(service_file, "r", encoding="utf-8") as in_file:
            with open(target_service_file, "w", encoding="utf-8") as out_file:
                module.debug("writing service file: %s" % (target_service_file))
                content = in_file.read()
                wrote = out_file.write(content)
                module.debug("wrote: %d/%d" % (len(content), wrote))
                changed = True
    except Exception as ex:
        module.warn("error writing service file '%s': %s" % (target_service_file, ex))
        return changed
    base_command = ["systemctl"]
    if os.getuid() != 0:
        base_command.append("--user")
    enable_command = base_command + ["enable", "--now", service_name]
    reload_command = base_command + ["daemon-reload"]
    code, _, err = run_command(module, enable_command)
    if code != 0:
        module.warn(
            "error enabling service '%s': %s" % (service_name, err))
    else:
        changed = True
    code, _, err = run_command(module, reload_command)
    if code != 0:
        module.warn("error reloading systemd daemon: %s" % (err))
    else:
        changed = True
    return changed


def start_service(module: AnsibleModule, namespace: str) -> bool:
    return _systemd_command(module, namespace, "start")


def stop_service(module: AnsibleModule, namespace: str) -> bool:
    return _systemd_command(module, namespace, "stop")


def _systemd_command(module: AnsibleModule, namespace: str, command: str) -> bool:
    name = default_service_name(namespace)
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


def default_service_name(namespace: str = "default") -> str:
    return "skupper-%s.service" % (namespace)


def create_service(module: AnsibleModule, namespace: str = "default") -> bool:
    if not systemd_available(module):
        return False
    name = default_service_name(namespace)
    file = os.path.join(namespace_home(
        namespace), "internal", "scripts", name)
    if not os.path.isfile(file):
        module.warn(
            "SystemD service has not been defined: %s" % (file))
        return False
    return systemd_create(module, name, file)


def systemd_delete(module: AnsibleModule, service_name: str) -> bool:
    changed = False
    service_file = os.path.join(service_dir(), service_name)
    if not os.path.isfile(service_file):
        module.warn(
            "SystemD service has not been defined: %s" % (service_file))

    base_command = ["systemctl"]
    if os.getuid() != 0:
        base_command.append("--user")

    disable_command = base_command + ["disable", "--now", service_name]
    reload_command = base_command + ["daemon-reload"]
    reset_command = base_command + ["reset-failed"]

    # stopping service
    code, _, err = run_command(module, disable_command)
    if code != 0:
        module.warn(
            "error stopping service '%s': %s" % (service_name, err))
    else:
        changed = True

    # removing service file
    try:
        os.remove(service_file)
        changed = True
    except Exception as ex:
        module.warn("error removing service file '%s': %s" % (service_file, ex))

    # reloading systemd
    for command in [reload_command, reset_command]:
        code, _, err = run_command(module, command)
        if code != 0:
            module.warn("error running systemd command '%s': %s" % (command, err))
        else:
            changed = True

    return changed


def delete_service(module: AnsibleModule, namespace: str = "default") -> bool:
    if not systemd_available(module):
        return False
    name = default_service_name(namespace)
    return systemd_delete(module, name)

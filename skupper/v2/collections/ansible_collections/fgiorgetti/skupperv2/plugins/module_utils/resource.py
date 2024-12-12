from __future__ import (absolute_import, division, print_function)
import os
import yaml
from .args import is_valid_name
from .exceptions import ResourceException


__metaclass__ = type


def load(path: str, platform: str, maxdepth=3) -> str:
    yamls = []
    if os.path.isdir(path):
        for (dirpath, _, filenames) in os.walk(path):
            if dirpath == path:
                depth = 0
            else:
                dirpathclean = dirpath[len(path):].lstrip('/').rstrip('/')
                depth = len(dirpathclean.split(os.sep))
            if depth <= maxdepth:
                yamls.extend([os.path.join(dirpath, filename)
                              for filename in filenames
                              if filename.lower().endswith((".yaml", ".yml"))])
    else:
        yamls.append(path)
    objects = []
    for filename in yamls:
        with open(filename, "r", encoding="utf-8") as stream:
            for obj in yaml.safe_load_all(stream):
                if platform not in ("podman", "docker", "systemd") or allowed(obj):
                    objects.append(obj)
    definitions = yaml.safe_dump_all(objects)
    return definitions


def allowed(obj: dict) -> bool:
    api_version, kind = version_kind(obj)
    return api_version in ("skupper.io/v2alpha1") or kind in ("Secret")


def version_kind(obj):
    api_version = obj["apiVersion"] if "apiVersion" in obj else ""
    kind = obj["kind"] if "kind" in obj else ""
    return api_version, kind


def dump(definitions: str, namespace: str, overwrite: bool) -> bool:
    from .common import resources_home
    changed = False
    home = resources_home(namespace)
    if not os.path.exists(home):
        os.makedirs(home)
    elif not os.path.isdir(home):
        raise ResourceException("%s is not a directory" % (home))
    for obj in yaml.safe_load_all(definitions):
        if not isinstance(obj, dict):
            continue
        _, kind = version_kind(obj)
        name = obj.get("metadata", {}).get("name")
        if not name or not allowed(obj):
            continue
        if not is_valid_name(name):
            continue
        if not kind or not is_valid_name(kind, ignore_case=True):
            continue
        obj_namespace = obj.get("metadata", {}).get("namespace", "")
        if obj_namespace == "":
            obj["metadata"]["namespace"] = namespace
        filename = os.path.join(home, "%s-%s.yaml" % (kind, name))
        if os.path.exists(filename) and not overwrite:
            continue
        with open(filename, 'w', encoding='utf-8') as yaml_file:
            yaml.safe_dump(obj, yaml_file, indent=2)
            changed = True
    return changed


def delete(definitions: str, namespace: str) -> bool:
    from .common import resources_home
    changed = False
    home = resources_home(namespace)
    if not os.path.exists(home):
        return changed
    if not os.path.isdir(home):
        raise ResourceException("%s is not a directory" % (home))

    for obj in yaml.safe_load_all(definitions):
        _, kind = version_kind(obj)
        name = obj.get("metadata", {}).get("name")
        if not name or not is_valid_name(name):
            continue
        if not kind or not is_valid_name(kind, ignore_case=True):
            continue
        filename = os.path.join(home, "%s-%s.yaml" % (kind, name))
        if os.path.exists(filename):
            os.remove(filename)
            changed = True
    return changed

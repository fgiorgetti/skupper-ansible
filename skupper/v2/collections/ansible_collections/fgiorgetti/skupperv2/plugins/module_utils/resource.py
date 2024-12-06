from __future__ import (absolute_import, division, print_function)
from .common import resources_home
from .exceptions import ResourceException
import os
import yaml


__metaclass__ = type


def load(path: str, platform: str, maxdepth=3) -> str:
    yamls = []
    try:
        import yaml
    except ImportError:
        return yamls

    if os.path.isdir(path):
        for (dirpath, dirnames, filenames) in os.walk(path):
            if dirpath == path:
                depth = 0
            else:
                dirpathclean = dirpath[len(path):].lstrip('/').rstrip('/')
                depth = len(dirpathclean.split(os.sep))
            if depth <= maxdepth:
                yamls.extend([os.path.join(dirpath, filename)
                            for filename in filenames if filename.lower().endswith((".yaml", ".yml"))])
    else:
        yamls.append(path)
    objects = []
    for filename in yamls:
        with open(filename) as stream:
            for obj in yaml.safe_load_all(stream):
                if platform not in ("podman", "docker", "systemd") or allowed(obj):
                    objects.append(obj)
    definitions = yaml.safe_dump_all(objects)
    return definitions


def allowed(obj: dict) -> bool:
    apiVersion, kind = version_kind(obj)
    return apiVersion in ("skupper.io/v2alpha1") or kind in ("Secret")


def version_kind(obj):
    apiVersion = obj["apiVersion"] if "apiVersion" in obj else ""
    kind = obj["kind"] if "kind" in obj else ""
    return apiVersion, kind


def dump(definitions: str, namespace: str, overwrite: bool) -> bool:
    changed = False
    home = resources_home(namespace)
    if not os.path.exists(home):
        os.makedirs(home)
    elif not os.path.isdir(home):
        raise ResourceException("%s is not a directory" % (home))

    for obj in yaml.safe_load_all(definitions):
        if type(obj) is not dict:
            continue
        apiVersion, kind = version_kind(obj)
        name = obj.get("metadata", {}).get("name")
        if not name or not allowed(obj):
            continue
        obj_namespace = obj.get("metadata", {}).get("namespace", "")
        if obj_namespace == "":
            obj["metadata"]["namespace"] = namespace
        filename = os.path.join(home, "%s-%s.yaml" % (kind, name))
        if os.path.exists(filename) and not overwrite:
            continue
        with open(filename, 'w') as yaml_file:
            yaml.safe_dump(obj, yaml_file, indent=2)
            changed = True
    return changed


def delete(definitions: str, namespace: str) -> bool:
    changed = False
    home = resources_home(namespace)
    if not os.path.exists(home):
        return changed
    elif not os.path.isdir(home):
        raise ResourceException("%s is not a directory" % (home))

    for obj in yaml.safe_load_all(definitions):
        apiVersion, kind = version_kind(obj)
        name = obj.get("metadata", {}).get("name")
        if not name:
            continue
        filename = os.path.join(home, "%s-%s.yaml" % (kind, name))
        if os.path.exists(filename):
            os.remove(filename)
            changed = True
    return changed

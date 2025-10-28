from __future__ import (absolute_import, division, print_function)
__metaclass__ = type


from .args import is_valid_name
from .resource import version_kind
from .exceptions import K8sException
try:
    from kubernetes import client, config, dynamic
    from kubernetes.dynamic.exceptions import ApiException
    import json
    import yaml
    import os
except ImportError:
    pass


class K8sClient:
    def __init__(self, kubeconfig: str, context: str) -> None:
        self.kubeconfig = kubeconfig or os.path.join(
            os.getenv("HOME"), ".kube", "config")
        self.context = context
        config.load_kube_config(
            config_file=self.kubeconfig,
            context=context,
        )
        self.client = dynamic.DynamicClient(client.ApiClient())

    def api(self, **kwargs):
        return self.client.resources.get(**kwargs)

    def create_or_patch(self, namespace: str, definitions: str, overwrite: bool) -> bool:
        changed = False
        for obj in yaml.safe_load_all(definitions):
            if not isinstance(obj, dict):
                continue
            version, kind = version_kind(obj)
            if namespace:
                obj.get("metadata", {})["namespace"] = namespace
            obj_namespace = obj.get("metadata", {}).get("namespace", "default")
            if not is_valid_name(obj_namespace):
                raise K8sException("invalid namespace (rfc1123): {}".format(obj_namespace))
            api = self.api(api_version=version, kind=kind)
            try:
                api.create(body=obj, namespace=obj_namespace)
                changed = True
            except ApiException as api_ex:
                if api_ex.reason == "Conflict":
                    if not overwrite:
                        continue
                    # try merging
                    self._patch(api, obj, obj_namespace)
                    changed = True
                else:
                    body = json.loads(api_ex.body)
                    message = "reason: %s - status: %s - message: %s" % (
                        api_ex.reason, api_ex.status, body.get("message"))
                    raise K8sException(message) from api_ex
        return changed

    def _patch(self, api, obj: dict, namespace):
        try:
            api.patch(body=obj, namespace=namespace,
                      content_type="application/merge-patch+json")
        except ApiException as api_ex:
            body = json.loads(api_ex.body)
            message = "reason: %s - status: %s - message: %s" % (
                api_ex.reason, api_ex.status, body.get("message"))
            raise K8sException(message) from api_ex

    def delete(self, namespace: str, definitions: str) -> bool:
        changed = False
        objects = yaml.safe_load_all(definitions)
        for obj in objects:
            if not isinstance(obj, dict):
                continue
            version, kind = version_kind(obj)
            obj_name = obj.get("metadata", {}).get("name")
            obj_namespace = namespace or obj.get("metadata", {}).get("namespace", "default")
            if not is_valid_name(obj_namespace):
                raise K8sException("invalid namespace (rfc1123): {}".format(obj_namespace))
            if not obj_name:
                continue
            api = self.api(api_version=version, kind=kind)
            try:
                api.delete(name=obj_name, namespace=obj_namespace)
                changed = True
            except ApiException as api_ex:
                if api_ex.status == 404:
                    continue
                body = json.loads(api_ex.body)
                message = "reason: %s - status: %s - message: %s" % (
                    api_ex.reason, api_ex.status, body.get("message"))
                raise K8sException(message) from api_ex
        return changed

    def get(self, namespace: str, version: str, kind: str, name: str):
        resources = []
        api = self.api(api_version=version, kind=kind)
        try:
            res = api.get(name=name, namespace=namespace)
            if name:
                return res.to_dict()
            resources.extend([item.to_dict() for item in res.get("items", [])])
            return resources
        except ApiException as api_ex:
            body = json.loads(api_ex.body)
            message = "reason: %s - status: %s - message: %s" % (
                api_ex.reason, api_ex.status, body.get("message"))
            raise K8sException(message, status=api_ex.status) from api_ex


def has_condition(res: dict, condition: str, status: bool = True) -> bool:
    for res_condition in res.get("status", {}).get("conditions", []):
        if res_condition.get("type", "") == condition and \
                res_condition.get("status", "False") == str(status):
            return True
    return False

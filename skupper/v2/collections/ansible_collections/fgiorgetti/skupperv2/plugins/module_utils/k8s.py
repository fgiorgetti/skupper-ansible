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
            obj_namespace = obj.get("metadata", {}).get("namespace", "default")
            if obj_namespace != (namespace or "default"):
                if obj_namespace == "default":
                    obj["metadata"]["namespace"] = namespace
                else:
                    raise K8sException("namespace cannot be set to '%s' as resource "
                                       "is defined with namespace '%s'" % (namespace, obj_namespace))
            api = self.api(api_version=version, kind=kind)
            try:
                api.create(body=obj, namespace=namespace)
                changed = True
            except ApiException as api_ex:
                if api_ex.reason == "Conflict":
                    if not overwrite:
                        continue
                    # try merging
                    obj = api.patch(body=obj, namespace=namespace,
                                    content_type="application/merge-patch+json")
                    changed = True
                else:
                    body = json.loads(api_ex.body)
                    message = "reason: %s - status: %s - message: %s" % (
                        api_ex.reason, api_ex.status, body.get("message"))
                    raise K8sException(message) from api_ex
        return changed

    def delete(self, namespace: str, definitions: str) -> bool:
        changed = False
        objects = yaml.safe_load_all(definitions)
        for obj in objects:
            if not isinstance(obj, dict):
                continue
            version, kind = version_kind(obj)
            obj_name = obj.get("metadata", {}).get("name")
            if not obj_name:
                continue
            api = self.api(api_version=version, kind=kind)
            try:
                api.delete(name=obj_name, namespace=namespace)
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

from .resource import version_kind
from .exceptions import K8sException
try:
    from kubernetes import client, config, dynamic
    from kubernetes.dynamic.exceptions import ApiException
    import json
    import yaml
except ImportError:
    pass


def create_or_patch(kubeconfig: str, context: str, namespace: str, definitions: str, overwrite: bool) -> bool:
    changed = False
    objects = yaml.safe_load_all(definitions)
    api_config=config.load_kube_config(
        config_file=kubeconfig,
        context=context,
    )
    dynamic_client = dynamic.DynamicClient(client.ApiClient(configuration=api_config))
    for obj in objects:
        if type(obj) is not dict:
            continue
        version, kind = version_kind(obj)
        obj_namespace = obj.get("metadata", {}).get("namespace", "default")
        if obj_namespace != (namespace or "default"):
            if obj_namespace == "default":
                obj["metadata"]["namespace"] = namespace
            else:
                raise Exception("namespace cannot be set to '%s' as resource is defined with namespace '%s'" %(namespace, obj_namespace))
        api = dynamic_client.resources.get(api_version=version, kind=kind)
        try:
            res = api.create(body=obj, namespace=namespace)
            changed = True
        except ApiException as apiEx:
            if apiEx.reason == "Conflict":
                if not overwrite:
                    continue
                # try merging
                obj = api.patch(body=obj, namespace=namespace, content_type="application/merge-patch+json")
                changed = True
            else:
                body = json.loads(apiEx.body)
                message = "reason: %s - status: %s - message: %s" %(apiEx.reason, apiEx.status, body.get("message"))
                raise(K8sException(message))
    return changed


def delete(kubeconfig: str, context: str, namespace: str, definitions: str) -> bool:
    changed = False
    objects = yaml.safe_load_all(definitions)
    api_config=config.load_kube_config(
        config_file=kubeconfig,
        context=context,
    )
    dynamic_client = dynamic.DynamicClient(client.ApiClient(configuration=api_config))
    for obj in objects:
        if type(obj) is not dict:
            continue
        version, kind = version_kind(obj)
        obj_name = obj.get("metadata", {}).get("name")
        if not obj_name:
            continue
        api = dynamic_client.resources.get(api_version=version, kind=kind)
        try:
            res = api.delete(name=obj_name, namespace=namespace)
            changed = True
        except ApiException as apiEx:
            if apiEx.status == 404:
                continue
            body = json.loads(apiEx.body)
            message = "reason: %s - status: %s - message: %s" %(apiEx.reason, apiEx.status, body.get("message"))
            raise(K8sException(message))
    return changed

"""kubeconfig 로딩 공용 헬퍼 — incluster → 로컬 kubeconfig(k8s_context) 폴백."""


def load_kube(settings) -> None:
    from kubernetes import config  # lazy: k8s SDK

    try:
        config.load_incluster_config()
    except config.ConfigException:
        config.load_kube_config(context=settings.k8s_context or None)

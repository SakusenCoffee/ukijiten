"""Automatic answers for connector internals; account setup is browser-only."""


def browser_answer(name):
    if name in ('config_is_local','config_shared_client_id','config_browser','config_refresh_token'):
        return 'true'
    return None

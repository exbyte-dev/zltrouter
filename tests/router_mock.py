import json
from urllib.parse import parse_qs, urlparse

import responses

PROC_GET = "http://192.168.0.1/reqproc/proc_get"
PROC_POST = "http://192.168.0.1/reqproc/proc_post"


def install_get(values: dict) -> None:
    """Register a GET proc_get callback that answers by `cmd`.

    `values` maps a proc_get key -> string value. Device-special cmds:
      - cmd 'get_random_login' -> {'random_login': values.get('random_login', '')}
      - cmd 'get_token'        -> {'token': values['token']} if 'token' in values,
                                   else {'get_token': values.get('get_token', '')}
    Any other cmd (possibly comma-joined) -> {k: values.get(k, '') for k in keys}.
    Order-independent: works no matter how many times each cmd is fetched.
    """
    def callback(request):
        cmd = parse_qs(urlparse(request.url).query).get("cmd", [""])[0]
        if cmd == "get_random_login":
            body = {"random_login": values.get("random_login", "")}
        elif cmd == "get_token":
            body = {"token": values["token"]} if "token" in values \
                else {"get_token": values.get("get_token", "")}
        else:
            body = {key: values.get(key, "") for key in cmd.split(",")}
        return (200, {}, json.dumps(body))

    responses.add_callback(responses.GET, PROC_GET, callback=callback)


def install_post(result: str = "success", headers: dict | None = None,
                 extra: dict | None = None) -> None:
    body = {"result": result}
    if extra:
        body.update(extra)
    responses.add(responses.POST, PROC_POST, json=body, headers=headers or {})

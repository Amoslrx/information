"""Optional provider-neutral model gateway: JSON request on stdin, fields JSON on stdout.

Set NOTICE_MODEL_URL to a service accepting the extraction request contract.
NOTICE_MODEL_TOKEN is an optional bearer token; it is never printed.
The gateway must return the structured fields object, not a chat response envelope.
"""
import json
import os
import sys
import urllib.request
from urllib.parse import urlsplit


def model_request(request):
    if os.environ.get('NOTICE_MODEL_PROTOCOL', 'gateway') == 'gateway':
        return request
    if os.environ.get('NOTICE_MODEL_PROTOCOL') != 'chat':
        raise ValueError('unknown model protocol')
    model = os.environ.get('NOTICE_MODEL_NAME', '')
    if not model:
        raise ValueError('configure NOTICE_MODEL_NAME')
    return {'model': model, 'messages': [
        {'role': 'system', 'content': request['instructions']},
        {'role': 'user', 'content': json.dumps(request, ensure_ascii=False)}],
        'response_format': {'type': 'json_object'}}


def model_response(payload):
    if os.environ.get('NOTICE_MODEL_PROTOCOL', 'gateway') == 'gateway':
        return payload
    content = payload['choices'][0]['message']['content']
    if not isinstance(content, str):
        raise ValueError('model did not return JSON text')
    return json.loads(content)


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        raise ValueError('model endpoint redirect refused')


def main():
    url = os.environ.get('NOTICE_MODEL_URL', '')
    parsed = urlsplit(url)
    if not (parsed.scheme == 'https' or (parsed.scheme == 'http' and parsed.hostname in ('localhost', '127.0.0.1'))) or parsed.username or parsed.password:
        raise ValueError('configure HTTPS or local NOTICE_MODEL_URL')
    request = json.load(sys.stdin)
    headers = {'Content-Type': 'application/json; charset=utf-8', 'Accept': 'application/json'}
    token = os.environ.get('NOTICE_MODEL_TOKEN')
    if token:
        headers['Authorization'] = 'Bearer ' + token
    req = urllib.request.Request(url, data=json.dumps(model_request(request), ensure_ascii=False).encode('utf-8'), headers=headers)
    with urllib.request.build_opener(NoRedirect()).open(req, timeout=75) as response:
        payload = response.read(2_000_001)
    if len(payload) > 2_000_000:
        raise ValueError('model response too large')
    sys.stdout.buffer.write(json.dumps(model_response(json.loads(payload)), ensure_ascii=False).encode('utf-8'))


if __name__ == '__main__':
    main()

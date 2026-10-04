"""Optional provider-neutral model gateway: JSON request on stdin, fields JSON on stdout.

Set NOTICE_MODEL_URL to a service accepting the extraction request contract.
NOTICE_MODEL_TOKEN is an optional bearer token; it is never printed.
The gateway must return the structured fields object, not a chat response envelope.
"""
import json
import os
import sys
import urllib.request


def main():
    url = os.environ.get('NOTICE_MODEL_URL', '')
    if not url.startswith(('https://', 'http://localhost:', 'http://127.0.0.1:')):
        raise ValueError('configure HTTPS or local NOTICE_MODEL_URL')
    request = json.load(sys.stdin)
    headers = {'Content-Type': 'application/json; charset=utf-8', 'Accept': 'application/json'}
    token = os.environ.get('NOTICE_MODEL_TOKEN')
    if token:
        headers['Authorization'] = 'Bearer ' + token
    req = urllib.request.Request(url, data=json.dumps(request, ensure_ascii=False).encode('utf-8'), headers=headers)
    with urllib.request.urlopen(req, timeout=75) as response:
        payload = response.read(2_000_001)
    if len(payload) > 2_000_000:
        raise ValueError('model response too large')
    sys.stdout.buffer.write(json.dumps(json.loads(payload), ensure_ascii=False).encode('utf-8'))


if __name__ == '__main__':
    main()

"""Disposable local MCP fixture: JSON-RPC over stdio, no sockets or account access."""
import json
import os
import sys


for line in sys.stdin:
    request = json.loads(line)
    if 'id' not in request:
        continue
    method = request.get('method')
    if method == 'initialize':
        result = {
            'protocolVersion': request['params']['protocolVersion'],
            'capabilities': {'tools': {'listChanged': False}},
            'serverInfo': {'name': 'harmless-local-stdio', 'version': '1.0'},
            'instructions': 'Constant local fixture ' + os.environ.get('FIXTURE_SECRET', ''),
        }
    elif method == 'tools/list':
        result = {'tools': [{'name': 'constant', 'description': 'Return a harmless constant',
                             'inputSchema': {'type': 'object', 'properties': {}}}]}
    elif method == 'tools/call':
        result = {'content': [{'type': 'text', 'text': 'harmless constant'}], 'isError': False}
    elif method == 'ping':
        result = {}
    else:
        print(json.dumps({'jsonrpc': '2.0', 'id': request['id'],
                          'error': {'code': -32601, 'message': 'Unknown fixture method'}}), flush=True)
        continue
    print(json.dumps({'jsonrpc': '2.0', 'id': request['id'], 'result': result}), flush=True)

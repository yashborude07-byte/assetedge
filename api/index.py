import json
import sys
import os
import io
from contextlib import redirect_stdout

sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'assetedge-final'))

from backend import app

def handler(request):
    """
    Vercel Python Serverless Function
    Expects Vercel request format
    """
    # Parse path, method, headers, body
    path = request['path']
    method = request['method']
    headers = request.get('headers', {})
    body = request.get('body', '')
    
    # Body handling
    if isinstance(body, str):
        body = body.encode()
    
    # Create environ for Flask
    environ = {
        'REQUEST_METHOD': method,
        'PATH_INFO': path,
        'SCRIPT_NAME': '',
        'SERVER_NAME': headers.get('host', 'localhost'),
        'SERVER_PORT': '443' if headers.get('x-forwarded-proto', 'http') == 'https' else '80',
        'wsgi.url_scheme': headers.get('x-forwarded-proto', 'http'),
        'wsgi.input': io.BytesIO(body),
        'CONTENT_LENGTH': str(len(body)),
        'CONTENT_TYPE': headers.get('content-type', ''),
    }
    
    # Add headers
    for k, v in headers.items():
        key = 'HTTP_' + k.upper().replace('-', '_')
        environ[key] = v
    
    # Flask dispatch
    with app.test_request_context(path, environ):
        try:
            rv = app.full_dispatch_request()
            response = app.response_class(
                response=rv.get_data(as_text=True) if hasattr(rv, 'get_data') else rv.data,
                status=rv.status_code,
                headers=dict(rv.headers) if hasattr(rv, 'headers') else {}
            )
        except Exception as e:
            return {
                'statusCode': 500,
                'headers': {'Content-Type': 'text/plain'},
                'body': f'Server Error: {str(e)}'
            }
    
    resp = {
        'statusCode': response.status_code,
        'headers': dict(response.headers),
        'body': response.get_data(as_text=True)
    }
    
    return resp





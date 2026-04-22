import sys
import os
import io
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from assetedge_final.backend import app as flask_app

def handler(request):
    """Vercel Python handler"""
    from flask import Request as FlaskRequest
    from werkzeug.wrappers import Response
    
    # Create Flask request
    flask_req = FlaskRequest.from_environ({
        'PATH_INFO': request.get('path', '/'),
        'REQUEST_METHOD': request.get('method', 'GET'),
        'HTTP_HOST': request.get('headers', {}).get('host', 'localhost'),
        'wsgi.input': io.BytesIO(request.get('body', b'') or b''),
        **{k.lower().replace('-', '_'): v for k, v in (request.get('headers', {}) or {}).items()}
    })
    
    # Dispatch through Flask app
    with flask_app.test_request_context(flask_req.path, flask_req):
        flask_app.preprocess_request()
        rv = flask_app.full_dispatch_request()
        response = flask_app.make_response(rv)
    
    return {
        'statusCode': response.status_code,
        'headers': dict(response.headers),
        'body': response.get_data(as_text=True)
    }




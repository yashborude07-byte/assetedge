import sys
import os
import io
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from assetedge_final.backend import app as flask_app

def handler(request):
    """Vercel Python handler"""
    path = request['path']
    method = request['method']
    
    with flask_app.test_request_context(path, method=method):
        flask_app.preprocess_request()
        resp = flask_app.handle_request()
    
    return {
        'statusCode': resp.status_code,
        'headers': dict(resp.headers),
        'body': resp.get_data(as_text=True)
    }



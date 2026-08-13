from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import urlparse

VERSION_RESPONSE = r'''{"result":{"platform":"android","zipfilename":"update","platformid":"8888","versionname":"update.manifest","app_update_url":"http://35.221.225.145:8080/patchserver/download_apk?ver=117","SellClannelId":"0","isTest":"0","projectname":"update.manifest","mini_ver":"26062101","url":"http://download.supergame.one:80/patch-manager-static/"},"status":1}'''

class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        print(f'"GET {self.path} HTTP/1.1"')

        parsed = urlparse(self.path)

        if parsed.path == "/rxcqLogin/getVersion":
            body = VERSION_RESPONSE.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return

        body = b"OK"
        self.send_response(200)
        self.send_header("Content-Type", "text/plain")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format, *args):
        print(format % args)

if __name__ == "__main__":
    server = HTTPServer(("0.0.0.0", 9999), Handler)
    print("[HTTP] listening on 0.0.0.0:9999")
    server.serve_forever()
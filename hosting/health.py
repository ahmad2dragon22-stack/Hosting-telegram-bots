from http.server import BaseHTTPRequestHandler, HTTPServer
import threading


class HealthCheckHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/":
            self.send_response(200)
            self.send_header("Content-type", "text/plain")
            self.end_headers()
            self.wfile.write(b"OK")
        else:
            self.send_response(404)
            self.end_headers()


def run_health_server(port: int = 8000):
    server_address = ("", port)
    httpd = HTTPServer(server_address, HealthCheckHandler)
    print(f"Health check server running on port {port}...")
    httpd.serve_forever()

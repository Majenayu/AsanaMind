import http.server
import socketserver
import os

PORT = 5000

class MyHTTPRequestHandler(http.server.SimpleHTTPRequestHandler):
    def end_headers(self):
        self.send_header('Cache-Control', 'no-cache, no-store, must-revalidate')
        self.send_header('Pragma', 'no-cache')
        self.send_header('Expires', '0')
        super().end_headers()

    def log_message(self, format, *args):
        print(f"[SERVER] {self.address_string()} - {format % args}")

os.chdir(os.path.dirname(os.path.abspath(__file__)))

Handler = MyHTTPRequestHandler

class ReusableTCPServer(socketserver.TCPServer):
    allow_reuse_address = True

with ReusableTCPServer(("0.0.0.0", PORT), Handler) as httpd:
    print(f"✓ SUNDAY Yoga Platform server running on http://0.0.0.0:{PORT}")
    print(f"✓ Access your yoga AR correction system at the URL above")
    print(f"✓ Camera permissions will be requested when you start AR correction")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\n✓ Server stopped")

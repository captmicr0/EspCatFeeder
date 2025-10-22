import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

# Simple request handler
class FeedHandler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        return
    
    def do_GET(self):
        if self.path == '/feedPortion':
            print(f"Received request on port {self.server.server_port} for {self.path}")
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b'feeding portion')
        else:
            self.send_response(404)
            self.end_headers()

# Function to start each server
def start_server(port):
    server = HTTPServer(('0.0.0.0', port), FeedHandler)
    print(f"Server started on port {port}")
    server.serve_forever()

# Launch all three servers in threads
ports = [60081, 60082, 60083]
for port in ports:
    threading.Thread(target=start_server, args=(port,), daemon=True).start()

print(f"Servers are running on ports {ports}. Press Ctrl+C to stop.")

# Keep the main thread alive
try:
    while True:
        pass
except KeyboardInterrupt:
    print("\nServers stopped.")

from http.server import HTTPServer, BaseHTTPRequestHandler
import urllib.parse, requests, mimetypes
import os, sys, signal, threading, json
from functools import partial
from concurrent.futures import ThreadPoolExecutor
from http.server import ThreadingHTTPServer
import time
from datetime import datetime
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler

# File to store mappings persistently
MAPPINGS_FILE = 'feederdata.json'

# List to store all feeders
feeders = []

# List to store all times
times = []

class MyHandler(FileSystemEventHandler):
    def __init__(self, filename):
        self.filename = filename
        self.is_self_writing = False

    def on_modified(self, event):
        if not event.is_directory and event.src_path.endswith(self.filename):
            if not self.is_self_writing:
                print(f"[*] Feeders and times file [{MAPPINGS_FILE}] modified")
                load_data()

fileEventHandler = MyHandler(MAPPINGS_FILE)

def load_data():
    global feeders, times
    if os.path.exists(MAPPINGS_FILE):
        with open(MAPPINGS_FILE, 'r') as f:
            data = json.load(f)
            feeders = data.get('feeders', {})
            times = data.get('times', [])
            print("[*] Loaded feeders and times from file.")
    else:
        print("[*] No save file found. Starting fresh.")

def save_data():
    global feeders, times, fileEventHandler
    fileEventHandler.is_self_writing = True
    with open(MAPPINGS_FILE, 'w') as f:
        json.dump({'feeders': feeders, 'times': times}, f)
        print("[*] Feeders and times saved to file.")
    fileEventHandler.is_self_writing = False

class RequestHandler(BaseHTTPRequestHandler):
    def redirect(self, url):
        return f'<meta http-equiv="refresh" content="3; url={url}" />'
    
    def do_POST(self):
        global feeders, times

        if self.path == '/getFeeders':
            self.send_response(200)
            self.send_header('Content-type', 'application/json')
            self.end_headers()

            self.wfile.write(bytes(json.dumps(feeders), "utf-8"))
        
        elif self.path == '/addFeeder':
            content_length = int(self.headers['Content-Length'])
            post_data = self.rfile.read(content_length).decode('utf-8')
            params = urllib.parse.parse_qs(post_data)
            
            feeder = params.get('feeder', [''])[0]

            already_exist = feeder in feeders
            if not already_exist:
                feeders.append(feeder)
                save_data()

            self.send_response(200)
            self.send_header('Content-type', 'text/plain')
            self.end_headers()

            self.wfile.write(bytes(json.dumps(not already_exist), "utf-8"))
        
        elif self.path == '/removeFeeder':
            content_length = int(self.headers['Content-Length'])
            post_data = self.rfile.read(content_length).decode('utf-8')
            params = urllib.parse.parse_qs(post_data)
            
            feeder = params.get('feeder', [''])[0]

            already_exist = feeder in feeders
            if already_exist:
                feeders.remove(feeder)
                save_data()

            self.send_response(200)
            self.send_header('Content-type', 'text/plain')
            self.end_headers()

            self.wfile.write(bytes(json.dumps(already_exist), "utf-8"))
        
        elif self.path == '/getTimes':
            self.send_response(200)
            self.send_header('Content-type', 'application/json')
            self.end_headers()

            self.wfile.write(bytes(json.dumps(times), "utf-8"))
        
        elif self.path == '/addTime':
            content_length = int(self.headers['Content-Length'])
            post_data = self.rfile.read(content_length).decode('utf-8')
            params = urllib.parse.parse_qs(post_data)
            
            time = params.get('time', [''])[0]

            already_exist = time in times
            if not already_exist:
                times.append(time)
                save_data()

            self.send_response(200)
            self.send_header('Content-type', 'text/plain')
            self.end_headers()

            self.wfile.write(bytes(json.dumps(not already_exist), "utf-8"))
        
        elif self.path == '/removeTime':
            content_length = int(self.headers['Content-Length'])
            post_data = self.rfile.read(content_length).decode('utf-8')
            params = urllib.parse.parse_qs(post_data)
            
            time = params.get('time', [''])[0]
            
            already_exist = any([True for x in times if x.startswith(time)])
            if already_exist:
                idx = [i for i, x in enumerate(times) if x.startswith(time)][0]
                times.pop(idx)
                save_data()

            self.send_response(200)
            self.send_header('Content-type', 'text/plain')
            self.end_headers()

            self.wfile.write(bytes(json.dumps(already_exist), "utf-8"))
        
        else:
            self.send_error(404, "Not Found")

    def do_GET(self):
        if self.path == "/":
            self.path = "/index.html"
        
        # Remove leading slash and join with 'websrc' directory
        file_path = self.path.lstrip('/')
        
        # Check if file exists
        if os.path.isfile(file_path):
            mime_type, _ = mimetypes.guess_type(file_path)
            if mime_type is None:
                mime_type = 'text/plain'
            
            # Read file content
            with open(file_path, 'r') as file:
                content = file.read()

                # Send response
                self.send_response(200)
                self.send_header('Content-type', mime_type)
                self.send_header('Content-Length', str(len(content)))
                self.end_headers()
                self.wfile.write(content.encode('utf-8'))
        
        else:
            self.send_error(404, "Not Found")

def feedLoop():
    global feeders, times

    def send_request(feeder, portionCnt):
        results = []
        for _ in range(portionCnt):
            try:
                response = requests.get(feeder.strip('/') + '/feedPortion')
                results.append(f"[{response.status_code},{response.text}]")
            except:
                results.append("[ERROR]")
        return feeder, results

    t = threading.current_thread()
    while getattr(t, "do_run", True):
        now = datetime.now().time().strftime('%H:%M')
        for timestr in times:
            portionTime, portionCnt = timestr.split('-')
            portionCnt = int(portionCnt)
            if now == portionTime:
                with ThreadPoolExecutor(max_workers=len(feeders)) as executor:
                    futures = [executor.submit(send_request, feeder, portionCnt) for feeder in feeders]
                    for future in futures:
                        feeder, results = future.result()
                        print(f"Feeding [{feeder}] {portionCnt} portions... ", end='')
                        print(', '.join(results)  + '.')
                secondsToNextM = 60 - int(datetime.now().time().strftime('%S'))
                print(f"Sleeping {secondsToNextM}+10 seconds (till next minute)...")
                time.sleep(secondsToNextM + 10)
        time.sleep(5)

def runHTTPServer(server):
    server.serve_forever()

def shutdownSignalHandler(args, signum=99999, frame=None):
    httpserver, feedThread, observer = args
    print(f"[*] received signal {signum}. shutting down.")
    print("[*] shutting down RequestHandler")
    httpserver.shutdown()
    print("[*] shutting down feedLoop")
    feedThread.do_run = False
    print("[*] shutting down Observer")
    observer.stop()
    return True

if __name__ == '__main__':
    print("[*] FeedDirector starting up")

    print(f"[*] Current system time: {datetime.now().strftime('%H:%M (%I:%M %p) on %B %d, %Y')}")

    load_data()

    os.environ['FOR_DISABLE_CONSOLE_CTRL_HANDLER'] = '1'
    
    print("[*] Creating RequestHandler instance")
    server_address = (
        os.environ.get('HTTP_ADDR', ''),
        int(os.environ.get('HTTP_PORT', '8000'))
    )
    print("[*] FeedDirector @ [ %s:%d ]" % server_address)
    httpd = ThreadingHTTPServer(server_address, RequestHandler)
    
    # Create threads
    print("[*] creating runHTTPServer thread")
    httpdThread = threading.Thread(target=runHTTPServer, args=(httpd,))
    print("[*] creating feedLoop thread")
    feedThread = threading.Thread(target=feedLoop)
    print("[*] creating Observer instance [file change monitor]")
    observer = Observer()
    observer.schedule(fileEventHandler, '.', recursive=False)

    # Register the signal handlers
    print("[*] Registering SIGTERM and SIGINT signal handlers")
    signal.signal(signal.SIGTERM, partial(shutdownSignalHandler, (httpd, feedThread, observer)))
    signal.signal(signal.SIGINT, partial(shutdownSignalHandler, (httpd, feedThread, observer)))

    # Windows specific signal handler fix
    if sys.platform == "win32":
        print("[*] Registering Windows specific signal handler")
        import win32api
        win32api.SetConsoleCtrlHandler(partial(shutdownSignalHandler, (httpd, feedThread, observer)), True)
    
    # Start threads
    print("[*] starting runHTTPServer thread")
    httpdThread.start()
    print("[*] starting feedLoop thread")
    feedThread.start()
    print("[*] starting Observer instance [file change monitor]")
    observer.start()

    # Wait for the server thread to finish
    httpdThread.join()
    feedThread.join()
    observer.join()

    print("[*] FeedDirector exiting...")

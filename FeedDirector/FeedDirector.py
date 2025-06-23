import logging

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

# Log file directory from ENV
log_dir = os.environ.get('LOG_DIR', os.getcwd())

# Ensure the log directory exists
if not os.path.exists(log_dir):
    os.makedirs(log_dir)

# Get the current date and time when the program starts
start_time = datetime.now().strftime('%Y-%m-%d_%H-%M-%S')

# Configure logging with a dynamic filename
log_filename = f'{os.environ.get('LOG_NAME', 'feed_director')}_{start_time}.log'

# Construct the full log file path
log_path = os.path.join(log_dir, log_filename)

# Create a logger
logger = logging.getLogger('NotificationRedirector')
logger.setLevel(logging.DEBUG)  # Set the level to DEBUG to capture all messages

# Create a formatter
formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s', datefmt='%Y-%m-%d %H:%M:%S')

# Create a file handler
file_handler = logging.FileHandler(log_path)
file_handler.setLevel(logging.DEBUG)  # Log all levels to the file
file_handler.setFormatter(formatter)

# Create a stream handler for console output
console_handler = logging.StreamHandler()
console_handler.setLevel(logging.DEBUG)  # Log all levels to the console
console_handler.setFormatter(formatter)

# Add handlers to the logger
logger.addHandler(file_handler)
logger.addHandler(console_handler)

# File to store mappings persistently
MAPPINGS_FILE = 'feederdata.json'

# List to store all feeders
feeders = []

# List to store all times
times = []

# List to store all the feeding events (per-run, not persistent)
event_log = []

class MyHandler(FileSystemEventHandler):
    def __init__(self, filename):
        self.filename = filename
        self.is_self_writing = False

    def on_modified(self, event):
        if not event.is_directory and event.src_path.endswith(self.filename):
            if not self.is_self_writing:
                logger.info(f"[*] Feeders and times file [{MAPPINGS_FILE}] modified")
                load_data()

fileEventHandler = MyHandler(MAPPINGS_FILE)

def load_data():
    global feeders, times
    if os.path.exists(MAPPINGS_FILE):
        with open(MAPPINGS_FILE, 'r') as f:
            data = json.load(f)
            feeders = data.get('feeders', {})
            times = data.get('times', [])
            logger.info("[*] Loaded feeders and times from file.")
    else:
        logger.info("[*] No save file found. Starting fresh.")

def save_data():
    global feeders, times, fileEventHandler
    fileEventHandler.is_self_writing = True
    with open(MAPPINGS_FILE, 'w') as f:
        json.dump({'feeders': feeders, 'times': times}, f)
        logger.info("[*] Feeders and times saved to file.")
    fileEventHandler.is_self_writing = False

class RequestHandler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        return

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

            time = '-'.join(time.split('-')[0:2]) # remove days from time (safely, incase no days are included)

            already_exist = any([True for x in times if x.startswith(time)])
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

            time = '-'.join(time.split('-')[0:2]) # remove days from time (safely, incase no days are included)
            
            already_exist = any([True for x in times if x.startswith(time)])
            if already_exist:
                idx = [i for i, x in enumerate(times) if x.startswith(time)][0]
                times.pop(idx)
                save_data()

            self.send_response(200)
            self.send_header('Content-type', 'text/plain')
            self.end_headers()

            self.wfile.write(bytes(json.dumps(already_exist), "utf-8"))
        
        elif self.path == '/modifyDaysForTime':
            content_length = int(self.headers['Content-Length'])
            post_data = self.rfile.read(content_length).decode('utf-8')
            params = urllib.parse.parse_qs(post_data)
            
            time = params.get('time', [''])[0]
            newdays = params.get('newdays', [''])[0]

            time = '-'.join(time.split('-')[0:2]) # remove days from time (safely, incase no days are included)
            
            already_exist = any([True for x in times if x.startswith(time)])
            if already_exist:
                idx = [i for i, x in enumerate(times) if x.startswith(time)][0]
                times[idx] = '-'.join([time, newdays])
                save_data()

            self.send_response(200)
            self.send_header('Content-type', 'text/plain')
            self.end_headers()

            self.wfile.write(bytes(json.dumps(already_exist), "utf-8"))
        
        elif self.path == '/getEventLog':
            self.send_response(200)
            self.send_header('Content-type', 'application/json')
            self.end_headers()

            self.wfile.write(bytes(json.dumps(event_log), "utf-8"))
        
        else:
            self.send_error(404, "Not Found")

    def do_GET(self):
        if self.path == "/":
            self.path = "/index.html"
        
        # Remove leading slash
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
    
    dayLookup = {
        'Sun': 'Su',
        'Mon': 'M',
        'Tue': 'Tu',
        'Wed': 'W',
        'Th': 'Th',
        'Fri': 'F',
        'Sat': 'Sa'
    }

    t = threading.current_thread()
    while getattr(t, "do_run", True):
        now = datetime.now().time().strftime('%H:%M')
        day = dayLookup[datetime.now().date().strftime('%a')]
        for timestr in times:
            portionTime, portionCnt, portionDays = timestr.split('-')
            portionCnt = int(portionCnt)
            if now == portionTime and day in portionDays:
                with ThreadPoolExecutor(max_workers=len(feeders)) as executor:
                    futures = [executor.submit(send_request, feeder, portionCnt) for feeder in feeders]
                    for future in futures:
                        feeder, results = future.result()
                        event_info = f"Feeding [{feeder}] {portionCnt} portions... {', '.join(results)  + '.'}"
                        logger.info(event_info)
                        event_log.append(datetime.now().strftime('%Y-%m-%d %H:%M:%S') + ' - ' + event_info)
                secondsToNextM = 60 - int(datetime.now().time().strftime('%S'))
                logger.info(f"Sleeping {secondsToNextM}+10 seconds (till next minute)...")
                time.sleep(secondsToNextM + 10)
        time.sleep(5)

def runHTTPServer(server):
    server.serve_forever()

def shutdownSignalHandler(args, signum=99999, frame=None):
    httpserver, feedThread, observer = args
    logger.info(f"[*] received signal {signum}. shutting down.")
    logger.info("[*] shutting down RequestHandler")
    httpserver.shutdown()
    logger.info("[*] shutting down feedLoop")
    feedThread.do_run = False
    logger.info("[*] shutting down Observer")
    observer.stop()
    return True

if __name__ == '__main__':
    logger.info("[*] FeedDirector starting up")

    logger.info(f"[*] Current system time: {datetime.now().strftime('%H:%M (%I:%M %p) on %B %d, %Y')}")

    load_data()

    os.environ['FOR_DISABLE_CONSOLE_CTRL_HANDLER'] = '1'
    
    logger.info("[*] Creating RequestHandler instance")
    server_address = (
        os.environ.get('HTTP_ADDR', ''),
        int(os.environ.get('HTTP_PORT', '8000'))
    )
    logger.info("[*] FeedDirector @ [ %s:%d ]" % server_address)
    httpd = ThreadingHTTPServer(server_address, RequestHandler)
    
    # Create threads
    logger.info("[*] creating runHTTPServer thread")
    httpdThread = threading.Thread(target=runHTTPServer, args=(httpd,))
    logger.info("[*] creating feedLoop thread")
    feedThread = threading.Thread(target=feedLoop)
    logger.info("[*] creating Observer instance [file change monitor]")
    observer = Observer()
    observer.schedule(fileEventHandler, '.', recursive=False)

    # Register the signal handlers
    logger.info("[*] Registering SIGTERM and SIGINT signal handlers")
    signal.signal(signal.SIGTERM, partial(shutdownSignalHandler, (httpd, feedThread, observer)))
    signal.signal(signal.SIGINT, partial(shutdownSignalHandler, (httpd, feedThread, observer)))

    # Windows specific signal handler fix
    if sys.platform == "win32":
        logger.info("[*] Registering Windows specific signal handler")
        import win32api
        win32api.SetConsoleCtrlHandler(partial(shutdownSignalHandler, (httpd, feedThread, observer)), True)
    
    # Start threads
    logger.info("[*] starting runHTTPServer thread")
    httpdThread.start()
    logger.info("[*] starting feedLoop thread")
    feedThread.start()
    logger.info("[*] starting Observer instance [file change monitor]")
    observer.start()

    # Wait for the server thread to finish
    httpdThread.join()
    feedThread.join()
    observer.join()

    logger.info("[*] FeedDirector exiting...")

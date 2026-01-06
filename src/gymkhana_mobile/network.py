import socket
import threading
import json
import config

class UdpListener:
    def __init__(self, on_message_received, on_error=None):
        self.running = True
        self.sock = None
        self.on_message_received = on_message_received
        self.on_error = on_error

    def start(self):
        """受信スレッドを開始"""
        threading.Thread(target=self._listen_loop, daemon=True).start()

    def stop(self):
        """受信を停止"""
        self.running = False
        if self.sock:
            try:
                self.sock.close()
            except:
                pass

    def _listen_loop(self):
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        # ソケット再利用設定 (再起動時のエラー防止)
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)

        try:
            self.sock.bind(('0.0.0.0', config.UDP_PORT))
            self.sock.settimeout(1.0)
            print(f"UDP Listening on port {config.UDP_PORT}...")

            while self.running:
                try:
                    data, addr = self.sock.recvfrom(config.BUFFER_SIZE)
                    message = data.decode('utf-8').strip()
                    
                    if self.on_message_received:
                        self.on_message_received(message)
                        
                except socket.timeout:
                    continue
                except OSError as e:
                     if e.errno == 10038: break # ソケット閉鎖
                     if self.on_error: self.on_error(e)
                except Exception as e:
                    if self.on_error: self.on_error(e)
        finally:
            try: self.sock.close()
            except: pass

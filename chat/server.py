#!/usr/bin/env python3
# -*- coding:utf8 -*-
# PEP 8 check with Pylint
"""server

Create and start NLU TCPServer with socketserver.
The socketserver module simplifies the task of writing network servers.
通过socketserver创建并启动语义理解服务器。
"""

import os
import json
import socketserver
# import chardet
from qa import Robot
from mytools import get_current_time

robot = Robot()


class MyTCPHandler(socketserver.BaseRequestHandler):
    """The request handler class for nlu server.
    语义理解服务器。

    It is instantiated once per connection to the server, and must override
    the 'handle' method to implement communication to the client.
    """
    def handle(self):
        while True:
			# self.request is the TCP socket connected to the client
            self.data = self.request.recv(2048)
            if not self.data:
                break
            print("\n{} wrote:".format(self.client_address[0]))
            # Detect encoding of received data
            # encoding = chardet.detect(self.data)["encoding"]
            # print("Encoding: " + encoding)
            # self.data = self.data.decode(encoding)
            self.data = self.data.decode("UTF-8")
            print("Data:\n")
            print(self.data)
            # step 1.Bytes to json obj and extract question
            json_data = json.loads(self.data)
            # step 2.Get answer
            if "ask_content" in json_data.keys():
                result = robot.search(question=json_data["ask_content"], userid=json_data["userid"])
            elif "config_content" in json_data.keys():
                result = robot.configure(info=json_data["config_content"], userid=json_data["userid"])
            # step 3.Send
            # self.request.sendall(json.dumps(result).encode(encoding))
            self.request.sendall(json.dumps(result).encode("UTF-8"))


def start(host="localhost", port=7000):
    """Start NLU server.

    Create the server, binding to host and port. Then activate the server.
    This will keep running until you interrupt the program with Ctrl-C.

    Args:
        host: Server IP address. 服务器IP地址设置。
            Defaults to "localhost".
        port: server port. 服务器端口设置。
            Defaults to 7000.
    """
    # 多线程处理多用户请求
    sock = socketserver.ThreadingTCPServer((host, port), MyTCPHandler)
    sock.serve_forever()

if __name__ == "__main__":
    start()
	
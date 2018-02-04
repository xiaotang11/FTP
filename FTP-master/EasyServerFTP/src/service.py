
import socket
import subprocess
import re
import os
import json
import socketserver

from config import settings

ACTION_CODE = {
    '1000': 'cmd',
    '2000': 'post',
    '3000': 'get',
}

REQUEST_CODE = {#响应码，将文档发给用户，用户就知道哪个码代表什么意思
    '1001': 'cmd info',
    '1002': 'cmd ack',
    '2001': 'post info',
    '2002': 'ACK（可以开始上传）',
    '2003': '文件已经存在',
    '2004': '续传',
    '2005': '不续传',
    '3001': 'get info',
    '3002': 'get ack',
    '4001': "未授权",
    '4002': "授权成功",
    '4003': "授权失败"
}

#只能处理单用户
class Server(object):
    request_queue_size = 5

    def __init__(self):
        self.socket = socket.socket()
        self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            self.server_bind(settings.BIND_HOST, settings.BIND_PORT)

            self.server_activate()
        except Exception as e:
            print(e)
            self.server_close()

    def server_bind(self, ip, port):
        self.socket.bind((ip, port,))

    def server_activate(self):
        self.socket.listen(self.request_queue_size)
        self.run()

    def server_close(self):
        self.socket.close()

    def run(self):
        # get request
        while True:
            conn, address = self.socket.accept()
            conn.sendall(bytes("欢迎登陆", 'utf-8'))
            obj = Action(conn)
            while True:
                client_bytes = conn.recv(1024)
                if not client_bytes:
                    break

                client_str = str(client_bytes, encoding='utf-8')
                if obj.has_login:

                    o = client_str.split('|', 1)
                    if len(o) > 0:
                        func = getattr(obj, o[0])
                        func(client_str)
                    else:
                        conn.sendall(bytes('输入格式错误', 'utf-8'))
                else:
                    obj.login(client_str)

            conn.close()


class MultiServerHandler(socketserver.BaseRequestHandler):
    def handle(self):
        conn = self.request
        conn.sendall(bytes("欢迎登陆", 'utf-8'))
        obj = Action(conn)
        #  self.conn = conn
        # self.has_login = False
        # self.username = None
        # self.home = None
        # self.current_dir = None
        while True:
            client_bytes = conn.recv(1024)
            if not client_bytes:
                break
            # cmd|ipconfig
            client_str = str(client_bytes, encoding='utf-8')
            if obj.has_login:
                o = client_str.split('|', 1)
                # o[0]: cmd
                if len(o) > 0:
                    func = getattr(obj, o[0])
                    func(client_str) # cmd|ipconfig
                else:
                    conn.sendall(bytes('输入格式错误', 'utf-8'))
            else:
                obj.login(client_str)

        conn.close()

#处理多用户登录
class MultiServer(object):
    def __init__(self):
        server = socketserver.ThreadingTCPServer((settings.BIND_HOST, settings.BIND_PORT), MultiServerHandler)
        # socketserver 绑定地址和端口，同时每一个请求执行MultiServerHandler 类的handle方法
        server.serve_forever()


class Action(object):
    '''
    每个用户就是一个对象，
    用户加密认证（md5值）
允许同时多用户登录（通过socketserver来实现）

每个用户有自己的家目录 ，且只能访问自己的家目录    /home/mary/hello
对用户进行磁盘配额，每个用户的可用空间不同
允许用户在ftp server上随意切换目录     先发大小，再发内容，中间再发一收一发以防止粘包
允许用户查看当前目录下文件

允许上传和下载文件，保证文件一致性     一点一点读，一点一点发
文件传输过程中显示进度条                通过百分比除，
支持文件的断点续传                       文件也有md5值，现将文件的md5值发给服务端，服务端创建一个文件名就叫这个md5值，如果上传完了，就将md5值换成文件名。
                                        下次一再发时，服务端先检测有没有这个md5值，有就，计算该文件大小发给客户端，客户端就将指针跳转到该字节，继续发，服务端以追加模式继续将数据加进去。

    '''
    def __init__(self, conn):
        self.conn = conn
        self.has_login = False
        self.username = None
        self.home = None
        self.current_dir = None

    def login(self, origin):
        self.conn.sendall(bytes("4001", 'utf-8'))
        while True:
            login_str = str(self.conn.recv(1024), encoding='utf-8')
            login_dict = json.loads(login_str)
            if login_dict['username'] == 'marymarytang' and login_dict['pwd'] == '123':
                self.conn.sendall(bytes("4002", 'utf-8'))
                self.has_login = True
                self.username = 'marymarytang'
                self.initialize()
                break
            else:
                self.conn.sendall(bytes("4003", 'utf-8'))

#初始化用户的家目录
    def initialize(self):
        self.home = os.path.join(settings.USER_HOME, self.username)
        self.current_dir = os.path.join(settings.USER_HOME, self.username)

    def cmd(self, origin):

        func, command = origin.split('|', 1)
        command_list = re.split('\s*', command, 1)

        if command_list[0] == 'ls':
            if len(command_list) == 1:
                if self.current_dir:
                    command_list.append(self.current_dir)
                else:
                    command_list.append(self.home)
            else:
                if self.current_dir:
                    p = os.path.join(self.current_dir, command_list[1])
                else:
                    p = os.path.join(self.home, command_list[1])
                command_list[1] = p

        if command_list[0] == 'cd':
            if len(command_list) == 1:
                command_list.append(self.home)

            else:
                if self.current_dir:
                    p = os.path.join(self.current_dir, command_list[1])
                else:
                    p = os.path.join(self.home, command_list[1])
                self.current_dir = p
                command_list[1] = p
        command = ' '.join(command_list)
        try:# 通过subprocess.check_output（）方法将拿到的命令执行一下
            result_bytes = subprocess.check_output(command, shell=True)
            # result_bytes # gbk字节
            result_bytes = bytes(str(result_bytes, encoding='gbk'), encoding='utf-8')
        except Exception as e:
            result_bytes = bytes('error cmd', encoding='utf-8')



        info_str = "info|%d" % len(result_bytes)
        self.conn.sendall(bytes(info_str, 'utf-8'))
        ack = self.conn.recv(1024)
        self.conn.sendall(result_bytes)

    def post(self, origin):
        func, file_byte_size, file_name, file_md5, target_path = origin.split('|', 4)
        target_abs_md5_path = os.path.join(self.home, target_path)
        has_received = 0
        file_byte_size = int(file_byte_size)

        if os.path.exists(target_abs_md5_path):
            self.conn.sendall(bytes('2003', 'utf-8'))
            is_continue = str(self.conn.recv(1024), 'utf-8')
            if is_continue == "2004":
                has_file_size = os.stat(target_abs_md5_path).st_size
                self.conn.sendall(bytes(str(has_file_size), 'utf-8'))
                has_received += has_file_size
                f = open(target_abs_md5_path, 'ab')

            else:
                f = open(target_abs_md5_path, 'wb')
        else:
            self.conn.sendall(bytes('2002', 'utf-8'))
            f = open(target_abs_md5_path, 'wb')

        while file_byte_size > has_received:
            data = self.conn.recv(1024)
            f.write(data)
            has_received += len(data)
        f.close()

    def get(self, origin):
        pass

    def exit(self, origin):
        pass




#!/usr/bin/python3
# -*- coding: utf-8 -*-
"""Proxy server for Ivelum test:

https://github.com/ivelum/job/blob/master/code_challenges/python.md

Bugaevsky T., 2017, zk.boogie@gmail.com

"""

import http.server
import urllib.request
import urllib.parse
import urllib.error
import html
import io
import shutil
import re
import html.parser
import http.client
import socketserver

__version__ = "0.1"


class UserHTMLParser(html.parser.HTMLParser):

    """HTML parser for ContentHandler class

    Replaces URLs to stay inside the proxy and performs user defined regular expression replacement on text contents.

    """

    pattern = r''
    replacement = ''
    cur_tag = ''
    data = []
    server_base_url = ''
    target_base_url = ''

    def __init__(self, pattern=r'', replacement='', server_base_url='', target_base_url=''):
        self.server_base_url = server_base_url
        self.target_base_url = target_base_url
        self.pattern = pattern
        self.replacement = replacement
        self.data = []
        html.parser.HTMLParser.__init__(self)

    def handle_starttag(self, tag, attributes):
        # Saving the last tag to know which tag content is processed in handle_data.
        tag = tag.lower()
        self.cur_tag = tag

        # Processing URL replacements in tag attributes.
        self.data.append('<' + tag)
        for name, value in attributes:
            name = name.lower()
            if value is not None:
                # Processing attributes that might contain URL.
                if (tag == 'a' and name == 'href') \
                        or (tag == 'img' and name == 'src') \
                        or (tag == 'link' and name == 'href') \
                        or (tag == 'iframe' and name == 'src') \
                        or (tag == 'script' and name == 'src'):
                    # Checking the domain of the URL.
                    reg_exp = re.compile(r'^([a-z]+://[^/]*)[/?](.*)?$', re.I)
                    url_base_url = reg_exp.sub('\g<1>', value)
                    if url_base_url == value:
                        if value.startswith('//'):
                            # URLs without protocol should have one when getting content.
                            value = 'http:' + value
                            url_base_url = 'http:' + url_base_url
                        else:
                            # URLs without domain are for resources on the target domain.
                            value = self.target_base_url + value
                            url_base_url = self.target_base_url

                    if url_base_url == self.target_base_url:
                        # URLs on the target domain are processed as URLs on the server domain.
                        value = reg_exp.sub(self.server_base_url + '/\g<2>', value)
                    else:
                        # URLs on other domains are passed entire the URL in the url query parameter.
                        value = self.server_base_url + '/?url=' + urllib.parse.quote_plus(value)

                self.data.append(' ' + name + '="' + html.escape(value) + '"')
            else:
                self.data.append(' ' + name)
        self.data.append('>')

    def handle_endtag(self, tag):
        single_tags = ['img', 'meta', 'link', 'input', 'br', 'hr']
        if tag not in single_tags:
            self.data.append('</' + tag + '>')

    def handle_data(self, data):
        skip_tags = ['script', 'style']
        if self.cur_tag not in skip_tags:
            reg_exp = re.compile(self.pattern, re.I)
            data = reg_exp.sub(self.replacement, data)
            self.data.append(html.escape(data))
        else:
            self.data.append(data)

    def get_data(self):
        return ''.join(self.data)


class ContentHandler(http.server.BaseHTTPRequestHandler):

    """Handles request from the server.

    Performs replacements in text and keeps links working.

    """

    target_base_url = ''
    server_base_url = ''
    server_address = ('', 0)
    pattern = r''
    replacement = ''

    def __init__(self, target_base_url, server_address, pattern, replacement, request, client_address, server):
        self.target_base_url = target_base_url
        self.server_base_url = 'http://%s:%d' % server_address
        self.server_address = server_address
        self.pattern = pattern
        self.replacement = replacement
        try:
            http.server.BaseHTTPRequestHandler.__init__(self, request, client_address, server)
        except ConnectionError as e:
            pass  # Possible connection reset error (client connection closed)

    def do_GET(self):
        """Serve a GET request."""
        source = self.open_url(self.target_base_url + self.path)
        if source:
            try:
                shutil.copyfileobj(source, self.wfile)
            except IOError as e:
                pass  # Possible broken pipe (client connection closed)
            finally:
                source.close()

    def open_url(self, url):

        """Downloads the file content by the URL.

        The data is also processed according to the class designation.

        """

        # Restoring URLs from other domains
        reg_exp = re.compile(r'^.*url=(.*?)$', re.I)
        if reg_exp.match(url):
            url = urllib.parse.unquote_plus(reg_exp.sub('\g<1>', url))

        # Reading URL content and encoding
        content_received = False
        url_content = None
        full_content_type = 'text/html; charset=utf-8'
        content_type = 'text/html'
        encoding = 'utf-8'
        url_timeout = 3.0
        try:
            url_content = urllib.request.urlopen(url, None, url_timeout)
            content_received = True
        except urllib.error.URLError as e:
            pass  # Unable to get response for the URL, details: print(e.reason)
        if content_received:
            full_content_type = url_content.getheader('Content-type', full_content_type)
            reg_exp = re.compile(r'^(.*?);\s*charset=(.*?)$', re.I)
            content_type = reg_exp.sub('\g<1>', full_content_type)
            if content_type != full_content_type:
                encoding = reg_exp.sub('\g<2>', full_content_type)

        data = b''
        if url_content is not None:
            # Processing content
            data = url_content.read()
            if content_type == 'text/html':
                parser = UserHTMLParser(self.pattern, self.replacement, self.server_base_url, self.target_base_url)
                parser.feed(data.decode(encoding))
                data = parser.get_data().encode(encoding)

        # Generating output
        f = io.BytesIO()
        f.write(data)
        f.seek(0)
        if content_received:
            self.send_response(200)
        else:
            self.send_response(404)
        self.send_header("Content-type", full_content_type)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        return f

    def address_string(self):
        """Reverse DNS bugfix
        https://stackoverflow.com/questions/2617615/slow-python-http-server-on-localhost
        """
        host, port = self.server_address[:2]
        # return socket.getfqdn(host)
        return host


class ThreadedHTTPServer(socketserver.ThreadingMixIn, http.server.HTTPServer):

    """ This class allows to handle requests in separated threads.
    No further content needed, don't touch this.
    https://stackoverflow.com/questions/8403857/python-basehttpserver-not-serving-requests-properly
    """


def run(ip='127.0.0.1', port=80, target_base_url='https://ya.ru', pattern=r'', replacement=''):
    server_address = (ip, port)

    # Adding arguments to the handler
    def handler(*args):
        ContentHandler(target_base_url, server_address, pattern, replacement, *args)

    httpd = None
    try:
        httpd = ThreadedHTTPServer(server_address, handler)
        httpd.serve_forever()
        print('Ctrl + C to stop the proxy server.')
    except KeyboardInterrupt:
        print('Shutting down the proxy server.')
        httpd.socket.close()


run('127.0.0.1',
    8232,
    'https://habrahabr.ru',
    r'(?<![a-zа-я])([a-zа-я]{6})(?![a-zа-я])', # Case insensitive
    '\g<1>™')

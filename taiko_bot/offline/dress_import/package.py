"""Bounded wxapkg reader and a deliberately small data-expression parser."""
import hashlib
import json
import re
import struct
import zipfile

from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

APPID = "wxeafab0667490cd23"


def read_service(archive, appid=APPID):
    with zipfile.ZipFile(archive) as bundle:
        entries = [i for i in bundle.infolist() if i.filename.rsplit('/', 1)[-1] == '__APP__.wxapkg']
        if len(entries) != 1 or entries[0].file_size > 32 * 1024 * 1024:
            raise ValueError("Expected one bounded main package")
        data = bundle.read(entries[0])
    if data.startswith(b'V1MMWX'):
        key = hashlib.pbkdf2_hmac('sha1', appid.encode(), b'saltiest', 1000, 32)
        decoder = Cipher(algorithms.AES(key), modes.CBC(b'the iv: 16 bytes')).decryptor()
        data = decoder.update(data[6:1030])[:1023] + bytes(b ^ ord(appid[-2]) for b in data[1030:])
    if len(data) < 18 or data[0] != 0xbe or data[13] != 0xed:
        raise ValueError("Invalid package header or AppID")
    count = struct.unpack_from('>I', data, 14)[0]
    if count > 10000:
        raise ValueError("Unbounded package index")
    offset = 18
    for _ in range(count):
        length = struct.unpack_from('>I', data, offset)[0]
        offset += 4
        if length > 4096:
            raise ValueError("Invalid package filename")
        name = data[offset:offset + length].decode()
        offset += length
        start, size = struct.unpack_from('>II', data, offset)
        offset += 8
        if start + size > len(data):
            raise ValueError("Invalid package offset")
        if name == '/app-service.js':
            return data[start:start + size].decode()
    raise ValueError("Main service missing")


class DataParser:
    """Accept literals, earlier variables and the two known image-list helpers only."""
    token = re.compile(r'\s*("(?:[^"\\]|\\.)*"|-?\d+|[A-Za-z_$][\w$]*|[\[\]{}(),:=!])')

    def __init__(self, text, variables, helpers):
        self.text, self.offset = text, 0
        self.variables, self.helpers = variables, helpers

    def peek(self):
        match = self.token.match(self.text, self.offset)
        if not match:
            raise ValueError(f"Unsupported data expression at {self.offset}")
        return match.group(1)

    def take(self, expected=None):
        value = self.peek()
        if expected is not None and value != expected:
            raise ValueError(f"Expected {expected}, got {value}")
        self.offset = self.token.match(self.text, self.offset).end()
        return value

    def value(self):
        token = self.take()
        if token == '[':
            result = []
            while self.peek() != ']':
                result.append(self.value())
                if self.peek() != ',':
                    break
                self.take(',')
            self.take(']')
            return result
        if token == '{':
            result = {}
            while self.peek() != '}':
                key = self.take()
                if key.startswith('"'):
                    key = json.loads(key)
                self.take(':')
                if key in result:
                    raise ValueError(f"Duplicate property {key}")
                result[key] = self.value()
                if self.peek() != ',':
                    break
                self.take(',')
            self.take('}')
            return result
        if token.startswith('"'):
            return json.loads(token)
        if token == '!':
            return not self.value()
        if re.fullmatch(r'-?\d+', token):
            return int(token)
        if token in self.helpers:
            self.take('(')
            args = [self.value()]
            while self.peek() == ',':
                self.take(',')
                args.append(self.value())
            self.take(')')
            return self.helpers[token](*args)
        if token in self.variables:
            return self.variables[token]
        raise ValueError(f"Unknown data symbol {token}")


def parse_catalog(service):
    marker = '!*** ./src/pages/components/clothes/data.ts ***!'
    start = service.index(marker)
    text = service[start:service.index('},"./', start)]
    exports = dict(re.findall(r'(\w+):function\(\)\{return (\w+)\}', text))
    palette_match = re.search(r'(\w+)=(\["#[^\]]+\])', text)
    palette = json.loads(palette_match[2])
    if len(palette) > 256:
        raise ValueError("Unbounded palette")
    helpers = re.findall(r'(\w+)=function\([^)]*\)\{return (\w+)\.map', text)
    color_helper = next(name for name, source in helpers if source == palette_match[1])
    variant_helper = next(name for name, source in helpers if source != palette_match[1])

    def colors(base, prefix):
        return [{'color': color, 'url': f'{base}/{prefix}_{i:03}.png'} for i, color in enumerate(palette)]

    def variants(entries, base, prefix):
        return [dict(entry, url=f'{base}/{prefix}_{i:03}.png') for i, entry in enumerate(entries)]

    first = re.search(r'\b' + re.escape(exports['cosIconList']) + r'=\[', text)
    parser = DataParser(text[first.start():], {}, {color_helper: colors, variant_helper: variants})
    while True:
        name = parser.take()
        parser.take('=')
        parser.variables[name] = parser.value()
        if parser.offset == len(parser.text.rstrip()):
            break
        if not parser.text[parser.offset:].strip():
            break
        parser.take(',')
    result = {name: parser.variables[symbol] for name, symbol in exports.items()}
    for name in ('cosIconList', 'headIconList', 'bodyIconList', 'paintIconList', 'accessoriesIconList'):
        ids = [entry['id'] for entry in result[name]]
        if len(ids) != len(set(ids)):
            raise ValueError(f"Duplicate IDs in {name}")
    render_start = service.index('!*** ./src/pages/components/clothes/index.tsx ***!')
    render = service[render_start:service.index('},"./', render_start)]
    result['defaultLine'] = re.search(r'https://[^"\s]+/line_290/line_290\.png', render)[0]
    result['schemaVersion'] = 1
    return result

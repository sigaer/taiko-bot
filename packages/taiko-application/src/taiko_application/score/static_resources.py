"""Bounded public-image cache and request-owned, read-only rendering resources.

The process cache never lends an Image: a copy is made under its lock. Only
public file resources enter it. Player canvases and fonts live for one request.
"""
from collections import OrderedDict
from pathlib import Path
from threading import RLock
import time
from PIL import Image, ImageFont
from .cancellation import check_cancelled

MAX_IMAGE_BYTES = 64 * 1024**2


def revision(path):
    path = Path(path).absolute()
    stat = path.stat()
    return (str(path), stat.st_mtime_ns, stat.st_size, stat.st_ino, stat.st_ctime_ns)


class StaticImageCache:
    def __init__(self, max_bytes=MAX_IMAGE_BYTES):
        self.max_bytes = max_bytes
        self._items = OrderedDict()
        self._bytes = 0
        self._lock = RLock()

    @property
    def bytes(self):
        with self._lock:
            return self._bytes

    def clear(self):
        with self._lock:
            for image in self._items.values():
                image.close()
            self._items.clear()
            self._bytes = 0

    def _discard(self, key):
        image = self._items.pop(key)
        self._bytes -= image.width * image.height * len(image.getbands())
        image.close()

    def copy(self, key, load):
        with self._lock:
            cached = self._items.get(key)
            if cached is not None:
                self._items.move_to_end(key)
                return cached.copy()
            # A resource revision replaces every transform of that path.
            for old in list(self._items):
                if old[0][0] == key[0][0] and old[0] != key[0]:
                    self._discard(old)
            image = load()
            cost = image.width * image.height * len(image.getbands())
            if cost > self.max_bytes:
                return image
            while self._items and self._bytes + cost > self.max_bytes:
                self._discard(next(iter(self._items)))
            # This host's filesystem timestamps advance in 4 ms ticks. A very
            # recent in-place rewrite can otherwise alias the previous revision.
            # Do not retain such images across requests until the tick is stable.
            if len(key[0]) >= 5 and time.time_ns() - key[0][4] < 1_000_000_000:
                return image
            self._items[key] = image
            self._bytes += cost
            return image.copy()


STATIC_IMAGES = StaticImageCache()


class RequestResources:
    def __init__(self):
        self._images = {}
        self._fonts = {}
        self._bytes = 0
        self._overflow = []
        self._owned = []

    def own(self, image):
        self._owned.append(image)
        return image

    def release(self, image):
        self._owned = [owned for owned in self._owned if owned is not image]

    def close(self):
        for image in [*self._images.values(), *self._overflow, *self._owned]:
            image.close()
        self._images.clear()
        self._overflow.clear()
        self._fonts.clear()
        self._owned.clear()
        self._bytes = 0

    def image(self, path, *, size=None, fit=None, square=False, height=None):
        check_cancelled()
        key = (revision(path), size, fit, square, height)
        if key in self._images:
            return self._images[key]

        def load():
            source = Image.open(path)
            try:
                image = source.convert('RGBA')
            finally:
                source.close()
            try:
                if square:
                    w, h = image.size
                    side = min(w, h)
                    left, top = (w-side)//2, (h-side)//2
                    cropped = image.crop((left, top, left+side, top+side))
                    image.close()
                    image = cropped
                target = size
                if height is not None and image.height != height:
                    target = (max(1, int(round(image.width * height / max(1, image.height)))), height)
                if target:
                    resized = image.resize(target, Image.LANCZOS)
                    image.close()
                    image = resized
                if fit:
                    image.thumbnail(fit, Image.LANCZOS)
                return image
            except BaseException:
                image.close()
                raise

        image = STATIC_IMAGES.copy(key, load)
        cost = image.width * image.height * 4
        if self._bytes + cost <= MAX_IMAGE_BYTES and len(self._images) < 256:
            self._images[key] = image
            self._bytes += cost
        else:
            # Overflow remains request-owned and is never added to either cache.
            self._overflow.append(image)
        return image

    def font(self, path, size):
        key = (revision(path), size)
        if key not in self._fonts:
            font = ImageFont.truetype(str(path), size)
            if len(self._fonts) < 128:
                self._fonts[key] = font
            return font
        return self._fonts[key]

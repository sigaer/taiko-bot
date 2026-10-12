"""Request-owned Pillow images; never close images supplied by the caller."""

from PIL import Image


class RenderResources:

    def _own(self, image):
        if getattr(self, "_tracking", False) and isinstance(image, Image.Image):
            self._owned.append(image)
        return image

    def render(self, *args, **kwargs):
        self._owned = []
        self._tracking = True
        result = None
        try:
            result = self._render(*args, **kwargs)
            return result
        finally:
            self._tracking = False
            for image in reversed(self._owned):
                if image is not result:
                    image.close()
            self._owned.clear()
            self._ICON_CACHE.clear()

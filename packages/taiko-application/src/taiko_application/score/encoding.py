"""JPEG boundary; source images are borrowed, every temporary is released."""
from io import BytesIO
from PIL import Image


def to_jpeg_bytes(img_buf, quality=85):
    if not isinstance(img_buf, Image.Image):
        data = img_buf.getvalue() if isinstance(img_buf, BytesIO) else img_buf
        with Image.open(BytesIO(data)) as image:
            return to_jpeg_bytes(image, quality)
    image = img_buf
    if image.mode in ('RGBA', 'LA'):
        rgb = Image.new('RGB', image.size, (255, 255, 255))
        try:
            with image.getchannel('A') as alpha:
                rgb.paste(image, mask=alpha)
        except BaseException:
            rgb.close()
            raise
    else:
        rgb = image.convert('RGB')
    try:
        with BytesIO() as output:
            rgb.save(output, format='JPEG', quality=quality, optimize=True)
            return output.getvalue()
    finally:
        rgb.close()

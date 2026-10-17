"""Production WSGI entry point."""

from hdu_upload.server import create_app


app = create_app()

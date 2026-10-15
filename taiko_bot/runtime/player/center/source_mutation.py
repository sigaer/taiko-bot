from __future__ import annotations


from taiko_store import PublicationError, PublicationStore

class AuthorizedPublicationStore(PublicationStore):
    authorize = None
    def publish(self, *args, **kwargs):
        if self.authorize is None:
            raise PublicationError("Source grant not installed")
        self.authorize()
        return super().publish(*args, **kwargs)

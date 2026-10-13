"""Live host authorization immediately before private-result delivery."""


def has_current_send_authority(event, original, resolve):
    """A cached result is never evidence of current read authority."""
    try:
        current = resolve(event)
        fields = ("identity_key", "user_id", "source", "is_virtual")
        return (
            isinstance(current, dict)
            and not current.get("error")
            and bool(current.get("user_id"))
            and all(current.get(key) == original.get(key) for key in fields)
        )
    except Exception:
        return False

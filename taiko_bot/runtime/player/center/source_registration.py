"""Register existing score bytes before entering the normal query lease."""


def ensure_registered(store, verify_authorization):
    # Fast path never replaces an existing head, including deletion tombstones.
    with store.shared():
        if store.view() is not None:
            return
    # Do not upgrade SH in place. Writers and deletion use the same Source EX.
    with store.exclusive():
        verify_authorization()
        if store.view() is not None:
            return
        view = store.reader()
        if not (store.root / (store.identity + 'data.json')).exists() and not view.history_names():
            return  # A genuinely empty account stays empty.
        store.adopt()

"""Request-only reuse of identical ordered score inputs at one public revision."""
from collections import OrderedDict
from hashlib import sha256
import json
from taiko_application.score.cancellation import check_cancelled


class RequestRatingMemo:
    def __init__(self, calculate, revision):
        self.calculate = calculate
        self.revision = revision
        self._items = OrderedDict()
        self._records = 0
        self._aggregations = OrderedDict()

    def aggregate(self, kind, function):
        def calculate(results, *args):
            check_cancelled()
            key = (kind, id(function), id(results), args)
            if key in self._aggregations:
                self._aggregations.move_to_end(key)
                return self._aggregations[key][2]
            value = function(results, *args)
            if len(self._aggregations) >= 64:
                self._aggregations.popitem(last=False)
            # Retain the input reference so a recycled list ID cannot alias it.
            self._aggregations[key] = (results, function, value)
            return value
        calculate._memo_kind = kind
        calculate._memo_function = function
        return calculate

    def __call__(self, records):
        check_cancelled()
        key = (self.revision(), sha256(json.dumps(records, sort_keys=True, separators=(',', ':'), ensure_ascii=False).encode()).digest())
        if key in self._items:
            self._items.move_to_end(key)
            return self._items[key]
        result = self.calculate(records)
        while self._items and (len(self._items) >= 32 or self._records + len(result) > 32000):
            _, previous = self._items.popitem(last=False)
            self._records -= len(previous)
        if len(result) <= 32000:
            self._items[key] = result
            self._records += len(result)
        return result

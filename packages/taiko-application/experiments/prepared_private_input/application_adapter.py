"""Experiment-only adapter. No acquisition or preparation capability is held."""
import re
from taiko_application.commands.score import ScorePorts, execute_score
from taiko_application.commands.models import CommandContext
from .dto import PreparedPrivateInput
from .render_fixture import render, jpeg, query, rejected, hint


def execute_prepared_score(prepared: PreparedPrivateInput, text: str, *, failure=None):
    if type(prepared) is not PreparedPrivateInput:
        raise TypeError('PreparedPrivateInput required')
    def generate_score_image(*, song_no, user_id, prefer_best_in_group):
        if user_id != prepared.authorized_target.user_id or prefer_best_in_group is not True:
            raise ValueError('Prepared render target mismatch')
        # Closure captures immutable prepared data, never a provider or resolver.
        return render(prepared.current, song_no, failure)
    ports = ScorePorts(hint, rejected, jpeg, generate_score_image, lambda *a: None, query)
    return execute_score(CommandContext(user_id=prepared.authorized_target.user_id,
        match=re.fullmatch(r'^/?tinfo\s?(.+)$', text)), ports)

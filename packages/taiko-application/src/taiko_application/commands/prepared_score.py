"""Data-only tinfo execution. Host prepares matching and presentation inputs."""
from dataclasses import dataclass
from io import BytesIO
from PIL import Image
from ..private_input import PreparedPrivateInput, ReadFailure
from ..score.context import ScorePresentationContext
from ..score.drawinfo import ScoreInfoRenderer
from .models import CommandResult


@dataclass(frozen=True, slots=True)
class ScoreSelection:
    song_no: int
    fuzzy_hint: str = ""


def select_score(has_match, music_list=(), *, fuzzy=False, fuzzy_hint=""):
    if not has_match:
        return CommandResult("text", "格式不正确，应为：tinfo 歌名", delivery="direct")
    if len(music_list) == 0:
        return CommandResult("text", "未找到任何歌曲？", delivery="reply")
    if fuzzy or len(music_list) == 1:
        song_no = int(music_list[0][0])
    else:
        return CommandResult("text", "你要找的可能是：\n" + "".join(f"id{row[0]} {row[1]}\n" for row in music_list), delivery="direct")
    if song_no == -1:
        return CommandResult("text", "查询失败，怎么回事呢？", delivery="direct")
    return ScoreSelection(song_no, fuzzy_hint if fuzzy else "")


@dataclass(frozen=True, slots=True)
class PreparedScoreCommand:
    private_input: PreparedPrivateInput
    selection: ScoreSelection | CommandResult
    presentation: ScorePresentationContext | None = None
    presentation_failure: ReadFailure | None = None


def execute_prepared_score(command):
    if type(command.private_input) is not PreparedPrivateInput:
        raise TypeError("Prepared private input required")
    if isinstance(command.selection, CommandResult):
        return command.selection
    failure = command.private_input.current_failure or command.presentation_failure
    if failure is not None:
        return CommandResult("text", "您还未上传数据哦~请先发送“taikoupdate”进行上传" if failure.missing else failure.message,
                             delivery="reply" if failure.missing else "direct")
    try:
        if command.presentation is None or command.presentation.song_no != command.selection.song_no:
            raise ValueError("Score presentation does not match selection")
        raw = ScoreInfoRenderer(command.presentation).render()
    except FileNotFoundError:
        return CommandResult("text", "您还未上传数据哦~请先发送“taikoupdate”进行上传", delivery="reply")
    except Exception as error:
        return CommandResult("text", str(error), delivery="direct")
    # Keep JPEG decoding outside the legacy renderer error boundary.
    with Image.open(BytesIO(raw)) as source:
        if source.mode in ("RGBA", "LA"):
            rgb = Image.new("RGB", source.size, (255, 255, 255))
            rgb.paste(source, mask=source.split()[-1])
        else:
            rgb = source.convert("RGB")
        try:
            output = BytesIO()
            rgb.save(output, format="JPEG", quality=85, optimize=True)
            data = output.getvalue()
        finally:
            rgb.close()
    return CommandResult("image", data, prefix_text=command.selection.fuzzy_hint)

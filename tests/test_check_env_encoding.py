from pathlib import Path

from scripts.check_env import _reconfigure_output_stream


class _FakeStream:
    def __init__(self, reject_encoding=False):
        self.reject_encoding = reject_encoding
        self.calls = []

    def reconfigure(self, **kwargs):
        self.calls.append(kwargs)
        if self.reject_encoding and "encoding" in kwargs:
            raise ValueError("encoding cannot be changed")


class _StreamWithoutReconfigure:
    pass


def test_reconfigure_output_stream_prefers_utf8_with_replacement():
    stream = _FakeStream()

    _reconfigure_output_stream(stream)

    assert stream.calls == [{"encoding": "utf-8", "errors": "replace"}]


def test_reconfigure_output_stream_falls_back_to_errors_only():
    stream = _FakeStream(reject_encoding=True)

    _reconfigure_output_stream(stream)

    assert stream.calls == [
        {"encoding": "utf-8", "errors": "replace"},
        {"errors": "replace"},
    ]


def test_reconfigure_output_stream_ignores_streams_without_reconfigure():
    _reconfigure_output_stream(_StreamWithoutReconfigure())


def test_requirements_file_is_ascii_decodable():
    requirements_path = Path(__file__).resolve().parents[1] / "requirements.txt"

    requirements_path.read_bytes().decode("ascii")

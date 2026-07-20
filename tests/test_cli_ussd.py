from click.testing import CliRunner

from zlt.cli import cli
from zlt.client import UssdResult


class FakeClient:
    def __init__(self, results, config=None):
        self._results = list(results)
        self.config = config
        self.sent = []
        self.replies = []
        self.cancelled = False

    def _next(self):
        return self._results.pop(0)

    def ussd_send(self, code, **kw):
        self.sent.append(code)
        return self._next()

    def ussd_reply(self, text, **kw):
        self.replies.append(text)
        return self._next()

    def ussd_cancel(self):
        self.cancelled = True


def test_send_one_shot_prints_reply():
    client = FakeClient([UssdResult("Balance 100", "complete")])
    r = CliRunner().invoke(cli, ["ussd", "send", "*310#"], obj=client)
    assert r.exit_code == 0
    assert "Balance 100" in r.output
    assert client.sent == ["*310#"]


def test_send_interactive_reply_then_complete(monkeypatch):
    # CliRunner reports a non-TTY stdin; force interactive so the reply loop runs.
    monkeypatch.setattr("zlt.cli._stdin_is_tty", lambda: True)
    client = FakeClient([
        UssdResult("1 Data 2 Voice", "prompt"),
        UssdResult("You chose Data", "complete"),
    ])
    r = CliRunner().invoke(cli, ["ussd", "send", "*312#"], obj=client, input="1\n")
    assert r.exit_code == 0
    assert "1 Data 2 Voice" in r.output
    assert "You chose Data" in r.output
    assert client.replies == ["1"]


def test_send_prompt_empty_input_cancels(monkeypatch):
    monkeypatch.setattr("zlt.cli._stdin_is_tty", lambda: True)
    client = FakeClient([UssdResult("1 Data 2 Voice", "prompt")])
    r = CliRunner().invoke(cli, ["ussd", "send", "*312#"], obj=client, input="\n")
    assert r.exit_code == 0
    assert client.cancelled is True
    assert "cancelled" in r.output.lower()


def test_send_prompt_nontty_prints_menu_and_exits():
    # No TTY (CliRunner default): print the menu, do not hang waiting for input.
    client = FakeClient([UssdResult("1 Data 2 Voice", "prompt")])
    r = CliRunner().invoke(cli, ["ussd", "send", "*312#"], obj=client)
    assert r.exit_code == 0
    assert "1 Data 2 Voice" in r.output
    assert client.replies == []
    assert client.cancelled is False


def test_send_timeout_message():
    client = FakeClient([UssdResult("", "timeout")])
    r = CliRunner().invoke(cli, ["ussd", "send", "*310#"], obj=client)
    assert r.exit_code == 0
    assert "no response" in r.output.lower()


def test_run_resolves_saved_label(monkeypatch, tmp_path):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    from zlt import ussd_store
    ussd_store.save_code("Balance", "*310#")
    client = FakeClient([UssdResult("Balance 100", "complete")])
    r = CliRunner().invoke(cli, ["ussd", "run", "balance"], obj=client)
    assert r.exit_code == 0
    assert client.sent == ["*310#"]


def test_run_unknown_label_errors(monkeypatch, tmp_path):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    r = CliRunner().invoke(cli, ["ussd", "run", "nope"], obj=FakeClient([]))
    assert r.exit_code != 0
    assert "nope" in r.output


def test_save_list_rm(monkeypatch, tmp_path):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    runner = CliRunner()
    assert runner.invoke(cli, ["ussd", "save", "Balance", "*310#"], obj=FakeClient([])).exit_code == 0
    out = runner.invoke(cli, ["ussd", "list"], obj=FakeClient([])).output
    assert "Balance" in out and "*310#" in out
    assert runner.invoke(cli, ["ussd", "rm", "Balance"], obj=FakeClient([])).exit_code == 0
    assert "Balance" not in runner.invoke(cli, ["ussd", "list"], obj=FakeClient([])).output


def test_cancel_command():
    client = FakeClient([])
    r = CliRunner().invoke(cli, ["ussd", "cancel"], obj=client)
    assert r.exit_code == 0
    assert client.cancelled is True

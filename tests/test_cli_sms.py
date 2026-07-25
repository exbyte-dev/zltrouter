from click.testing import CliRunner

from zlt.cli import cli
from zlt.client import SmsError, SmsMessage


class FakeClient:
    def __init__(self, messages=None, *, list_exc=None, send_exc=None, config=None,
                 read_exc=None, delete_exc=None):
        self._messages = list(messages or [])
        self._list_exc = list_exc
        self._send_exc = send_exc
        self._read_exc = read_exc
        self._delete_exc = delete_exc
        self.config = config
        self.sent = []
        self.marked = []
        self.deleted = []

    def sms_list(self, limit=50):
        if self._list_exc:
            raise self._list_exc
        return self._messages[:limit]

    def sms_send(self, number, text):
        if self._send_exc:
            raise self._send_exc
        self.sent.append((number, text))

    def sms_mark_read(self, ids):
        if self._read_exc:
            raise self._read_exc
        self.marked.append(list(ids))
        return len(ids)

    def sms_delete(self, ids):
        if self._delete_exc:
            raise self._delete_exc
        self.deleted.append(list(ids))
        return len(ids)


def msg(**over):
    row = dict(id="656", number="121", text="Hi", date="2026-07-24 15:28",
               unread=True, outgoing=False)
    row.update(over)
    return SmsMessage(**row)


def test_list_prints_messages():
    client = FakeClient([msg(text="Balance is N100")])
    r = CliRunner().invoke(cli, ["sms", "list"], obj=client)
    assert r.exit_code == 0
    assert "Balance is N100" in r.output
    assert "121" in r.output
    assert "2026-07-24 15:28" in r.output


def test_list_marks_unread():
    client = FakeClient([msg(unread=True)])
    r = CliRunner().invoke(cli, ["sms", "list"], obj=client)
    assert r.exit_code == 0
    assert "*" in r.output  # unread marker


def test_list_empty_inbox_says_so():
    r = CliRunner().invoke(cli, ["sms", "list"], obj=FakeClient([]))
    assert r.exit_code == 0
    assert "no messages" in r.output.lower()


def test_list_renders_multiline_bodies():
    """Real messages contain newlines; they must not break the layout."""
    client = FakeClient([msg(text="Ref: 123\nAmt: N1,500.00")])
    r = CliRunner().invoke(cli, ["sms", "list"], obj=client)
    assert r.exit_code == 0
    assert "Ref: 123" in r.output
    assert "Amt: N1,500.00" in r.output


def test_list_reports_errors_cleanly():
    client = FakeClient(list_exc=SmsError("different SMS API"))
    r = CliRunner().invoke(cli, ["sms", "list"], obj=client)
    assert r.exit_code != 0
    assert "different SMS API" in r.output


def test_send_passes_number_and_text():
    client = FakeClient()
    r = CliRunner().invoke(cli, ["sms", "send", "121", "Hi there"], obj=client)
    assert r.exit_code == 0
    assert client.sent == [("121", "Hi there")]


def test_send_reports_errors_cleanly():
    client = FakeClient(send_exc=SmsError("the network rejected the message"))
    r = CliRunner().invoke(cli, ["sms", "send", "121", "Hi"], obj=client)
    assert r.exit_code != 0
    assert "rejected" in r.output


def test_send_confirms_on_success():
    client = FakeClient()
    r = CliRunner().invoke(cli, ["sms", "send", "121", "Hi"], obj=client)
    assert r.exit_code == 0
    assert "121" in r.output


# --- ids, mark read and delete ------------------------------------------------
def test_list_prints_the_id_that_addresses_a_message():
    """'sms read' and 'sms rm' take ids, so 'sms list' has to show them."""
    client = FakeClient([msg(id="659")])
    r = CliRunner().invoke(cli, ["sms", "list"], obj=client)
    assert r.exit_code == 0
    assert "659" in r.output.split("\n")[0]


def test_read_marks_the_given_ids():
    client = FakeClient()
    r = CliRunner().invoke(cli, ["sms", "read", "659", "658"], obj=client)
    assert r.exit_code == 0
    assert client.marked == [["659", "658"]]
    assert "Marked 2 as read" in r.output


def test_read_requires_at_least_one_id():
    client = FakeClient()
    r = CliRunner().invoke(cli, ["sms", "read"], obj=client)
    assert r.exit_code != 0
    assert client.marked == []


def test_read_reports_router_errors():
    client = FakeClient(read_exc=SmsError("router refused"))
    r = CliRunner().invoke(cli, ["sms", "read", "659"], obj=client)
    assert r.exit_code != 0
    assert "router refused" in r.output


def test_rm_deletes_without_prompting():
    """Deliberate: the intended use is clearing an inbox in bulk."""
    client = FakeClient()
    r = CliRunner().invoke(cli, ["sms", "rm", "659", "658"], obj=client)
    assert r.exit_code == 0
    assert client.deleted == [["659", "658"]]
    assert "Deleted 2" in r.output


def test_rm_requires_at_least_one_id():
    client = FakeClient()
    r = CliRunner().invoke(cli, ["sms", "rm"], obj=client)
    assert r.exit_code != 0
    assert client.deleted == []


def test_rm_reports_router_errors():
    client = FakeClient(delete_exc=SmsError("the device rejected the delete"))
    r = CliRunner().invoke(cli, ["sms", "rm", "659"], obj=client)
    assert r.exit_code != 0
    assert "rejected the delete" in r.output

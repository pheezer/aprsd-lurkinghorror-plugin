import os

import pytest
from aprsd import conf  # noqa: F401  (registers core aprsd opts)
from aprsd.packets import core
from oslo_config import cfg

from aprsd_lurkinghorror_plugin import conf as lh_conf  # noqa: F401

CONF = cfg.CONF

FIXTURE = os.path.join(os.path.dirname(__file__), "fixtures", "lurkinghorror.z3")

# The Lurking Horror story file is not redistributable, so it is not committed.
# Engine/plugin tests that need a real game are skipped when it is absent.
requires_story = pytest.mark.skipif(
    not os.path.isfile(FIXTURE),
    reason="story fixture tests/fixtures/lurkinghorror.z3 not present",
)

MY_CALL = "KMINE"
PLAYER = "W1AW"


@pytest.fixture
def configured(tmp_path):
    """Initialize CONF the way the plugin expects, with saving in a tmp dir."""
    CONF.callsign = MY_CALL
    CONF.enable_save = False
    CONF.save_location = str(tmp_path)
    CONF.lurking_horror.story_file = FIXTURE
    CONF.lurking_horror.command_prefix = "#"
    CONF.lurking_horror.max_reply_messages = 4
    CONF.lurking_horror.turn_timeout = 30
    CONF.lurking_horror.session_idle_timeout = 0
    yield CONF


def make_packet(message, from_call=PLAYER, to_call=MY_CALL, msg_number=1):
    """Build a prepared APRS MessagePacket for tests."""
    packet = core.factory(
        {
            "from": from_call,
            "addresse": to_call,
            "to": to_call,
            "format": core.PACKET_TYPE_MESSAGE,
            "message_text": message,
            "msgNo": str(msg_number),
            "raw": "",
        }
    )
    packet.prepare()
    return packet


@pytest.fixture
def reset_session_store():
    """Ensure each test gets a clean GameSessionStore singleton."""
    from aprsd_lurkinghorror_plugin.session import GameSessionStore

    GameSessionStore._instance = None
    yield
    GameSessionStore._instance = None

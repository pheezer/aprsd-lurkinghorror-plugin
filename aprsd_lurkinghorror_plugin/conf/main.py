from oslo_config import cfg

plugin_group = cfg.OptGroup(
    name="lurking_horror",
    title="APRSD Lurking Horror (Z-machine) plugin settings",
)

plugin_opts = [
    cfg.StrOpt(
        "story_file",
        default=None,
        help="Absolute path to a Z-machine story file (.z3/.z5/.dat) to play. "
        "Required; the plugin disables itself if this is unset or missing.",
    ),
    cfg.StrOpt(
        "command_prefix",
        default="#",
        help="Prefix a player must put in front of every game command, e.g. "
        "'#' so '#go north' plays. Keep it short and distinct so it does "
        "not collide with other command plugins.",
    ),
    cfg.IntOpt(
        "max_reply_messages",
        default=4,
        min=1,
        max=10,
        help="Maximum number of APRS messages (each <=67 chars) to send in "
        "reply to a single game turn. Longer output is truncated.",
    ),
    cfg.IntOpt(
        "turn_timeout",
        default=10,
        min=1,
        help="Seconds to allow the interpreter to run a single turn before "
        "giving up and replying with an error.",
    ),
    cfg.IntOpt(
        "session_idle_timeout",
        default=86400,
        min=0,
        help="Expire a player's saved game after this many seconds of "
        "inactivity. 0 disables idle expiry.",
    ),
]

ALL_OPTS = plugin_opts


def register_opts(cfg):
    cfg.register_group(plugin_group)
    cfg.register_opts(ALL_OPTS, group=plugin_group)


def list_opts():
    return {
        plugin_group.name: plugin_opts,
    }

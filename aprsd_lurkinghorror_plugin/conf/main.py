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
        default=8,
        min=1,
        max=20,
        help="Maximum number of APRS messages (each <=67 chars) to send in "
        "reply to a single game turn. A full room description is roughly "
        "5-8 messages; raise this if you still see '(more)' truncation, at "
        "the cost of more RF traffic per turn.",
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
    # --- Beacon options ---------------------------------------------------
    # aprsd's built-in beacon hardcodes its comment to "APRSD GPS Beacon" and
    # offers no way to change it, so the plugin can optionally send its own
    # beacon with a themed comment/symbol to advertise the game on aprs.fi.
    cfg.BoolOpt(
        "beacon_enabled",
        default=False,
        help="If true, the plugin periodically sends its own position beacon "
        "with the comment/symbol below. Requires latitude and longitude. "
        "Use this instead of aprsd's built-in beacon (disable that) so the "
        "map comment can be customized.",
    ),
    cfg.StrOpt(
        "beacon_comment",
        default="Lurking Horror over APRS",
        help="Comment shown on the map for the plugin's beacon.",
    ),
    cfg.StrOpt(
        "beacon_symbol",
        default="(",
        help="APRS symbol code for the beacon. Default '(' is the fog symbol "
        "on the primary table. See http://www.aprs.org/symbols.html",
    ),
    cfg.StrOpt(
        "beacon_symbol_table",
        default="/",
        help="APRS symbol table for the beacon symbol ('/' primary, '\\\\' "
        "alternate).",
    ),
    cfg.FloatOpt(
        "beacon_latitude",
        default=None,
        help="Latitude for the plugin beacon (decimal degrees). Required when "
        "beacon_enabled is true.",
    ),
    cfg.FloatOpt(
        "beacon_longitude",
        default=None,
        help="Longitude for the plugin beacon (decimal degrees). Required when "
        "beacon_enabled is true.",
    ),
    cfg.IntOpt(
        "beacon_interval",
        default=1800,
        min=60,
        help="Seconds between plugin beacon transmissions.",
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

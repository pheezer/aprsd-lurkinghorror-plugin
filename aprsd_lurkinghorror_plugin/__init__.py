from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("aprsd_lurkinghorror_plugin")
except PackageNotFoundError:
    __version__ = "0.0.0"

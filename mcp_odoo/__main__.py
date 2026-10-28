from .config import load_config
from .server import configure, mcp


def main() -> None:
    configure(load_config())
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
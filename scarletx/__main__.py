import os
import uvicorn


def main() -> None:
    host = os.getenv("SCARLETX_HOST", "127.0.0.1")
    port = int(os.getenv("SCARLETX_PORT", "8690"))
    uvicorn.run("scarletx.main:app", host=host, port=port)


if __name__ == "__main__":
    main()

"""Run known startup repairs, then launch the existing AURA server."""
import aura_selfcare as care
import socket


def main():
    with socket.socket() as probe:
        probe.settimeout(.5)
        if probe.connect_ex(('127.0.0.1',8511)) == 0:
            raise SystemExit('AURA port 8511 is already in use. Stop the previous AURA CMD with Ctrl+C first.')
    care.activate()
    try:
        result = care.tick(force=True)
        if result is not None: print(care.report(result))
    except (OSError, ValueError):
        print('Self-care unavailable. Continuing with the existing server.')
    import run_aura
    run_aura.main()


if __name__ == '__main__':
    main()

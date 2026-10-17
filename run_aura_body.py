"""Attach the body lab and virtual controller to the existing managed launcher."""
import socket
import os


def main():
    with socket.socket() as probe:
        probe.settimeout(.5)
        if probe.connect_ex(('127.0.0.1',8511))==0:
            raise SystemExit('Stop the previous AURA server with Ctrl+C before starting Body Lab.')
    import phase3_web as server
    from aura_body_routes import install_body,Engine
    from aura_body import BODY
    from aura_body_memory import WorldMemory
    BODY.recorder=WorldMemory()
    install_body(server.app,server.require,server.TOKEN)
    engine=Engine();engine.start()
    old_start=os.environ.get('AURA_BODY_LAB');os.environ['AURA_BODY_LAB']='1'
    try:
        import run_aura_managed
        run_aura_managed.main()
    finally:
        engine.stop()
        if old_start is None:os.environ.pop('AURA_BODY_LAB',None)
        else:os.environ['AURA_BODY_LAB']=old_start


if __name__=='__main__':main()

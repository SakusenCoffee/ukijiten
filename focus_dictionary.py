#!/usr/bin/python3
"""Focus the running floating dictionary through KDE's window manager."""
import os
from pathlib import Path
import socket
import uuid

import dbus


def main():
    # Reveal a hidden pane without creating another Qt application or prompt.
    with socket.socket(socket.AF_UNIX) as client:
        client.connect(f'/tmp/yomitan-floating-{os.getuid()}')
        client.sendall(b'{"query":""}\n')

    bus = dbus.SessionBus()
    scripting = dbus.Interface(bus.get_object('org.kde.KWin', '/Scripting'), 'org.kde.kwin.Scripting')
    name = 'focus-floating-dictionary-' + uuid.uuid4().hex
    script_id = scripting.loadScript(str(Path(__file__).with_suffix('.js')), name, signature='ss')
    if script_id < 0:
        raise RuntimeError('KWin could not load the dictionary focus script.')
    try:
        script = dbus.Interface(bus.get_object('org.kde.KWin', f'/Scripting/Script{script_id}'), 'org.kde.kwin.Script')
        script.run()
    finally:
        scripting.unloadScript(name)


if __name__ == '__main__':
    main()

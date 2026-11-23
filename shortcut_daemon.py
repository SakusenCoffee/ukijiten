#!/usr/bin/env python3
"""Keep a KDE global shortcut registered for the Ukijiten lookup prompt."""
import subprocess
import sys
from pathlib import Path

import dbus
import dbus.mainloop.glib
from gi.repository import GLib

COMPONENT = 'yomitan-dictionary-lookup'
ACTION = '_launch'
FOCUS_ACTION = '_focus'
# Qt::CTRL | Qt::ALT | Qt::Key_Z
KEY = 0x04000000 | 0x08000000 | ord('Z')
APP = Path(__file__).with_name('ukijiten.py')
FOCUS_APP = Path(__file__).with_name('focus_dictionary.py')
FOCUS_KEY = 0x10000000 | 0x08000000 | 0x02000000 | ord('N')


def main():
    dbus.mainloop.glib.DBusGMainLoop(set_as_default=True)
    bus = dbus.SessionBus()
    obj = bus.get_object('org.kde.kglobalaccel', '/kglobalaccel')
    service = dbus.Interface(obj, 'org.kde.KGlobalAccel')
    action_id = [COMPONENT, ACTION, 'Ukijiten lookup', 'Ukijiten lookup']
    service.doRegister(dbus.Array(action_id, signature='s'))
    # SetPresent makes KWin actually listen for the key, not merely list it.
    service.setShortcut(dbus.Array(action_id, signature='s'), dbus.Array([KEY], signature='i'), dbus.UInt32(2))
    focus_id = [COMPONENT, FOCUS_ACTION, 'Ukijiten lookup', 'Focus dictionary search']
    service.doRegister(dbus.Array(focus_id, signature='s'))
    service.setShortcut(dbus.Array(focus_id, signature='s'), dbus.Array([FOCUS_KEY], signature='i'), dbus.UInt32(2))

    def pressed(component, action, timestamp):
        if component == COMPONENT and action == FOCUS_ACTION:
            subprocess.Popen([sys.executable, str(FOCUS_APP)], start_new_session=True,
                             stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            return
        if component == COMPONENT and action == ACTION:
            subprocess.Popen([sys.executable, str(APP), '--popup'], start_new_session=True,
                             stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    bus.add_signal_receiver(pressed, signal_name='globalShortcutPressed',
                            dbus_interface='org.kde.kglobalaccel.Component',
                            path='/component/yomitan_dictionary_lookup')
    GLib.MainLoop().run()


if __name__ == '__main__':
    main()
